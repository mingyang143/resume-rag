import os
import json
import tempfile
import sys
import glob
import psycopg2
from psycopg2.extras import RealDictCursor
import subprocess
from typing import Dict, Optional, List, Callable
from dateutil import parser
import fitz
import faiss
import numpy as np
import pickle
from pathlib import Path
import re

from pdf2image import convert_from_path    # pip install pdf2image
from dotenv import load_dotenv

from ..backend.model import Qwen2VLClient    
from .helpers import (
    connect_postgres,
    embed_sentences,
    ensure_resumes_normal_table,
    upsert_resumes_normal,
)

# Load environment variables from .env file
load_dotenv()
# Add FAISS configuration constants
FAISS_INDEX_PATH = "./resume_faiss_index.bin"
FAISS_METADATA_PATH = "./resume_faiss_metadata.pkl"
CHUNK_SIZE = 512  # Characters per chunk
CHUNK_OVERLAP = 50  # Overlap between chunks


def load_env_vars():
    """Load environment variables (or complain if missing)."""
    env = {
        "PG_USER":          os.getenv("PG_USER"),
        "PG_PASSWORD":      os.getenv("PG_PASSWORD"),
        "PG_DB":            os.getenv("PG_DB"),
        "PG_HOST":          os.getenv("PG_HOST"),
        "PG_PORT":          os.getenv("PG_PORT"),
    }
    missing = [k for k,v in env.items() if v is None]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {missing}")
    return env

# ──────────────────────────────────────────────────────────────────────────────
# Initialize Qwen2VL client
# ──────────────────────────────────────────────────────────────────────────────
qwen = Qwen2VLClient(
    host="http://localhost",
    port=8001,
    model="Qwen/Qwen2.5-VL-7B-Instruct",
    temperature=0.0  # deterministic
)

# ──────────────────────────────────────────────────────────────────────────────
# Prompt template for extracting skills from a page image
# ──────────────────────────────────────────────────────────────────────────────
SKILLS_PROMPT = """
You are an expert technical recruiter analyzing a resume page. You must extract EVERY technical skill mentioned ANYWHERE on this page by reading SECTION BY SECTION, LINE BY LINE from TOP TO BOTTOM.

**SYSTEMATIC EXTRACTION PROCESS:**
1. Start from the very TOP of the page
2. Read each section heading and all content within that section
3. Extract technical skills from EVERY line of text you see
4. Continue systematically until you reach the BOTTOM of the page

**SECTIONS TO EXAMINE THOROUGHLY:**
- Header/Contact Info (sometimes contains LinkedIn, GitHub, portfolio URLs)
- Summary/Objective (often mentions key technologies)
- Skills/Technical Skills (obvious location)
- Work Experience (job descriptions often mention specific tools/technologies)
- Projects (detailed technical implementations)
- Education (coursework, modules, specializations, thesis topics)
- Certifications (specific technologies certified in)
- Publications/Research (technical topics, methodologies)
- Awards/Achievements (technical competitions, hackathons)
- Languages (programming languages may be listed here)
- Any other visible section

**WHAT TO EXTRACT (be exhaustive):**
- Programming Languages: Python, Java, JavaScript, C++, R, MATLAB, etc.
- Frameworks/Libraries: React, Django, TensorFlow, PyTorch, scikit-learn, OpenCV, etc.
- AI/ML Models/Algorithms: YOLO, BERT, GPT, ResNet, CNN, RNN, SVM, Random Forest, etc.
- Cloud Platforms: AWS, Azure, GCP, specific services (S3, EC2, Lambda, etc.)
- Tools & Software: Docker, Kubernetes, Git, Jenkins, Tableau, PowerBI, etc.
- Databases: MySQL, PostgreSQL, MongoDB, Redis, Elasticsearch, etc.
- Technologies: REST API, GraphQL, microservices, blockchain, IoT, etc.
- Development Methodologies: Agile, Scrum, DevOps, CI/CD, TDD, etc.
- Academic Subjects: Data Structures, Algorithms, Machine Learning, Computer Vision, etc.
- Specific Versions: YOLOv8, GPT-4, Python 3.x, React 18, etc.
- Domain Knowledge: Computer Vision, NLP, Deep Learning, Data Science, etc.

**EXTRACTION RULES:**
1. Read EVERY word on the page - don't skip anything
2. Extract skills from job descriptions, project descriptions, course lists, thesis titles
3. Include academic modules/courses if they're technical (e.g., "Advanced Machine Learning")
4. Include research topics and methodologies mentioned
5. Extract specific model names, version numbers, and technical specifications
6. Include industry-specific tools and technologies
7. Don't skip skills just because they appear in sentences - extract them anyway

**WHAT NOT TO EXTRACT:**
- Soft skills (communication, teamwork, leadership, problem-solving)
- General business concepts (project management unless it's a specific tool like Jira)
- Languages (English, Spanish) unless they're programming languages

**CRITICAL OUTPUT REQUIREMENTS:**
1. Return EXACTLY this format: ["skill1", "skill2", "skill3"]
2. No extra text, no markdown, no explanations
3. No ``` code blocks
4. Just the pure JSON array
5. Each skill as a clean string

**EXAMPLE EXTRACTION APPROACH:**
If you see: "Coursework: Advanced Machine Learning, Computer Vision, Data Structures and Algorithms"
Extract: ["Machine Learning", "Computer Vision", "Data Structures", "Algorithms"]

If you see: "Built recommendation system using Python, TensorFlow, and deployed on AWS EC2"
Extract: ["Python", "TensorFlow", "AWS", "EC2"]

If you see: "Thesis: Object Detection using YOLOv8 and OpenCV"
Extract: ["Object Detection", "YOLOv8", "OpenCV"]

**YOUR TASK:**
Read this resume page systematically from top to bottom, section by section, line by line, and extract EVERY technical skill you see. Be thorough and exhaustive.
""".strip()


