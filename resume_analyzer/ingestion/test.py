import os
import json
import tempfile
import sys
import glob
import psycopg2
import subprocess
from typing import Dict, Optional, List, Callable
from dateutil import parser
import fitz
import json
from pdf2image import convert_from_path    # pip install pdf2image
from dotenv import load_dotenv

from ..backend.model import Qwen2VLClient    
from .helpers import (
    connect_postgres,
    embed_sentences,
    ensure_resumes_normal_table,
    upsert_resumes_normal,
)
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# Load environment variables from .env file
load_dotenv()

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

# SKILLS_PROMPT = """
# You are an expert recruiter. You will be shown an image of one page of a resume.
# 1. First, scan for any explicit “Skills” section or skills related bullet list.
# 2. Then, read through the experience/work related section and **extract any technical or domain skills** mentioned there (e.g. languages, tools, frameworks, methodologies) even if they’re embedded in sentences.
# 3. Return a JSON array of unique skill names, e.g.:

# ["Python", "SQL", "Docker", "Machine Learning", "AWS", "REST APIs"]

# **Rules:**
# - Do not return soft skills (e.g. “teamwork”, “communication”).
# - Do not include any extra text or numbering—just the JSON array.

# **Do NOT** include any ```json``` blocks, code fences, or other formatting—just the bracketed array.
# """.strip()

# def extract_skills_from_pdf(pdf_path: str) -> list[str]:
#     """
#     Convert each page of pdf_path to an image, send to Qwen with SKILLS_PROMPT,
#     parse the JSON array response, and return a deduplicated list of skills.
#     """
#     base = os.path.splitext(os.path.basename(pdf_path))[0]
#     skills = set()

#     # Convert all pages to images
#     pages = convert_from_path(pdf_path, dpi=150)
#     with tempfile.TemporaryDirectory() as tmpdir:
#         for i, page in enumerate(pages, start=1):
#             img_path = os.path.join(tmpdir, f"{base}_page_{i}.jpg")
#             page.save(img_path, "JPEG")

#             # Call Qwen
#             try:
#                 reply = qwen.chat_completion(
#                     question=SKILLS_PROMPT,
#                     system_prompt="You are an expert at parsing resumes.",
#                     image_path=img_path
#                 ).strip()
#             except Exception as e:
#                 print(f"[{base} page {i}] Error calling Qwen: {e}")
#                 continue

#             # Try to parse as JSON array
#             try:
#                 arr = json.loads(reply)
#                 if isinstance(arr, list):
#                     for s in arr:
#                         skills.add(str(s).strip())
#                 else:
#                     print(f"[{base} page {i}] Unexpected reply (not a list), got:", reply)
#             except json.JSONDecodeError:
#                 # fallback: split on commas
#                 for part in reply.split(","):
#                     skills.add(part.strip())
#     return sorted(skills)
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

def test(resumes_folder: str):
    pdfs = glob.glob(os.path.join(resumes_folder, "*.pdf"))
    if not pdfs:
        print("No PDF files found in", resumes_folder)
        return

    for pdf in pdfs:
        name = os.path.basename(pdf)
        print("=" * 60)
        print(f"Extracting summary from {name}")
        print("=" * 60)

        # <-- use the new summary extractor, not the skills-only one
        summary = extract_summary_from_pdf(pdf)

        print("\nJSON output:")
        print(json.dumps(summary, indent=2, ensure_ascii=False))

# def test_cosine_similarity():
#     """Test cosine similarity between two terms"""
    
#     # Terms to compare
#     term1 = "YOLO"
#     term2 = "YOLOv11"
    
#     print("----------------------------------------------------")
#     print(f"Testing cosine similarity between:")
#     print(f"Term 1: '{term1}'")
#     print(f"Term 2: '{term2}'")
#     print("----------------------------------------------------")
    
#     try:
#         # Get embeddings for both terms
#         embeddings = embed_sentences([term1, term2])
        
#         print(f"Got embeddings with dimension: {len(embeddings[0])}")
        
#         # Convert to numpy arrays
#         embedding1 = np.array(embeddings[0]).reshape(1, -1)
#         embedding2 = np.array(embeddings[1]).reshape(1, -1)
        
#         # Calculate cosine similarity
#         similarity = cosine_similarity(embedding1, embedding2)[0][0]
        
#         print("----------------------------------------------------")
#         print(f"Cosine Similarity: {similarity:.4f}")
#         print("----------------------------------------------------")
        
#         # Interpretation
#         if similarity > 0.8:
#             print("🟢 Very High Similarity")
#         elif similarity > 0.6:
#             print("🟡 High Similarity") 
#         elif similarity > 0.4:
#             print("🟠 Moderate Similarity")
#         elif similarity > 0.2:
#             print("🔴 Low Similarity")
#         else:
#             print("⚫ Very Low Similarity")
            
#         return similarity
        
#     except Exception as e:
#         print(f"Error calculating similarity: {e}")
#         return None


if __name__ == "__main__":
    test("/home/peseyes/Desktop/resumeRAG/resume_analyzer/resumes/test")
    # print("\n" + "="*60)
    # print("EMBEDDING SIMILARITY TEST")
    # print("="*60)
    
    # # Test cosine similarity
    # test_cosine_similarity()