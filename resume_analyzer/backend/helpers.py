import json
from typing import List, Dict, Tuple
import torch
import torch.nn.functional as F
from .model import Qwen2VLClient
from dotenv import load_dotenv
from ..ingestion.helpers import load_env_vars, connect_postgres
from ..ingestion.helpers import embed_sentences


def fetch_candidate_keys(matched: List[str]) -> Dict[str, str]:
    """
    Given a list of filenames from resumes_metadata, fetch their candidate_key
    values from Postgres and return a dict mapping filename -> candidate_key.
    """
    env = load_env_vars()
    conn = connect_postgres(env)
    cur = conn.cursor()
    # Use ANY to match any filename in the list
    cur.execute(
        "SELECT filename, candidate_key FROM public.resumes_metadata WHERE filename = ANY(%s);",
        (matched,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # Build and return the mapping
    return {filename: candidate_key for filename, candidate_key in rows}

def find_matching_resumes_by_candidates(
    candidate_keys: List[str],
    input_skills: List[str],
    threshold: float = 0.9,
    min_ratio: float = 0.5
) -> Dict[str, List[Tuple[str, str, float]]]:
    """
    For each resume under the given candidate_keys, compute per-input-skill cosine
    similarities against each stored skill embedding. Print out the matched tuple
    (input_skill, stored_skill, score) for every resume—even those that don’t pass.
    Return only those resumes where the fraction of input skills scoring ≥ threshold
    exceeds min_ratio.

    Returns:
      { filename: [(input_skill, matched_skill, score), ...], ... }
    """
    if not candidate_keys or not input_skills:
        return {}

    # 1) Embed & normalize inputs
    input_vecs = torch.tensor(embed_sentences(input_skills))  # (K, D)
    input_norm = F.normalize(input_vecs, dim=1)               # (K, D)

    # 2) Fetch only the rows for these candidate_keys
    env  = load_env_vars()
    conn = connect_postgres(env)
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT filename, skills_txt, skills_embed
          FROM public.resumes_normal
         WHERE candidate_key = ANY(%s);
        """,
        (candidate_keys,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    matches: Dict[str, List[Tuple[str, str, float]]] = {}
    for filename, skills_txt, emb_json in rows:
        stored_names = [s.strip() for s in skills_txt.split(",") if s.strip()]
        stored = torch.tensor(emb_json)                         # (M, D)
        if stored.numel() == 0 or len(stored_names) != stored.size(0):
            print(f"{filename}: no embeddings or name mismatch")
            continue

        stored_norm = F.normalize(stored, dim=1)                # (M, D)
        cosims      = input_norm @ stored_norm.T                # (K, M)

        result: List[Tuple[str, str, float]] = []
        count_ok = 0

        for i, skill in enumerate(input_skills):
            row = cosims[i]                                     # (M,)
            best_score, best_idx = row.max(dim=0)
            score  = float(best_score.item())
            match  = stored_names[best_idx.item()]
            result.append((skill, match, score))
            if score >= threshold:
                count_ok += 1

        ratio = count_ok / len(input_skills)
        # Always print the tuples for inspection
        print(f"{filename}: matches = {result}, ratio = {ratio:.2f}")

        if ratio >= min_ratio:
            matches[filename] = result

    return matches


def _get_all_candidate_keys() -> List[str]:
    """
    Get all available candidate keys from the database
    """
    env = load_env_vars()
    conn = connect_postgres(env)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT candidate_key FROM public.resumes_metadata;")
    keys = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return keys

    

def _handle_resume_details_query(user_query: str, candidate_key: str) -> Dict[str, any]:
    """
    Handle queries about specific resume details for a single candidate
    
    Args:
        user_query: The specific question about the candidate
        candidate_key: Single candidate key to query
    """
    if not candidate_key:
        return {
            "answer": "Please specify a candidate to get resume details.",
            "query_type": "resume_details",
            "candidates_analyzed": [],
            "skills_extracted": [],
            "additional_info": {"error": "No candidate specified"}
        }
    
    # Get resume data for the single candidate
    env = load_env_vars()
    conn = connect_postgres(env)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT filename, candidate_key, skills_summary_txt, full_resume_txt
        FROM public.resumes_normal
        WHERE candidate_key = %s AND skills_summary_txt IS NOT NULL;
        """,
        (candidate_key,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if not row:
        return {
            "answer": f"I don't have detailed resume information for candidate '{candidate_key}'. Please check if the candidate exists in our database.",
            "query_type": "resume_details",
            "candidates_analyzed": [],
            "skills_extracted": [],
            "additional_info": {"candidate_key": candidate_key, "error": "Candidate not found"}
        }
    
    filename, candidate_key, summary_txt, full_txt = row
    
    # Prepare context for detailed query - use structured summary primarily
    context = summary_txt if summary_txt else full_txt[:3000]  # Fallback to full text if needed
    
    DETAILS_PROMPT = f"""
        Based on the resume information below for {candidate_key}, answer this specific question: {user_query}

        CANDIDATE: {candidate_key} ({filename})
        RESUME DATA:
        {context}

        Provide a detailed, accurate answer based on the resume information. If the specific information isn't available in the resume, clearly state that and suggest what information is available instead.

        Focus on being specific and citing relevant details from the resume.
        """
    
    try:
        reply = qwen.chat_completion(
            question=DETAILS_PROMPT,
            system_prompt="You are an expert at extracting specific information from individual resumes."
        ).strip()
        
        return {
            "answer": reply,
            "query_type": "resume_details",
            "candidates_analyzed": [candidate_key],
            "skills_extracted": [],
            "additional_info": {
                "candidate_key": candidate_key,
                "filename": filename,
                "data_source": "structured_summary" if summary_txt else "full_text"
            }
        }
        
    except Exception as e:
        return {
            "answer": f"I encountered an error while retrieving resume details for {candidate_key}: {str(e)}",
            "query_type": "resume_details",
            "candidates_analyzed": [candidate_key],
            "skills_extracted": [],
            "additional_info": {
                "candidate_key": candidate_key,
                "error": str(e)
            }
        }

def _intelligent_candidate_matching(user_query: str, candidate_keys: List[str]) -> str:
    """
    Use Qwen to intelligently match candidate names mentioned in the query
    """
    candidates_list = ", ".join(candidate_keys)
    
    CANDIDATE_EXTRACTION_PROMPT = f"""
        You are helping to identify which candidate a user is asking about.

        USER QUERY: "{user_query}"

        AVAILABLE CANDIDATES: {candidates_list}

        Analyze the user query and determine which specific candidate they are referring to. Look for:
        1. Direct name mentions
        2. Partial name matches
        3. Variations of names (nicknames, first names only, etc.)

        Return ONLY the exact candidate key from the available list, or "NONE" if no clear match is found.

        Examples:
        - If query mentions "Leon" and candidates include "LeonLimJianPing" → return "LeonLimJianPing"
        - If query mentions "John's background" and candidates include "JohnDoe" → return "JohnDoe"
        - If query doesn't mention any specific candidate → return "NONE"

        Return only the candidate key or "NONE":
        """
    
    try:
        reply = qwen.chat_completion(
            question=CANDIDATE_EXTRACTION_PROMPT,
            system_prompt="You are an expert at matching candidate names from user queries."
        ).strip()
        
        # Clean up response
        reply = reply.strip('"').strip("'").strip()
        
        if reply == "NONE" or reply not in candidate_keys:
            print("----------------------------------------------------")
            print(f"No candidate match found via Qwen. Reply: {reply}")
            print("----------------------------------------------------")
            return None
        
        print(f"Qwen matched candidate: {reply}")
        return reply
        
    except Exception as e:
        print("----------------------------------------------------")
        print(f"Error in intelligent candidate matching: {e}")
        print("----------------------------------------------------")
        return None


def extract_skills_from_query(client: Qwen2VLClient, text: str) -> List[str]:
    """
    Given a free‐form user query, call Qwen2VL to extract a JSON list of skills.
    """

    # Prompt template for extracting skills from arbitrary text
    SKILLS_TEXT_PROMPT = """
    You are an AI assistant that extracts **technical and domain skills** from a user’s query or text.
    Your task:
    1. Read the input text carefully.
    2. Find every mention of programming languages, tools, frameworks, libraries, platforms, or methodologies.
    3. Return a JSON array of unique skill names, for example:

    ["Python", "Docker", "React", "AWS", "Agile"]

    **Rules:**
    - Do NOT include soft skills (e.g., “communication”, “teamwork”).
    - Do NOT include duplicate names; the array should be unique.
    - Return **only** the JSON array—no extra text or formatting.
    """.strip()

    # Combine prompt and the user text
    prompt = SKILLS_TEXT_PROMPT + f"\n\nInput text:\n\"\"\"\n{text}\n\"\"\"\n"
    # Ask Qwen
    reply = client.chat_completion(
        question=prompt,
        system_prompt="You are a skills‐extraction assistant."
    ).strip()

    # Remove markdown/code fences if any
    if reply.startswith("```"):
        reply = reply.strip("`").strip()

    # Attempt to parse JSON
    try:
        skills = json.loads(reply)
        if isinstance(skills, list):
            return [s.strip() for s in skills if isinstance(s, str)]
    except json.JSONDecodeError:
        # fallback: find bracketed section
        import re
        m = re.search(r"\[.*\]", reply, flags=re.S)
        if m:
            try:
                skills = json.loads(m.group(0))
                return [s.strip() for s in skills if isinstance(s, str)]
            except json.JSONDecodeError:
                pass
    # As last fallback, split on commas
    return [part.strip().strip('"') for part in reply.strip("[]").split(",") if part.strip()]

def _get_overall_judgment(summary_txt: str, input_skills: List[str]) -> Dict[str, any]:
    """
    Get initial judgment about candidate suitability - NO SCORING, just reasoning and transferability
    """
    skills_list = ", ".join(input_skills)
    
    OVERALL_JUDGMENT_PROMPT = f"""
        You are an expert HR analyst. Analyze this candidate's resume summary and assess their fit for the required skills.

        REQUIRED SKILLS: {skills_list}

        CANDIDATE RESUME SUMMARY:
        {summary_txt}

        Provide your analysis in this exact JSON format:
        {{
        "reasoning": "Detailed explanation of the candidate's relevant skills, experience, and how they relate to requirements",
        "transferability": "Assessment of candidate's potential and ability to adapt/learn missing skills"
        }}

        FOCUS ON:
        1. What specific skills and experience the candidate has
        2. How their background relates to the requirements
        3. Their potential to learn or adapt to missing skills
        4. Quality and depth of their experience

        NO SCORING - just provide thoughtful analysis of their capabilities and potential.
        Return ONLY the JSON object.
        """

    try:
        reply = qwen.chat_completion(
            question=OVERALL_JUDGMENT_PROMPT,
            system_prompt="You are an expert HR analyst focusing on candidate analysis."
        ).strip()
        
        # Clean up response
        if reply.startswith("```"):
            reply = "\n".join(
                line for line in reply.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        
        judgment = json.loads(reply)
        
        # Validate required fields
        required_fields = ["reasoning", "transferability"]
        if all(field in judgment for field in required_fields):
            return judgment
        else:
            raise ValueError("Missing required fields in judgment")
            
    except (json.JSONDecodeError, ValueError) as e:
        print("----------------------------------------------------")
        print(f"Error parsing overall judgment: {e}")
        print("----------------------------------------------------")
        return {
            "reasoning": f"Failed to analyze candidate due to parsing error: {str(e)}",
            "transferability": "Unable to assess transferability due to analysis error"
        }


def _get_initial_judgments(candidate_keys: List[str], input_skills: List[str]) -> Dict[str, Dict[str, any]]:
    """
    Phase 1: Get reasoning and transferability assessment for each candidate
    """
    env = load_env_vars()
    conn = connect_postgres(env)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT filename, candidate_key, skills_summary_txt
        FROM public.resumes_normal
        WHERE candidate_key = ANY(%s) AND skills_summary_txt IS NOT NULL;
        """,
        (candidate_keys,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    results = {}
    
    for filename, candidate_key, summary_txt in rows:
        print("----------------------------------------------------")
        print(f"Phase 1: Analyzing {filename} for candidate {candidate_key}...")
        print("----------------------------------------------------")

        # Get reasoning and transferability only
        initial_judgment = _get_overall_judgment(summary_txt, input_skills)
        initial_judgment["summary_txt"] = summary_txt  # Store for comparison phase
        initial_judgment["candidate_key"] = candidate_key
        
        results[filename] = initial_judgment

    return results

# Create filename matching helpers
def find_best_match(returned_filename, available_filenames):
    """Find the best matching filename from available options"""
    
    # 1. Exact match
    if returned_filename in available_filenames:
        return returned_filename
    
    # 2. Case-insensitive match
    for filename in available_filenames:
        if filename.lower() == returned_filename.lower():
            return filename
    
    # 3. Fuzzy matching - check if core parts match
    returned_clean = returned_filename.lower().replace(' ', '').replace('-', '').replace('_', '')
    for filename in available_filenames:
        filename_clean = filename.lower().replace(' ', '').replace('-', '').replace('_', '')
        if returned_clean == filename_clean:
            return filename
    
    # 4. Partial matching - check if most characters match
    for filename in available_filenames:
        # Calculate simple similarity
        returned_chars = set(returned_filename.lower().replace(' ', ''))
        filename_chars = set(filename.lower().replace(' ', ''))
        
        intersection = len(returned_chars & filename_chars)
        union = len(returned_chars | filename_chars)
        similarity = intersection / union if union > 0 else 0
        
        if similarity > 0.8:  # 80% character similarity
            return filename
    
    return None
        

def _comparative_reranking(initial_results: Dict[str, Dict[str, any]], input_skills: List[str]) -> Dict[str, Dict[str, any]]:
    """
    Phase 2: Rank all candidates based on their reasoning and suitability
    """
    if len(initial_results) <= 1:
        # Single candidate gets rank 1
        for filename, data in initial_results.items():
            data["rank_position"] = 1
            data.pop("summary_txt", None)
        return initial_results
    
    print("----------------------------------------------------")
    print(f"Available filenames in initial_results: {list(initial_results.keys())}")
    print("----------------------------------------------------")
    
    
    # Prepare all candidate reasoning for ranking
    skills_list = ", ".join(input_skills)
    candidates_analysis = []
    
    for filename, data in initial_results.items():
        candidates_analysis.append(f"""
        **{data['candidate_key']} ({filename}):**
        Reasoning: {data['reasoning']}
        Transferability: {data['transferability']}
        """)
            
    RANKING_PROMPT = f"""
        You are ranking candidates for a role requiring these skills: {skills_list}

        Here are ALL the candidates with their analysis:
        {''.join(candidates_analysis)}

        Your task: Rank these candidates from BEST to WORST based on their suitability for the role.

        Return a JSON object with this EXACT structure:
        {{
        "rankings": [
            {{
            "filename": "exact_filename_here",
            "rank_position": 1,
            "ranking_reasoning": "Why this candidate is ranked at this position compared to others"
            }}
        ]
        }}

        CRITICAL: Use the EXACT filename as provided in the candidate analysis above.
        Available filenames: {list(initial_results.keys())}
        You MUST rank ALL {len(initial_results)} candidates. Use exact filenames from above.


        RANKING CRITERIA:
        1. Depth and relevance of technical skills
        2. Transferability and learning potential
        3. Overall fit for the required skills

        List candidates in RANKED ORDER (position 1 = best, position 2 = second best, etc.).
        Return ONLY the JSON object.
        """

    try:
        reply = qwen.chat_completion(
            question=RANKING_PROMPT,
            system_prompt="You are an expert at ranking candidates based on their suitability."
        ).strip()
        
        # Clean up response
        if reply.startswith("```"):
            reply = "\n".join(
                line for line in reply.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        
        ranking_result = json.loads(reply)
        
        print("----------------------------------------------------")
        print(f"Ranking completed for {len(ranking_result.get('rankings', []))} candidates")
        print("----------------------------------------------------")
        
        # Apply rankings to results
        final_results = {}
        rankings = ranking_result.get("rankings", [])
        
        available_filenames = list(initial_results.keys())
        
        for rank_data in rankings:
            returned_filename = rank_data["filename"]
            
            # Find best matching filename
            matched_filename = find_best_match(returned_filename, available_filenames)
            
            if matched_filename:
                if matched_filename != returned_filename:
                    print("----------------------------------------------------")
                    print(f"📋 Matched '{returned_filename}' → '{matched_filename}'")
                    print("----------------------------------------------------")
                
                # Start with initial data
                final_data = initial_results[matched_filename].copy()
                
                # Add ranking results
                final_data.update({
                    "rank_position": rank_data["rank_position"],
                    "ranking_reasoning": rank_data["ranking_reasoning"]
                })
                
                # Clean up temporary data
                final_data.pop("summary_txt", None)
                
                final_results[matched_filename] = final_data
            else:
                print("----------------------------------------------------")
                print(f"⚠️  Warning: Could not match '{returned_filename}' to any filename")
                print(f"Available: {available_filenames}")
                print("----------------------------------------------------")
        
        # Add any missing candidates with default ranks
        for filename, data in initial_results.items():
            if filename not in final_results:
                data_copy = data.copy()
                data_copy.pop("summary_txt", None)
                data_copy.update({
                    "rank_position": len(rankings) + 1,
                    "ranking_reasoning": "Not included in comparative ranking"
                })
                final_results[filename] = data_copy
                print("----------------------------------------------------")
                print(f"📋 Added missing candidate '{filename}' with default rank")
                print("----------------------------------------------------")
        
        return final_results
        
    except (json.JSONDecodeError, ValueError) as e:
        print("----------------------------------------------------")
        print(f"Error in ranking: {e}")
        print("Falling back to simple ordering...")
        print("----------------------------------------------------")
        
        # Fallback: assign ranks in order
        fallback_results = {}
        for i, (filename, data) in enumerate(initial_results.items(), 1):
            data_copy = data.copy()
            data_copy.pop("summary_txt", None)
            data_copy.update({
                "rank_position": i,
                "ranking_reasoning": "Fallback ranking due to analysis error"
            })
            fallback_results[filename] = data_copy
        
        return fallback_results

def judge_candidates_by_summary(
    candidate_keys: List[str],
    input_skills: List[str],
) -> Dict[str, Dict[str, any]]:
    """
    Enhanced version with comparative reranking after initial judgment
    """
    if not candidate_keys or not input_skills:
        return {}

    # Phase 1: Get initial judgments for all candidates
    initial_results = _get_initial_judgments(candidate_keys, input_skills)
    
    if len(initial_results) <= 1:
        return initial_results
    
    # Phase 2: Comparative reranking
    print("----------------------------------------------------")
    print("🔄 Starting comparative reranking phase...")
    print("----------------------------------------------------")
    
    reranked_results = _comparative_reranking(initial_results, input_skills)
    
    return reranked_results

def _handle_skill_matching_query(user_query: str, candidate_keys: List[str], context_limit: int) -> Dict[str, any]:
    """
    Handle queries about finding candidates with specific skills
    """
    # Extract skills from the query
    skills = extract_skills_from_query(qwen, user_query)
    
    if not skills:
        return {
            "answer": "I couldn't identify any specific technical skills in your query. Could you be more specific about the technologies or skills you're looking for?",
            "query_type": "skill_matching",
            "candidates_analyzed": [],
            "skills_extracted": [],
            "additional_info": {"suggestion": "Try mentioning specific technologies like 'Python', 'React', 'AWS', etc."}
        }
    
    # Analyze candidates
    results = judge_candidates_by_summary(candidate_keys, skills)
    
    # Sort by score and take top matches
    sorted_results = sorted(
        results.items(), 
        key=lambda x: x[1].get("rank_position", 999)  # Sort by rank (1 = best)
    )[:context_limit]

    answer_parts = [f"Based on your query about {', '.join(skills)}, here are the candidates ranked by suitability:\n"]
        
    for filename, analysis in sorted_results:
        rank = analysis.get("rank_position", "?")
        reasoning = analysis.get("ranking_reasoning", analysis.get("reasoning", "No reasoning provided"))
        
        answer_parts.append(f"**#{rank}. {filename}**")
        answer_parts.append(f"   {reasoning}\n")
    
    answer = "\n".join(answer_parts)

    return {
        "answer": answer,
        "query_type": "skill_matching",
        "candidates_analyzed": [item[0] for item in sorted_results],
        "skills_extracted": skills,
        "additional_info": {
            "total_candidates_checked": len(results),
            "top_matches": len(sorted_results),
            "ranking_method": "comparative_suitability"
        }
    }

def _analyze_user_query(user_query: str) -> Dict[str, any]:
    """
    Analyze the user query to determine intent and extract key information
    """
    
    QUERY_ANALYSIS_PROMPT = f"""
        Analyze this user query and classify it into one of these categories:

        USER QUERY: "{user_query}"

        Return a JSON object with this structure:
        {{
        "type": "category_name",
        "confidence": 0.95,
        "key_terms": ["term1", "term2"],
        "intent": "brief description of what user wants"
        }}

        CATEGORIES:
        1. "skill_matching" - User asking about candidates with specific skills/technologies
        Examples: "Who has Python experience?", "Find developers with React and Node.js"

        2. "resume_details" - User asking about specific details from resumes
        Examples: "What's John's education background?", "Tell me about Mary's projects"

        3. "general_question" - General questions about the candidate pool
        Examples: "How many candidates do we have?", "What's the average experience level?"

        4. "unknown" - Query doesn't fit other categories

        Focus on the main intent and extract key terms that might be relevant.
        Return ONLY the JSON object.
        """
    
    try:
        reply = qwen.chat_completion(
            question=QUERY_ANALYSIS_PROMPT,
            system_prompt="You are an expert at understanding user intents in HR/recruiting contexts."
        ).strip()
        
        # Clean up response
        if reply.startswith("```"):
            reply = "\n".join(
                line for line in reply.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        
        analysis = json.loads(reply)
        return analysis
        
    except (json.JSONDecodeError, ValueError) as e:
        print("----------------------------------------------------")
        print(f"Error analyzing query: {e}")
        print("----------------------------------------------------")
        return {
            "type": "unknown",
            "confidence": 0.0,
            "key_terms": [],
            "intent": "Failed to analyze query"
        }

def chat_with_resumes(
    user_query: str,
    candidate_keys: List[str] = None,
    context_limit: int = 3
) -> Dict[str, any]:
    """
    Chat function that accepts user queries and provides intelligent answers about resumes.
    
    Args:
        user_query: Natural language question from the user
        candidate_keys: Optional list of specific candidates to focus on
        context_limit: Maximum number of resume contexts to include
    
    Returns:
        {
            "answer": str,           # Main response to user
            "query_type": str,       # Type of query detected
            "candidates_analyzed": List[str],  # Candidates that were analyzed
            "skills_extracted": List[str],     # Skills found in query (if applicable)
            "additional_info": Dict  # Extra context or suggestions
        }
    """
    
    # Get all candidate keys if none provided
    if not candidate_keys:
        candidate_keys = _get_all_candidate_keys()
    
    # Step 1: Classify the query type and extract relevant information
    query_analysis = _analyze_user_query(user_query)
    query_type = query_analysis["type"]
    print("----------------------------------------------------")
    print(f"🔍 Detected query type: {query_type}")
    print("----------------------------------------------------")
    
    # Step 2: Handle different types of queries
    if query_type == "skill_matching":
        return _handle_skill_matching_query(user_query, candidate_keys, context_limit)
    
    elif query_type == "resume_details":
        # Extract specific candidate from the user query
        specific_candidate = _intelligent_candidate_matching(user_query, candidate_keys)
        print("----------------------------------------------------")
        print(f"🔍 Specific candidate identified: {specific_candidate}")
        print("----------------------------------------------------")
        
        if not specific_candidate:
            return {
                "answer": f"I couldn't identify which specific candidate you're asking about. Available candidates: {', '.join(candidate_keys[:10])}{'...' if len(candidate_keys) > 10 else ''}",
                "query_type": "resume_details",
                "candidates_analyzed": [],
                "skills_extracted": [],
                "additional_info": {
                    "available_candidates": candidate_keys,
                    "suggestion": "Please mention a specific candidate name in your question."
                }
            }
        
        return _handle_resume_details_query(user_query, specific_candidate)
    
    else:
        return {
            "answer": "I'm not sure how to help with that specific question. Try asking about specific skills or candidate details.",
            "query_type": "unknown",
            "candidates_analyzed": [],
            "skills_extracted": [],
            "additional_info": {}
        }


qwen = Qwen2VLClient(
    host="http://localhost",
    port=8001,
    model="Qwen/Qwen2.5-VL-7B-Instruct",
    temperature=0.0  # deterministic
)



if __name__ == "__main__":
    print("----------------------------------------------------")
    print("🤖 Resume Chat Assistant Demo")
    print("----------------------------------------------------")
    
    # Example candidate keys available in database
    candidate_keys = ["LeonLimJianPing", "DIAN JIAO", "GaryQuahYiKai", "LiJialing"]
    
    print("----------------------------------------------------")
    print("Available candidates:", ", ".join(candidate_keys))
    print("----------------------------------------------------")
    
    # ============================================================================
    # USE CASE 1: SKILL-BASED MATCHING QUERY
    # ============================================================================
    print("----------------------------------------------------")
    print("🔍 USE CASE 1: Skill-based candidate matching")
    print("----------------------------------------------------")
    
    skill_query = "Find candidates with unity, game dev experience"
    
    print("----------------------------------------------------")
    print(f"👤 User Query: {skill_query}")
    print("----------------------------------------------------")
    
    skill_result = chat_with_resumes(
        user_query=skill_query,
        candidate_keys=candidate_keys,
        context_limit=3
    )
    
    print("----------------------------------------------------")
    print("🤖 Assistant Response:")
    print("----------------------------------------------------")
    print(skill_result["answer"])
    print("----------------------------------------------------")
    print(f"📊 Query Type: {skill_result['query_type']}")
    print(f"🔧 Skills Extracted: {skill_result['skills_extracted']}")
    print(f"👥 Candidates Analyzed: {skill_result['candidates_analyzed']}")
    print("----------------------------------------------------")
    
    # ============================================================================
    # USE CASE 2: SPECIFIC CANDIDATE DETAILS QUERY
    # ============================================================================
    # print("----------------------------------------------------")
    # print("📋 USE CASE 2: Specific candidate details")
    # print("----------------------------------------------------")
    
    # detail_query = "What is Leon's educational background and work experience?"
    
    # print("----------------------------------------------------")
    # print(f"👤 User Query: {detail_query}")
    # print("----------------------------------------------------")
    
    # detail_result = chat_with_resumes(
    #     user_query=detail_query,
    #     candidate_keys=candidate_keys,
    # )
    
    # print("----------------------------------------------------")
    # print("🤖 Assistant Response:")
    # print("----------------------------------------------------")
    # print(detail_result["answer"])
    # print("----------------------------------------------------")
    # print(f"📊 Query Type: {detail_result['query_type']}")
    # print(f"👤 Candidate Analyzed: {detail_result['candidates_analyzed']}")
    # print(f"📁 Additional Info: {detail_result['additional_info']}")
    # print("----------------------------------------------------")
    

def detect_email_intent(user_input: str, candidate_keys: List[str]) -> Dict[str, any]:
    """
    Use LLM to detect if user wants to send an email and extract details including specific fields.
    """
    candidates_list = ", ".join(candidate_keys)
    
    EMAIL_INTENT_PROMPT = f"""
        Analyze this user query to determine if they want to send an email to a candidate and extract specific fields.

        USER QUERY: "{user_input}"
        AVAILABLE CANDIDATES: {candidates_list}

        Return a JSON object with this structure:
        {{
        "is_email_request": true/false,
        "template_type": "template_name_or_null",
        "candidate_key": "exact_candidate_key_or_null",
        "confidence": 0.95,
        "intent": "brief description",
        "extracted_fields": {{
            "position": "extracted_position_or_null",
            "date": "extracted_date_or_null", 
            "time": "extracted_time_or_null",
            "format": "extracted_format_or_null",
            "duration": "extracted_duration_or_null",
            "start_date": "extracted_start_date_or_null",
            "end_date": "extracted_end_date_or_null",
            "salary": "extracted_salary_or_null",
            "employment_type": "extracted_employment_type_or_null"
        }}
        }}

        EMAIL TYPES TO DETECT:
        
        1. "offer_template" - Sending job/internship offers
        Examples: "send offer email to John", "email offer to Mary", "offer John the position"
        REQUIRED FIELDS TO EXTRACT:
        - position: job/internship position (extract if mentioned)
        - start_date: when they should start (COMPULSORY - extract from phrases like "start on Monday", "begin January 15", "starting next week")
        - end_date: when they should finish (COMPULSORY - extract from phrases like "until March", "ending in June", OR calculate from start_date + duration)
        - salary: compensation amount (COMPULSORY - extract from phrases like "$1500/month", "salary 2000", "1400 dollars")
        - duration: work period (COMPULSORY - extract from phrases like "3 months", "June to August", "6-month internship")
        - employment_type: work type (extract from phrases like "part-time", "full-time", "PT", "FT", "part time", "full time")

        2. "interview_invitation" - Sending interview invitations  
        Examples: "invite Sarah for interview", "send interview email to Mike", "schedule interview with Lisa"
        REQUIRED FIELDS TO EXTRACT:
        - position: job/internship position (extract if mentioned)
        - date: interview date (COMPULSORY - extract from phrases like "tomorrow", "January 15", "next Monday", "15th")
        - time: interview time (COMPULSORY - extract from phrases like "2pm", "14:00", "2 o'clock", "afternoon")
        - format: interview format (OPTIONAL - extract from phrases like "online", "zoom", "in-person", "virtual", "office". Default: "in-person")
        - duration: interview length (OPTIONAL - extract from phrases like "45 minutes", "1 hour", "30 mins". Default: "1 hour")

        3. "rejection_email" - Sending rejection emails
        Examples: "send rejection to Alice", "reject Bob via email", "email rejection to Tom"
        OPTIONAL FIELDS TO EXTRACT:
        - position: job/internship position (extract if mentioned, otherwise will use database default)

        FIELD EXTRACTION RULES:
        - Extract fields only when explicitly mentioned in the user query
        - Set to null if not mentioned
        - Be flexible with date/time formats (relative dates like "tomorrow", "next week" are valid)
        - **For employment_type**: Extract "part-time", "full-time", "PT", "FT", "part time", "full time" (case insensitive)
        - **For duration in offers**: 
          * Extract numeric durations like "3 months", "6-month internship", "June-August"
          * For program keywords: "ATAP" = 6 months, "SIP" = 3 months (May-August)
          * For non-numeric terms like "summer internship", extract as duration but system will use defaults
          * If both numeric and non-numeric are present like "6-month summer internship", extract the numeric part: "6 months"
        - **IMPORTANT DURATION LOGIC**:
          * If both start_date and end_date are mentioned explicitly → extract both, set duration to null
          * If start_date and duration are mentioned → extract both, set end_date to null
          * If only duration is mentioned → extract duration, set start_date and end_date to null
        - For salary: extract any monetary amount mentioned
        - **DO NOT calculate or infer dates - only extract what is explicitly stated**
        - **DO NOT assume employment_type unless explicitly mentioned**

        CANDIDATE MATCHING:
        - Look for candidate names mentioned in the query
        - Match against available candidates (case-insensitive, partial matching OK)
        - Return the EXACT candidate key from the available list

        EXAMPLES:

        Query: "Send offer email to John for software engineer position, starting January 15th, salary $2000/month, 6-month internship, part-time"
        Response: {{
            "is_email_request": true,
            "template_type": "offer_template", 
            "candidate_key": "John",
            "extracted_fields": {{
                "position": "software engineer position",
                "start_date": "January 15th",
                "end_date": null,
                "salary": "$2000/month", 
                "duration": "6-month internship",
                "employment_type": "part-time",
                "date": null, "time": null, "format": null
            }}
        }}

        Query: "Offer Mary the data analyst role, start February 1st, end August 31st, salary $1800/month, FT"
        Response: {{
            "is_email_request": true,
            "template_type": "offer_template",
            "candidate_key": "Mary",
            "extracted_fields": {{
                "position": "data analyst role",
                "start_date": "February 1st", 
                "end_date": "August 31st",
                "salary": "$1800/month",
                "duration": null,
                "employment_type": "FT",
                "date": null, "time": null, "format": null
            }}
        }}

        Query: "Send offer to Tom, starting next Monday, duration 4 months, salary 2500, PT work"
        Response: {{
            "is_email_request": true,
            "template_type": "offer_template",
            "candidate_key": "Tom",
            "extracted_fields": {{
                "position": null,
                "start_date": "next Monday",
                "end_date": null,
                "salary": "2500",
                "duration": "4 months",
                "employment_type": "PT",
                "date": null, "time": null, "format": null
            }}
        }}
        
        Query: "Send offer to Alice for full-time ATAP program, starting January 15th, salary $2000/month"
        Response: {{
            "is_email_request": true,
            "template_type": "offer_template",
            "candidate_key": "Alice",
            "extracted_fields": {{
                "position": null,
                "start_date": "January 15th",
                "end_date": null,
                "salary": "$2000/month",
                "duration": "ATAP program",
                "employment_type": "full-time",
                "date": null, "time": null, "format": null
            }}
        }}
        
        Query: "Email offer to Bob for SIP program, salary 1800, Full Time"
        Response: {{
            "is_email_request": true,
            "template_type": "offer_template",
            "candidate_key": "Bob",
            "extracted_fields": {{
                "position": null,
                "start_date": null,
                "end_date": null,
                "salary": "1800",
                "duration": "SIP program",
                "employment_type": "Full time",
                "date": null, "time": null, "format": null
            }}
        }}

        Query: "Invite Sarah for interview tomorrow at 2pm via Zoom, 45 minutes"
        Response: {{
            "is_email_request": true,
            "template_type": "interview_invitation",
            "candidate_key": "Sarah", 
            "extracted_fields": {{
                "position": null,
                "date": "tomorrow",
                "time": "2pm", 
                "format": "Zoom",
                "duration": "45 minutes",
                "start_date": null, "end_date": null, "salary": null, "employment_type": null
            }}
        }}
        
        Query: "Schedule interview with Mike for January 20th at 10am, in-person meeting, 1 hour"
        Response: {{
            "is_email_request": true,
            "template_type": "interview_invitation",
            "candidate_key": "Mike",
            "extracted_fields": {{
                "position": null,
                "date": "January 20th",
                "time": "10am",
                "format": "in-person",
                "duration": "1 hour",
                "start_date": null, "end_date": null, "salary": null, "employment_type": null
            }}
        }}
        
        Query: "Send interview email to Lisa next Monday 3pm for software engineer position"
        Response: {{
            "is_email_request": true,
            "template_type": "interview_invitation",
            "candidate_key": "Lisa",
            "extracted_fields": {{
                "position": "software engineer position",
                "date": "next Monday",
                "time": "3pm",
                "format": null,
                "duration": null,
                "start_date": null, "end_date": null, "salary": null, "employment_type": null
            }}
        }}
        
        Query: "Send rejection letter to Alice"
        Response: {{
            "is_email_request": true,
            "template_type": "rejection_email",
            "candidate_key": "Alice",
            "extracted_fields": {{
                "position": null,
                "date": null, "time": null, "format": null, "duration": null,
                "start_date": null, "end_date": null, "salary": null, "employment_type": null
            }}
        }}
        
        Query: "Reject Bob via email for the software engineer internship"
        Response: {{
            "is_email_request": true,
            "template_type": "rejection_email",
            "candidate_key": "Bob",
            "extracted_fields": {{
                "position": "software engineer internship",
                "date": null, "time": null, "format": null, "duration": null,
                "start_date": null, "end_date": null, "salary": null, "employment_type": null
            }}
        }}
        
        Query: "Send rejection email to Carol for data analyst role"
        Response: {{
            "is_email_request": true,
            "template_type": "rejection_email",
            "candidate_key": "Carol",
            "extracted_fields": {{
                "position": "data analyst role",
                "date": null, "time": null, "format": null, "duration": null,
                "start_date": null, "end_date": null, "salary": null, "employment_type": null
            }}
        }}

        Return ONLY the JSON object.
        """
    
    try:
        reply = qwen.chat_completion(
            question=EMAIL_INTENT_PROMPT,
            system_prompt="You are an expert at understanding email-related requests and extracting specific fields from HR contexts."
        ).strip()
        
        # Clean up response
        if reply.startswith("```"):
            reply = "\n".join(
                line for line in reply.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        
        email_intent = json.loads(reply)
        
        # Validate the response structure
        required_fields = ["is_email_request", "template_type", "candidate_key", "extracted_fields"]
        if not all(field in email_intent for field in required_fields):
            print(f"Invalid email intent response: {email_intent}")
            return {'is_email_request': False}
        
        # Additional validation - ensure candidate exists if specified
        if email_intent['is_email_request'] and email_intent['candidate_key']:
            if email_intent['candidate_key'] not in candidate_keys:
                # Try to find a close match
                candidate_key_lower = email_intent['candidate_key'].lower()
                for key in candidate_keys:
                    if candidate_key_lower in key.lower() or key.lower() in candidate_key_lower:
                        email_intent['candidate_key'] = key
                        break
                else:
                    # No match found
                    original_candidate = email_intent['candidate_key']
                    email_intent['candidate_key'] = None
                    email_intent['intent'] = f"Candidate '{original_candidate}' not found in current results"
        
        print("----------------------------------------------------")
        print(f"📧 Email intent detected: {email_intent}")
        print("----------------------------------------------------")
        
        return email_intent
        
    except (json.JSONDecodeError, ValueError) as e:
        print("----------------------------------------------------")
        print(f"Error detecting email intent: {e}")
        print("----------------------------------------------------")
        return {'is_email_request': False}