def extract_skills_from_pdf(pdf_path: str) -> list[str]:
    """
    Convert each page of pdf_path to an image, send to Qwen with SKILLS_PROMPT,
    parse the JSON array response, and return a deduplicated list of skills.
    """
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    skills = set()

    # Convert all pages to images
    pages = convert_from_path(pdf_path, dpi=150)
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, page in enumerate(pages, start=1):
            img_path = os.path.join(tmpdir, f"{base}_page_{i}.jpg")
            page.save(img_path, "JPEG")

            # Call Qwen
            try:
                reply = qwen.chat_completion(
                    question=SKILLS_PROMPT,
                    system_prompt="You are an expert at parsing resumes.",
                    image_path=img_path
                ).strip()
            except Exception as e:
                print(f"[{base} page {i}] Error calling Qwen: {e}")
                continue

            # Try to parse as JSON array
            try:
                arr = json.loads(reply)
                if isinstance(arr, list):
                    for s in arr:
                        skills.add(str(s).strip())
                else:
                    print(f"[{base} page {i}] Unexpected reply (not a list), got:", reply)
            except json.JSONDecodeError:
                # fallback: split on commas
                for part in reply.split(","):
                    skills.add(part.strip())
    return skills


def extract_full_text(pdf_path: str) -> str:
    """
    Read every page of the PDF at pdf_path and concatenate its text.
    """
    text_parts = []
    # open the PDF
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text_parts.append(page.get_text())
    return "\n".join(text_parts)

EXPERIENCE_SUMMARY_PROMPT = """
You are an expert resume parser. Analyze this resume page image and extract ALL sections in the EXACT ORDER they appear from top to bottom.

Return a JSON object with this structure:
{
  "sections": [
    {
      "section_name": "exact heading text as written",
      "entries": [
        {
          "entry_name": "specific title/role/project name or null for skill lists",
          "summary": "1-2 sentences highlighting key technical skills and achievements"
        }
      ]
    }
  ]
}

**SECTION IDENTIFICATION RULES:**
- Capture ALL major sections (Work Experience, Education, Projects, Skills, Certifications, etc.)
- Use the EXACT heading text as it appears (including variations like "Professional Experience", "Work History", "Technical Skills")
- Maintain the TOP-TO-BOTTOM order as shown in the resume
- Include sections even if they have minimal content

**ENTRY EXTRACTION RULES:**
- For job roles: "entry_name" = "Job Title at Company Name (dates if visible)"
- For projects: "entry_name" = "Project Name" or brief project description
- For education: "entry_name" = "Degree, Institution (dates if visible)"
- For skills sections: "entry_name" = null (since it's typically a list)
- For certifications: "entry_name" = "Certification Name"

**SUMMARY REQUIREMENTS:**
- Focus on technical skills, tools, technologies, and quantifiable achievements
- Mention specific programming languages, frameworks, databases, cloud platforms
- Include metrics when visible (e.g., "improved performance by 30%")
- For skills sections: group similar skills together in natural sentences
- Keep each summary to 1-2 sentences maximum
- Avoid generic phrases like "responsible for" - be specific about technologies used

**EXAMPLES:**

Work Experience Entry:
{
  "entry_name": "Software Engineer Intern at Google (Jun 2023 - Aug 2023)",
  "summary": "Developed microservices using Python, Django, and PostgreSQL, implemented CI/CD pipelines with Jenkins and Docker, resulting in 40% faster deployment cycles."
}

Project Entry:
{
  "entry_name": "E-Commerce Web Application",
  "summary": "Built full-stack application using React.js frontend, Node.js backend, MongoDB database, and integrated Stripe payment API with AWS deployment."
}

Skills Entry:
{
  "entry_name": null,
  "summary": "Programming languages include Python, Java, JavaScript, and C++. Experienced with frameworks like React, Django, and Spring Boot. Database technologies include MySQL, PostgreSQL, and MongoDB."
}

Education Entry:
{
  "entry_name": "Bachelor of Computer Science, MIT (2020-2024)",
  "summary": "Coursework focused on algorithms, data structures, machine learning, and distributed systems with hands-on projects in artificial intelligence."
}

**CRITICAL REQUIREMENTS:**
1. Return ONLY the JSON object - no markdown fences, no extra text
2. Preserve the exact visual order of sections from the resume
3. Extract ALL visible sections, not just major ones
4. Use exact heading text as written (case-sensitive)
5. Be specific about technologies and avoid vague descriptions

Analyze the resume image now and return the structured JSON:
""".strip()


def extract_summary_from_pdf(pdf_path: str) -> dict:
    """
    Convert each page of pdf_path to an image, send each image in turn to Qwen
    with EXPERIENCE_SUMMARY_PROMPT, parse each JSON object reply, and merge
    all page-level 'sections' into a single dict with key 'sections'.
    """
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    aggregated = {"sections": []}
    pages = convert_from_path(pdf_path, dpi=150)

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, page in enumerate(pages, start=1):
            img_path = os.path.join(tmpdir, f"{base}_page_{i}.jpg")
            page.save(img_path, "JPEG")

            try:
                reply = qwen.chat_completion(
                    question=EXPERIENCE_SUMMARY_PROMPT,
                    system_prompt="You are an expert at parsing resumes.",
                    image_path=img_path
                ).strip()
            except Exception as e:
                print(f"[{base} page {i}] Error calling Qwen: {e}")
                continue

            # strip any ``` fences
            if reply.startswith("```"):
                reply = "\n".join(
                    line for line in reply.splitlines()
                    if not line.strip().startswith("```")
                ).strip()

            try:
                page_obj = json.loads(reply)
            except json.JSONDecodeError:
                print(f"[{base} page {i}] Failed to parse JSON: {reply!r}")
                continue

            if not isinstance(page_obj, dict) or "sections" not in page_obj:
                print(f"[{base} page {i}] Unexpected format: {page_obj!r}")
                continue

            # Merge sections by name
            for sec in page_obj["sections"]:
                name = sec["section_name"]
                entries = sec.get("entries", [])
                # see if we already have this section
                existing = next(
                    (s for s in aggregated["sections"] if s["section_name"] == name),
                    None
                )
                if existing is None:
                    aggregated["sections"].append({
                        "section_name": name,
                        "entries": entries.copy()
                    })
                else:
                    existing["entries"].extend(entries)

    return aggregated


# def ingest_resume_normal(resumes_folder: str, candidate_key: str):
#     summary_logs: List[str] = []
#     env  = load_env_vars()
#     conn = connect_postgres(env)
#     cur  = conn.cursor()
#     ensure_resumes_normal_table(cur)
#     conn.commit()
#     pdfs = glob.glob(os.path.join(resumes_folder, "*.pdf"))
#     if not pdfs:
#         print("No PDF files found in", resumes_folder)
#         return

#     for pdf in pdfs:
#         fname = os.path.basename(pdf)
#         print("----------------------------------------------------")
#         print("Extracting skills from", os.path.basename(pdf), "…")
#         print("----------------------------------------------------")
#         skills = extract_skills_from_pdf(pdf)
#         print("----------------------------------------------------")
#         print("→", skills, "\n")
#         print("----------------------------------------------------")

#         skills_txt = ", ".join(skills)
        
        
#         print("----------------------------------------------------")
#         print("Categorizing skills into technical domains...")
#         print("----------------------------------------------------")
        
#         categories = categorize_skills(skills)
#         print("----------------------------------------------------")
#         print("→ Categories:", categories)
#         print("----------------------------------------------------")


#         print("----------------------------------------------------")
#         print("Extracting structured summary from", os.path.basename(pdf), "…")
#         print("----------------------------------------------------")
#         structured_summary = extract_summary_from_pdf(pdf)
#         skills_summary_txt = json.dumps(structured_summary, ensure_ascii=False)
#         print("----------------------------------------------------")
#         print("→ Structured summary extracted")
#         print("----------------------------------------------------")


#         print("----------------------------------------------------")
#         print("Extracting full text…")
#         print("----------------------------------------------------")
#         full_text = extract_full_text(pdf)
#         print("----------------------------------------------------")
#         print(f"Full text length: {len(full_text)} characters\n")
#         print("----------------------------------------------------")

#         upsert_resumes_normal(
#             cur,
#             filename        = fname,
#             candidate_key   = candidate_key,
#             skills_txt      = skills_txt,
#             skills_categories=categories,
#             full_resume_txt = full_text,
#             skills_summary_txt = skills_summary_txt
#         )
#         conn.commit()
#         print("----------------------------------------------------")
#         print(f"  ✓ Inserted/Updated {fname} in resumes_normal")
#         print("----------------------------------------------------")


#         summary_logs.append(f"  ✓ Done with {fname}.")

#     cur.close()
#     conn.close()

#     return summary_logs


def extract_summary_paragraph(skills_summary_txt: str) -> str:
    """
    Extract all summary fields from the structured JSON and combine into a single paragraph.
    """
    if not skills_summary_txt:
        return ""
    
    try:
        summary_data = json.loads(skills_summary_txt)
        
        if not isinstance(summary_data, dict) or "sections" not in summary_data:
            return ""
        
        summary_parts = []
        
        for section in summary_data.get("sections", []):
            section_name = section.get("section_name", "")
            entries = section.get("entries", [])
            
            for entry in entries:
                summary = entry.get("summary", "").strip()
                if summary:
                    summary_parts.append(summary)
        
        # Combine all summaries into one paragraph
        combined_paragraph = " ".join(summary_parts)
        return combined_paragraph
        
    except json.JSONDecodeError as e:
        print(f"Error parsing summary JSON: {e}")
        return ""
    
# PREDEFINED_CATEGORIES = [
#     "Game Development",
#     "Web Development", 
#     "NLP",
#     "LLM",
#     "Computer Vision",
#     "3D modeling",
#     "Product Manager",
#     "Mobile development",
#     "Data Science",
#     "Machine Learning"
# ]

# # Define keywords for each category
# CATEGORY_KEYWORDS = {
#     "Game Development": [
#         "game", "unity", "unreal", "graphics programming", "game design", "game engine",
#         "opengl", "directx", "shader", "rendering", "physics engine"
#     ],
#     "Web Development": [
#         "react", "vue", "angular", "django", "flask", "node.js", "nodejs", "express",
#         "html", "css", "javascript", "typescript", "php", "laravel", "spring boot",
#         "frontend", "backend", "full-stack", "web development", "rest api", "graphql", "java"
#     ],
#     "NLP": [
#         "nlp", "natural language processing", "spacy", "nltk", "text analysis", 
#         "text mining", "sentiment analysis", "named entity recognition", "tokenization"
#     ],
#     "LLM": [
#         "llm", "llms", "large language model", "gpt", "bert", "transformer", "transformers",
#         "chatgpt", "langchain", "rag", "fine-tuning", "prompt engineering", "openai"
#     ],
#     "Computer Vision": [
#         "computer vision", "opencv", "yolo", "image processing", "object detection",
#         "image classification", "cnn", "convolutional neural network", "diffusion model",
#         "image recognition", "facial recognition"
#     ],
#     "3D modeling": [
#         "3d modeling", "3d graphics", "blender", "maya", "3ds max", "cad", "autocad",
#         "three.js", "threejs", "webgl", "modeling", "animation", "rendering"
#     ],
#     "Product Manager": [
#         "product manager", "product management", "business analysis", "strategy",
#         "requirements gathering", "roadmap", "stakeholder", "agile", "scrum master"
#     ],
#     "Mobile development": [
#         "ios", "android", "react native", "flutter", "swift", "kotlin", "java",
#         "mobile app", "mobile development", "app store", "play store", "xamarin"
#     ],
#     "Data Science": [
#         "data science", "data analysis", "pandas", "numpy", "matplotlib", "seaborn",
#         "data visualization", "statistics", "analytics", "business analytics",
#         "predictive analytics", "a/b testing", "ab testing", "a-b testing", "tableau", "power bi"
#     ],
#     "Machine Learning": [
#         "machine learning", "ml", "scikit-learn", "sklearn", "tensorflow", "pytorch",
#         "keras", "neural network", "deep learning", "supervised learning",
#         "unsupervised learning", "classification", "regression", "clustering",
#         # Add common algorithm names
#         "kmeans", "k-means", "svm", "support vector machine", "random forest",
#         "decision tree", "linear regression", "logistic regression", "naive bayes",
#         "gradient boosting", "xgboost", "lightgbm", "ensemble methods"
#     ]
# }

# def categorize_from_full_paragraph_regex(full_txt: str) -> List[str]:
#     """
#     Extract summary paragraph and categorize using regex keyword matching with context validation.
#     """
#     if not full_txt:
#         return []
    
    
#     # Convert to lowercase for case-insensitive matching
#     full_lower = full_txt.lower()
    
#     # Find matching categories with context validation
#     matched_categories = []
    
#     for category, keywords in CATEGORY_KEYWORDS.items():
#         category_matched = False
#         category_details = []
        
#         for keyword in keywords:
#             pattern = re.escape(keyword.lower())
#             matches = list(re.finditer(pattern, full_lower))
            
#             if matches:
#                 print(f"🔍 Found {len(matches)} occurrence(s) of '{keyword}' for {category}")
                
#                 if keyword.lower() in ["game", "modeling", "ml"]:  # Ambiguous keywords
#                     valid_count = 0
                    
#                     # Check each occurrence
#                     for i, match in enumerate(matches, 1):
#                         print(f"   📍 Validating occurrence {i}/{len(matches)}")
#                         if validate_keyword_context(full_lower, match, keyword, category):
#                             valid_count += 1
                    
#                     if valid_count > 0:
#                         category_details.append(f"{keyword}({valid_count}/{len(matches)} valid)")
#                         category_matched = True
#                         print(f"   ✅ {keyword}: {valid_count}/{len(matches)} occurrences are valid")
#                     else:
#                         print(f"   ❌ {keyword}: 0/{len(matches)} occurrences are valid")
                        
#                 else:  # Non-ambiguous keywords
#                     category_details.append(f"{keyword}({len(matches)})")
#                     category_matched = True
#                     print(f"   ✅ {keyword}: accepted all {len(matches)} occurrence(s)")
        
#         if category_matched:
#             matched_categories.append(category)
#             print(f"✅ {category}: {category_details}")
    
#     if not matched_categories:
#         print("❌ No categories matched")
    
#     print(f"🏷️  FINAL CATEGORIES: {matched_categories}")
#     return matched_categories

# def validate_keyword_context(text: str, match, keyword: str, category: str) -> bool:
#     """
#     Use Qwen to validate if a keyword in context actually belongs to the category.
#     """
#     start = match.start()
#     end = match.end()
    
#     # PRE-FILTERING: Check for obvious false positives before calling LLM
#     if keyword.lower() == "ml" and category == "Machine Learning":
#         # Check if ML is part of a larger word
#         full_word_start = start
#         full_word_end = end
        
#         # Extend backwards to find start of word
#         while full_word_start > 0 and text[full_word_start - 1].isalpha():
#             full_word_start -= 1
        
#         # Extend forwards to find end of word
#         while full_word_end < len(text) and text[full_word_end].isalpha():
#             full_word_end += 1
        
#         full_word = text[full_word_start:full_word_end].lower()
        
#         # Known false positives for ML
#         markup_languages = ["html", "xml", "yaml", "sgml", "toml", "haml", "xaml"]
#         if full_word in markup_languages:
#             print(f"   🛡️ Pre-filter: '{keyword}' in '{full_word}' is markup language -> INVALID")
#             return False
    
#     # Extract context around the matched keyword (50 chars before and after)
#     context_start = max(0, start - 50)
#     context_end = min(len(text), end + 50)
#     context = text[context_start:context_end]
    
#     # Highlight the matched keyword in the context
#     highlighted_context = (
#         context[:start-context_start] + 
#         f"**{keyword.upper()}**" + 
#         context[end-context_start:]
#     )
    
#     validation_prompt = f"""
#         You are an expert at understanding technical contexts. I need to determine if a keyword belongs to a specific technical category.

#         KEYWORD: "{keyword}"
#         CATEGORY: "{category}"
#         CONTEXT: "{highlighted_context}"

#         CRITICAL RULES - THESE MUST BE FOLLOWED EXACTLY:
#         1. If you see "game theory" - this is mathematics, NOT Game Development
#         2. If you see "modeling" in non-3D contexts (data modeling, financial modeling) - NOT 3D modeling
#         3. Look at the EXACT surrounding words to determine the true meaning

#         EXAMPLES:
#         ❌ "**game** theory" → NOT Game Development (it's mathematics)
#         ❌ "data **modeling**" → NOT 3D modeling (it's data science)
#         ❌ "financial **modeling**" → NOT 3D modeling (it's finance)
#         ✅ "**game** engine" → IS Game Development
#         ✅ "3D **modeling** in Blender" → IS 3D modeling
#         ✅ "**modeling** characters for animation" → IS 3D modeling

#         QUESTION: Does **{keyword.upper()}** in this context refer to {category}?

#         Answer ONLY: YES or NO
#         """

#     try:
#         reply = qwen.chat_completion(
#             question=validation_prompt,
#             system_prompt="You are an expert at technical categorization. Follow the rules exactly. Answer only YES or NO."
#         ).strip().upper()
        
#         is_valid = reply.startswith("YES")
#         print(f"   Context validation for '{keyword}' in '{category}': {reply} -> {'VALID' if is_valid else 'INVALID'}")
        
#         return is_valid
        
#     except Exception as e:
#         print(f"   Context validation failed for '{keyword}': {e}")
        
#         # Enhanced fallback logic
#         if keyword.lower() == "ml":
#             context_lower = context.lower()
#             if any(word in context_lower for word in ["html", "xml", "yaml", "sgml"]):
#                 print(f"   🛡️ Fallback: Detected ML in markup language context, returning False")
#                 return False
        
#         if keyword.lower() == "game" and "theory" in context.lower():
#             print(f"   🛡️ Fallback: Detected 'game theory', returning False")
#             return False
            
#         if keyword.lower() == "modeling":
#             context_lower = context.lower()
#             non_3d_contexts = ["data modeling", "financial modeling", "business modeling", "mathematical modeling"]
#             if any(phrase in context_lower for phrase in non_3d_contexts):
#                 print(f"   🛡️ Fallback: Detected non-3D modeling context, returning False")
#                 return False
            
#         return True

def safe_parse_json(reply: str) -> dict:
    """
    Extract the first {...} block from reply and parse it as JSON.
    Raises ValueError if no JSON object is found or it fails to parse.
    """
    # Remove Markdown fences if present
    reply = re.sub(r"^```+json\s*|\s*```+$", "", reply.strip(), flags=re.IGNORECASE)
    # Find the first {...} block
    m = re.search(r'(\{.*\})', reply, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in LLM reply")
    payload = m.group(1)
    return json.loads(payload)

def load_categories(conn) -> list[dict]:
    """
    Fetch all skill categories from the DB.
    Returns a list of dicts: [{'id': 1, 'name': 'Web Development'}, ...]
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name FROM skill_category;")
        return cur.fetchall()
    

# def classify_skills_by_category(
#     qwen_client,
#     resume_text: str,
#     categories: list[dict],
#     top_k: int = 5
# ) -> list[dict]:
#     """
#     For each category, ask Qwen to find all distinct mentions of tools/tech/languages
#     that belong in that domain (even if the category name itself isn’t present).
#     Return list of {"id","name","mentions","score"} sorted by score desc.
#     """
#     results = []
#     for cat in categories:
#         prompt = f"""
# You are an expert technical recruiter.  Your job is to identify and count *all* 
# skills, tools, frameworks and languages that belong to the “{cat['name']}” domain 
# —even if the exact phrase “{cat['name']}” never appears.  For example, for Web Development 
# you might count JavaScript, HTML, CSS, React, Node.js, Django, etc.

# Return *only* valid JSON in this exact format:

# {{
#   "mentions": ["skill1", "skill2", …],
#   "score": <number of distinct mentions>
# }}

# Now analyze this resume text:
# \"\"\"
# {resume_text}
# \"\"\"
# """
#         reply = qwen_client.chat_completion(
#             question=prompt.strip(),
#             system_prompt="You are an expert technical recruiter. Return only valid JSON."
#         ).strip()

#         # data = json.loads(reply)
#         # # attach our own category metadata
#         # data["id"]   = cat["id"]
#         # data["name"] = cat["name"]
#         # results.append(data)

#     # pick top_k categories by score
#     # return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]
#         # parse JSON safely
#         try:
#             payload = json.loads(reply)
#             mentions = payload.get("mentions", [])
#             score    = int(payload.get("score", 0))
#         except (json.JSONDecodeError, ValueError):
#             print(f"⚠️ Failed to parse JSON for category {cat['name']!r}, reply was: {reply!r}")
#             mentions = []
#             score    = 0

#         results.append({
#             "id":       cat["id"],
#             "name":     cat["name"],
#             "mentions": mentions,
#             "score":    score,
#         })
#      # always return a list (even if all zero)
#     return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]


def classify_skills_by_category(
    qwen_client,
    resume_text: str,
    categories: list[dict],
    top_k: int = 5
) -> list[dict]:
    """
    For each category, ask Qwen to identify all skills belonging to that domain.
    Use safe_parse_json() to robustly extract the JSON payload.
    Returns top_k categories sorted by score desc.
    """
    results = []
    for cat in categories:
        prompt = f"""
You are an expert technical recruiter.  Return ONLY valid JSON—no markdown fences or extra text.

Respond in this exact format:
{{
  "mentions": ["skill1", "skill2", …],
  "score": <number of distinct mentions>
}}

Now analyze this resume text for the domain “{cat['name']}”:
\"\"\"
{resume_text}
\"\"\"
"""
        reply = qwen_client.chat_completion(
            question=prompt.strip(),
            system_prompt="You are an expert recruiter. Return only raw JSON."
        ).strip()

        try:
            payload = safe_parse_json(reply)
            mentions = payload.get("mentions", [])
            score    = int(payload.get("score", 0))
        except Exception as e:
            print(f"⚠️ Failed to parse JSON for category '{cat['name']}', error: {e}\nRaw reply was: {reply!r}")
            mentions = []
            score    = 0

        results.append({
            "id":       cat["id"],
            "name":     cat["name"],
            "mentions": mentions,
            "score":    score,
        })

    # return only the top_k by score
    return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]




def upsert_category_scores(cur, candidate_key: str, filename: str, classified: list[dict]):
    """
    Upsert each (candidate_key,filename,category_id) → score + mentions.
    """
    for entry in classified:
        cur.execute("""
            INSERT INTO resume_category_score
              (candidate_key, filename, category_id, score, mentions)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (candidate_key,filename,category_id) DO UPDATE
              SET score    = EXCLUDED.score,
                  mentions = EXCLUDED.mentions;
        """, (
            candidate_key,
            filename,
            entry["id"],
            entry["score"],
            json.dumps(entry["mentions"])
        ))

    
def ingest_resume_normal(resumes_folder: str, candidate_key: str):
    summary_logs: List[str] = []
    env  = load_env_vars()
    conn = connect_postgres(env)
    cur  = conn.cursor()
    ensure_resumes_normal_table(cur)
    conn.commit()
    pdfs = glob.glob(os.path.join(resumes_folder, "*.pdf"))
    if not pdfs:
        print("No PDF files found in", resumes_folder)
        return

    for pdf in pdfs:
        fname = os.path.basename(pdf)

        print("----------------------------------------------------")
        print("Extracting structured summary from", os.path.basename(pdf), "…")
        print("----------------------------------------------------")
        structured_summary = extract_summary_from_pdf(pdf)
        skills_summary_txt = json.dumps(structured_summary, ensure_ascii=False)
        print("----------------------------------------------------")
        print(f"→ Structured summary extracted")
        print("----------------------------------------------------")

        print("----------------------------------------------------")
        print("Extracting full text…")
        print("----------------------------------------------------")
        full_text = extract_full_text(pdf)
        print("----------------------------------------------------")
        print(f"Full text length: {len(full_text)} characters\n")
        print("----------------------------------------------------")



        # print("----------------------------------------------------")
        # print("Categorizing skills into technical domains...")
        # print("----------------------------------------------------")
        # categories = categorize_from_full_paragraph_regex(full_text)
        # print("----------------------------------------------------")
        # print("→ Categories:", categories)
        # print("----------------------------------------------------")

        # upsert_resumes_normal(
        #     cur,
        #     filename        = fname,
        #     candidate_key   = candidate_key,
        #     skills_categories=categories,
        #     full_resume_txt = full_text,
        #     skills_summary_txt = skills_summary_txt
        # )
        # ─── Dynamic Qwen-based categorization ────────────────────────────
        print("Loading skill categories from database…")
        db_categories = load_categories(conn)

        print("Classifying skills via Qwen for each category…")
        # classified = classify_skills_by_category(qwen, full_text, db_categories, top_k=5)
        # ask for as many as there are categories → you’ll get all of them
        classified   = classify_skills_by_category(
            qwen,
            full_text,
            db_categories,
            top_k=len(db_categories),
        )
        

        # 1) Persist detailed scores & mentions
        upsert_category_scores(cur, candidate_key, fname, classified)

        # 2) Extract all category NAMES for your summary table
        top_names = [c["name"] for c in classified]
        print("→ Categories in Descending order by score:", top_names)

        upsert_resumes_normal(
            cur,
            filename             = fname,
            candidate_key        = candidate_key,
            skills_categories    = top_names,
            full_resume_txt      = full_text,
            skills_summary_txt   = skills_summary_txt
        )
        # ─────────────────────────────────────────────────────────────────

        conn.commit()
        print("----------------------------------------------------")
        print(f"  ✓ Inserted/Updated {fname} in resumes_normal")
        print("----------------------------------------------------")


        summary_logs.append(f"  ✓ Done with {fname}.")

    cur.close()
    conn.close()

    return summary_logs

# if __name__ == "__main__":
#     resumes_folder = "/home/peseyes/Desktop/resumeRAG/resume_analyzer/resumes/resumes_normal"
#     summary = ingest_resume_normal(resumes_folder)
#     print("Ingestion complete.")
