import os
import json
import tempfile
import psycopg2
import requests
import subprocess
from typing import Dict, Optional, List, Callable, Union
from dateutil import parser
import re
from dotenv import load_dotenv
import torch
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import pickle
from pathlib import Path

from pdf2image import convert_from_path

from ..backend.model import Qwen2VLClient  

# ──────────────────────────────────────────────────────────────────────────────
# Load settings
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
EMBED_HOST = os.getenv("EMBED_HOST", "http://127.0.0.1")
EMBED_PORT = os.getenv("EMBED_PORT", "5006")
EMBED_URL  = f"{EMBED_HOST}:{EMBED_PORT}/embed"

# ──────────────────────────────────────────────────────────────────────────────
# Initialize device and model once
# ──────────────────────────────────────────────────────────────────────────────
# _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
# _embed_model = SentenceTransformer(
#     EMBEDDING_MODEL,
#     trust_remote_code=True
# ).to(_device)

CANONICAL_UNIS = [
    "National University of Singapore",
    "Nanyang Technological University",
    "Singapore Management University",
    "Singapore University of Technology and Design",
    "Singapore Institute of Technology",
    "Singapore University of Social Sciences",
    "Singapore Institute of Management",
    "Singapore Polytechnic",
    "Ngee Ann Polytechnic",
    "Temasek Polytechnic",
    "Republic Polytechnic",
    "Nanyang Polytechnic",
    "PSB Academy",
    "LASALLE College of the Arts",
    "Nanyang Academy of Fine Arts",
    "James Cook University Singapore",
    "Kaplan Singapore",
    "Curtin University Singapore",
    # … add more schools here …
]

FAISS_INDEX_PATH = "./resume_faiss_index.bin"
FAISS_METADATA_PATH = "./resume_faiss_metadata.pkl"
CHUNK_SIZE = 512  # Characters per chunk
CHUNK_OVERLAP = 50  # Overlap between chunks

def embed_sentences(sentences: List[str]) -> List[List[float]]:
    """
    Given a list of strings, call the /embed HTTP endpoint and return the embeddings.
    """
    payload = {"sentences": sentences}
    resp = requests.post(EMBED_URL, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["embeddings"]

def connect_postgres(env: Dict[str,str]):
    """Return a psycopg2 connection using the PG_... environment."""
    return psycopg2.connect(
        dbname   = env["PG_DB"],
        user     = env["PG_USER"],
        password = env["PG_PASSWORD"],
        host     = env["PG_HOST"],
        port     = env["PG_PORT"]
    )

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

# def ensure_resumes_table(cur) -> None:
#     """
#     Creates the `resumes_metadata` table if it does not exist,
#     adding a candidate_key to link to the normal resume.
#     """
#     cur.execute(
#         """
#         CREATE TABLE IF NOT EXISTS public.resumes_metadata (
#             filename               TEXT           NOT NULL PRIMARY KEY,
#             candidate_key          TEXT           NOT NULL,
#             work_duration_category TEXT,
#             university             TEXT,
#             applied_position       TEXT,
#             salary                 TEXT,
#             part_or_full           TEXT,
#             is_credit_bearing      TEXT,
#             citizenship            TEXT,
#             from_date              TEXT,
#             to_date                TEXT
#         );
#         """
#     )


def ensure_resumes_table(cur):
    """
    Ensure the resumes_metadata table exists with all required columns including email.
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS public.resumes_metadata (
            filename               TEXT PRIMARY KEY,
            candidate_key          TEXT NOT NULL,
            email                  TEXT NOT NULL,  -- Make sure this is here
            work_duration_category TEXT,
            university             TEXT,
            applied_position       TEXT,
            salary                 TEXT,
            part_or_full           TEXT,
            is_credit_bearing      TEXT,
            citizenship            TEXT,
            from_date              TEXT,
            to_date                TEXT
        );
    """)


# def upsert_resume_metadata(
#     cur,
#     filename: str,
#     candidate_key: str,
#     fields: Dict[str, Optional[str]]
# ) -> None:
#     """
#     Inserts or updates a row in resumes_metadata, now with candidate_key.
#     """
#     cur.execute(
#         """
#         INSERT INTO public.resumes_metadata
#             (filename, candidate_key,
#              work_duration_category, university, applied_position,
#              salary, part_or_full, is_credit_bearing, citizenship,
#              from_date, to_date)
#         VALUES (
#             %s, %s,
#             %s, %s, %s,
#             %s, %s, %s, %s,
#             %s, %s
#         )
#         ON CONFLICT (filename) DO UPDATE
#           SET candidate_key          = EXCLUDED.candidate_key,
#               work_duration_category = EXCLUDED.work_duration_category,
#               university             = EXCLUDED.university,
#               applied_position       = EXCLUDED.applied_position,
#               salary                 = EXCLUDED.salary,
#               part_or_full           = EXCLUDED.part_or_full,
#               is_credit_bearing      = EXCLUDED.is_credit_bearing,
#               citizenship            = EXCLUDED.citizenship,
#               from_date              = EXCLUDED.from_date,
#               to_date                = EXCLUDED.to_date;
#         """,
#         [
#             filename,
#             candidate_key,
#             fields.get("work_duration_category"),
#             fields.get("university"),
#             fields.get("applied_position"),
#             fields.get("salary"),
#             fields.get("part_or_full"),
#             fields.get("is_credit_bearing"),
#             fields.get("citizenship"),
#             fields.get("from_date"),
#             fields.get("to_date"),
#         ]
#     )

def upsert_resume_metadata(
    cur,
    filename: str,
    candidate_key: str,
    fields: Dict[str, Optional[str]]
) -> None:
    """
    Inserts or updates a row in resumes_metadata, now with candidate_key and email.
    """
    cur.execute(
        """
        INSERT INTO public.resumes_metadata
            (filename, candidate_key, email,
             work_duration_category, university, applied_position,
             salary, part_or_full, is_credit_bearing, citizenship,
             from_date, to_date)
        VALUES (
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s
        )
        ON CONFLICT (filename) DO UPDATE
          SET candidate_key          = EXCLUDED.candidate_key,
              email                  = EXCLUDED.email,
              work_duration_category = EXCLUDED.work_duration_category,
              university             = EXCLUDED.university,
              applied_position       = EXCLUDED.applied_position,
              salary                 = EXCLUDED.salary,
              part_or_full           = EXCLUDED.part_or_full,
              is_credit_bearing      = EXCLUDED.is_credit_bearing,
              citizenship            = EXCLUDED.citizenship,
              from_date              = EXCLUDED.from_date,
              to_date                = EXCLUDED.to_date;
        """,
        [
            filename,
            candidate_key,
            fields.get("email"),  # ADD THIS LINE
            fields.get("work_duration_category"),
            fields.get("university"),
            fields.get("applied_position"),
            fields.get("salary"),
            fields.get("part_or_full"),
            fields.get("is_credit_bearing"),
            fields.get("citizenship"),
            fields.get("from_date"),
            fields.get("to_date"),
        ]
    )

def ensure_resumes_normal_table(cur):
    """
    Creates the `resumes_normal` table if it does not exist,
    adding candidate_key to link back to metadata.
    """
    cur.execute("""
    CREATE TABLE IF NOT EXISTS public.resumes_normal (
        filename        TEXT     PRIMARY KEY,
        candidate_key   TEXT     NOT NULL,
        skills_categories TEXT[],
        full_resume_txt TEXT,
        skills_summary_txt TEXT
    );
    """)

def upsert_resumes_normal(
    cur,
    filename: str,
    candidate_key: str,
    skills_categories: List[str],
    full_resume_txt: str,
    skills_summary_txt: str = None
):
    """
    Inserts or updates a row in resumes_normal, now with candidate_key.
    """
    cur.execute("""
    INSERT INTO public.resumes_normal
      (filename, candidate_key, skills_categories, full_resume_txt, skills_summary_txt)
    VALUES (
      %s, %s, %s, %s, %s
    )
    ON CONFLICT (filename) DO UPDATE
      SET candidate_key   = EXCLUDED.candidate_key,
          skills_categories = EXCLUDED.skills_categories,
          full_resume_txt = EXCLUDED.full_resume_txt,
          skills_summary_txt = EXCLUDED.skills_summary_txt
    """, [
        filename,
        candidate_key,
        skills_categories,
        full_resume_txt,
        skills_summary_txt,
    ])

def convert_docx_to_pdf_via_libreoffice(docx_path: str, pdf_path: str) -> None:
    """
    Use LibreOffice in headless mode to convert a .docx to a .pdf.
    This works on Linux if LibreOffice is installed.
    """
    # LibreOffice outputs to the same directory as the docx unless you specify --outdir,
    # so we explicitly set --outdir to the target directory.
    outdir = os.path.dirname(pdf_path)
    try:
        subprocess.run([
            "libreoffice",
            "--headless",
            "--convert-to", "pdf",
            docx_path,
            "--outdir", outdir
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"LibreOffice conversion failed: {e.stderr.decode().strip()}")
    
def compute_months_between(from_date_str: str, to_date_str: str) -> Optional[Dict[str, float]]:
    """
    Parse two date strings, compute the difference in days, and approximate months
    by dividing the days by 30.

    Args:
        from_date_str: e.g. "June 2025" or "June"
        to_date_str:   e.g. "Aug 2026" or "August 2026"

    Returns:
        A dict { "days": <int>, "months": <float> }, or None if parsing fails.
    """
    try:
        d1 = parser.parse(from_date_str)
        d2 = parser.parse(to_date_str)
    except Exception:
        return None

    delta_days = (d2 - d1).days
    total_months = delta_days / 30.0

    if total_months < 2:
        # Anything less than 2 months: we could choose to bucket as "2-4" or None
        # but by your spec you only assign if >=2. We'll return None.
        return "0-2 MONTHS"
    elif 2 <= total_months <= 4:
        return "2-4 MONTHS"
    elif 5 <= total_months <= 7:
        return "5-7 MONTHS"
    else:
        return "MORE THAN 7 MONTHS"
    
def normalize_university(client: Qwen2VLClient, university: str) -> str:
    """
    Given a raw university string, ask Qwen to return the canonical full name.
    If Qwen cannot normalize, return the raw string unchanged (or None if raw is None/empty).
    """
    if not university or not university.strip():
        return university

    # Build a comma‐separated list of the canonical names for the prompt:
    canon_list = ", ".join(f'"{u}"' for u in CANONICAL_UNIS)

    prompt = f"""
        You are given a raw university name from a resume. We have the following list of canonical university names:
        {canon_list}

        Return exactly one of these canonical names if the raw string clearly refers to it
        (e.g. abbreviations, school codes, or extra details should be normalized to the full canonical name). 
        If you do NOT recognize it as one of the above, return the raw string unchanged.

        Examples of proper normalization:
        • "NTU ADM" → "Nanyang Technological University"
        • "NUS Comp Sci" → "National University of Singapore"
        • "SMU Lee Kong Chian" → "Singapore Management University"
        • "SUTD Engineering" → "Singapore University of Technology and Design"
        • "SIT Applied Learning" → "Singapore Institute of Technology"
        • "NTU School of Art" → "Nanyang Technological University"
        • "NUS Faculty of Engineering" → "National University of Singapore"
        • "Singapore Poly" → "Singapore Polytechnic"
        • "Ngee Ann Poly" → "Ngee Ann Polytechnic"
        • "RP Business" → "Republic Polytechnic"
        • "Harvard University" → "Harvard University" (unchanged - not in our list)

        Raw input:
        "{university.strip()}"

        Expected output format (return only the university name):
        "National University of Singapore"
        """.strip()
    
    try:
        reply = client.chat_completion(
            question=prompt,
            system_prompt="You are an expert in classifying singapore universities."
        ).strip()

        print("----------------------------------------------------")
        print(f"[normalize_university] Raw reply from Qwen:\n{reply}")
        print("----------------------------------------------------")
        # Take only the first non‐empty line:
        first_line = reply.splitlines()[0].strip()

        # If it’s wrapped in double‐quotes, remove them:
        if first_line.startswith('"') and first_line.endswith('"'):
            first_line = first_line[1:-1]

        return first_line or university
    except Exception as e:
        print("Error normalizing university:", e)
        return university

def normalize_partfull_time(client: Qwen2VLClient, partfull_str: Optional[str]) -> Optional[str]:
    """
    Given a raw part/full‐time string from a resume, return exactly "FULLTIME" or "PARTTIME".
    If the raw string clearly refers to one of these (e.g. "full", "FT", "part", "PT"), normalize it.
    Otherwise, ask Qwen2VLClient to choose between "FULLTIME" or "PARTTIME". 
    If input is None or empty, return it unchanged.
    """
    if not partfull_str or not partfull_str.strip():
        return partfull_str

    # List of the two canonical options:
    canon_list = '"FULLTIME", "PARTTIME"'

    prompt = f"""
        You are given a raw part/full‐time designation from a resume.
        We want to normalize it to exactly one of:
        {canon_list}

        Examples of valid mappings:
        • "full"       → "FULLTIME"
        • "Fulltime"   → "FULLTIME"
        • "FT"         → "FULLTIME"
        • "part"       → "PARTTIME"
        • "PartTime"   → "PARTTIME"
        • "PT"         → "PARTTIME"

        If the raw input clearly refers to one of these two categories, return exactly "FULLTIME" or "PARTTIME".
        If it does not match either, return the raw string unchanged.

        Raw input:
        "{partfull_str.strip()}"

        Example output:
        "FULLTIME"
    """.strip()

    try:
        reply = client.chat_completion(
            question=prompt,
            system_prompt="You are an assistant that normalizes part/full‐time labels to FULLTIME or PARTTIME."
        ).strip()

        # Grab the first non‐empty line of the model's reply:
        first_line = next((line for line in reply.splitlines() if line.strip()), "").strip()

        # Remove any surrounding quotes:
        if first_line.startswith('"') and first_line.endswith('"'):
            first_line = first_line[1:-1]

        # Uppercase to ensure exact match
        normalized = first_line.upper()

        if normalized in {"FULLTIME", "PARTTIME"}:
            return normalized
        else:
            # Fallback: simple heuristics if model went off‐script
            lower = partfull_str.lower()
            if "full" in lower or lower.strip() in {"ft"}:
                return "FULLTIME"
            if "part" in lower or lower.strip() in {"pt"}:
                return "PARTTIME"
            return partfull_str

    except Exception as e:
        # On any error, fall back to heuristics
        lower = partfull_str.lower()
        if "full" in lower or lower.strip() in {"ft"}:
            return "FULLTIME"
        if "part" in lower or lower.strip() in {"pt"}:
            return "PARTTIME"
        return partfull_str

def normalize_salary(client: Qwen2VLClient, raw_salary: Optional[str]) -> Union[str, None]:
    """
    Use Qwen to extract only the numeric portion of a raw salary string.
    If raw_salary is “NIL”/“null” (case-insensitive) or empty, return "any".
    Otherwise, return a string containing just the digits (no symbols, no “/month”, etc.).
    """
    if not raw_salary or re.search(r"\b(nil|null)\b", raw_salary, re.IGNORECASE):
        return "any"

    prompt = f"""
        You are given a raw salary string from a resume. Your task is to parse and return **only** the numeric amount (no currency symbols, no slashes, no words like "per", "month", "year", etc.). 

        Rules:
        1. If the input clearly indicates NIL or null (e.g. “NIL”, “null”, “N/A”), return exactly:
            any

        2. Otherwise, extract the first continuous sequence of digits (allow commas or decimal points) that represents the salary number.
            • Remove any commas (e.g. “1,500” → “1500”).
            • Ignore anything after the first numeric sequence—do not return ranges or extra text.
            • Example inputs and outputs:
                - “$1,500/month”        → “1500”
                - “1400”                → “1400”
                - “USD 2,000 per year”  → “2000”
                - “18/hr”               → “18”
                - “Approx. 3,200 monthly” → “3200”
                - “NIL”                 → “any”

        Return **exactly one token** as your output (no quotes, no extra text).
        Raw input:
        "{raw_salary.strip()}"
        """.strip()

    try:
        reply = client.chat_completion(
            question=prompt,
            system_prompt="You are an assistant that extracts the numeric portion of salary strings."
        ).strip()
    except Exception:
        # On model error, fall back to basic regex extraction:
        reply = raw_salary

    # Take only the first non-empty line
    first_line = next((line for line in reply.splitlines() if line.strip()), "").strip()

    # If model returned “any” (case-insensitive), normalize:
    if first_line.lower() == "any":
        return "any"

    # Remove any non-digit characters (commas, decimals OK if desired):
    m = re.search(r"[\d,]+(?:\.\d+)?", first_line)
    if not m:
        return "any"

    # Strip commas, keep decimal point if present
    number = m.group(0).replace(",", "")
    return number

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Split text into overlapping chunks for better semantic retrieval.
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # If this isn't the last chunk and we're not at the end of text
        if end < len(text):
            # Try to break at a sentence or word boundary
            last_period = text.rfind('.', start, end)
            last_space = text.rfind(' ', start, end)
            
            if last_period > start + chunk_size // 2:
                end = last_period + 1
            elif last_space > start + chunk_size // 2:
                end = last_space
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # Move start position with overlap
        start = max(start + 1, end - overlap)
        
        # Prevent infinite loop
        if start >= len(text):
            break
    
    return chunks


def load_or_create_faiss_index(embedding_dim: int = 768):
    """
    Load existing FAISS index and metadata, or create new ones.
    """
    index_path = Path(FAISS_INDEX_PATH)
    metadata_path = Path(FAISS_METADATA_PATH)
    
    if index_path.exists() and metadata_path.exists():
        print("----------------------------------------------------")
        print("Loading existing FAISS index...")
        print("----------------------------------------------------")
        
        # Load FAISS index
        index = faiss.read_index(str(index_path))
        
        # Load metadata
        with open(metadata_path, 'rb') as f:
            metadata = pickle.load(f)
        
        print(f"Loaded FAISS index with {index.ntotal} vectors")
        return index, metadata
    else:
        print("----------------------------------------------------")
        print("Creating new FAISS index...")
        print("----------------------------------------------------")
        
        # Create new FAISS index (using cosine similarity)
        index = faiss.IndexFlatIP(embedding_dim)  # Inner product for normalized vectors
        metadata = {
            'chunks': [],           # List of text chunks
            'candidate_keys': [],   # Corresponding candidate keys
            'filenames': [],        # Corresponding filenames
            'chunk_ids': []         # Unique chunk identifiers
        }
        
        return index, metadata


def save_faiss_index(index, metadata):
    """
    Save FAISS index and metadata to disk.
    """
    print("----------------------------------------------------")
    print("Saving FAISS index...")
    print("----------------------------------------------------")
    
    # Save FAISS index
    faiss.write_index(index, FAISS_INDEX_PATH)
    
    # Save metadata
    with open(FAISS_METADATA_PATH, 'wb') as f:
        pickle.dump(metadata, f)
    
    print(f"Saved FAISS index with {index.ntotal} vectors")


def add_to_faiss_index(index, metadata, chunks: List[str], embeddings: List[List[float]], 
                      candidate_key: str, filename: str):
    """
    Add new chunks and their embeddings to the FAISS index.
    """
    if not chunks or not embeddings:
        return
    
    # Normalize embeddings for cosine similarity (important for IndexFlatIP)
    embeddings_array = np.array(embeddings, dtype=np.float32)
    
    # L2 normalize for cosine similarity
    faiss.normalize_L2(embeddings_array)
    
    # Add to FAISS index
    index.add(embeddings_array)
    
    # Update metadata
    for i, chunk in enumerate(chunks):
        chunk_id = f"{candidate_key}_{filename}_{len(metadata['chunks'])}"
        metadata['chunks'].append(chunk)
        metadata['candidate_keys'].append(candidate_key)
        metadata['filenames'].append(filename)
        metadata['chunk_ids'].append(chunk_id)
    
    print(f"Added {len(chunks)} chunks to FAISS index")


def remove_candidate_from_faiss(index, metadata, candidate_key: str, filename: str):
    """
    Remove existing chunks for a candidate from FAISS index (for updates).
    This is a simplified approach - rebuild the index without the candidate's chunks.
    """
    # Find indices to remove
    indices_to_keep = []
    new_chunks = []
    new_candidate_keys = []
    new_filenames = []
    new_chunk_ids = []
    
    for i, (chunk, cand_key, fname, chunk_id) in enumerate(zip(
        metadata['chunks'], 
        metadata['candidate_keys'], 
        metadata['filenames'],
        metadata['chunk_ids']
    )):
        if not (cand_key == candidate_key and fname == filename):
            indices_to_keep.append(i)
            new_chunks.append(chunk)
            new_candidate_keys.append(cand_key)
            new_filenames.append(fname)
            new_chunk_ids.append(chunk_id)
    
    if len(indices_to_keep) < len(metadata['chunks']):
        print(f"Removing {len(metadata['chunks']) - len(indices_to_keep)} existing chunks for {candidate_key}")
        
        # Rebuild index with remaining vectors
        if indices_to_keep:
            # Get embeddings for remaining chunks
            remaining_embeddings = []
            for i in indices_to_keep:
                # This is inefficient but works for small datasets
                # For large datasets, consider using faiss.IndexIDMap
                vector = index.reconstruct(i)
                remaining_embeddings.append(vector)
            
            # Create new index
            new_index = faiss.IndexFlatIP(index.d)
            if remaining_embeddings:
                embeddings_array = np.array(remaining_embeddings, dtype=np.float32)
                new_index.add(embeddings_array)
            
            # Update metadata
            metadata['chunks'] = new_chunks
            metadata['candidate_keys'] = new_candidate_keys
            metadata['filenames'] = new_filenames
            metadata['chunk_ids'] = new_chunk_ids
            
            return new_index
    
    return index


def ensure_email_templates_table(cur):
    """
    Ensure the email_templates table exists with required columns.
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS public.email_templates (
            id SERIAL PRIMARY KEY,
            template_name VARCHAR(100) UNIQUE NOT NULL,
            subject_template TEXT NOT NULL,
            body_template TEXT NOT NULL,
            template_type VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # Insert default templates if they don't exist
    default_templates = [
        {
            'name': 'offer_template',
            'subject': 'Job Offer - {position} at {company}',
            'body': '''Dear {candidate_name},

We are pleased to offer you the position of {position} at {company}.

Position Details:
- Role: {position}
- Employment Type: {employment_type}
- Duration: {duration}
- Salary: {salary}
- Start Date: {start_date}

We believe your skills and experience make you an excellent fit for our team.

Please reply to confirm your acceptance by [DATE].

Best regards,
{sender_name}
{company}''',
            'type': 'offer'
        },
        {
            'name': 'rejection_email',
            'subject': 'Update on Your Application - {position}',
            'body': '''Dear {candidate_name},

Thank you for your interest in the {position} position and for taking the time to apply.

After careful consideration, we have decided to move forward with other candidates whose experience more closely matches our current needs.

We appreciate the time you invested in the application process and encourage you to apply for future opportunities.

Best wishes for your career development.

Best regards,
{sender_name}
{company}''',
            'type': 'rejection'
        },
        {
            'name': 'interview_invitation',
            'subject': 'Interview Invitation - {position}',
            'body': '''Dear {candidate_name},

Thank you for your application for the {position} position. We would like to invite you for an interview.

Interview Details:
- Position: {position}
- Date: [TO BE SCHEDULED]
- Time: [TO BE SCHEDULED]  
- Format: [ONLINE/IN-PERSON]
- Duration: Approximately 45 minutes

Please reply with your availability so we can schedule the interview.

Best regards,
{sender_name}
{company}''',
            'type': 'interview'
        }
    ]
    
    for template in default_templates:
        cur.execute("""
            INSERT INTO public.email_templates (template_name, subject_template, body_template, template_type)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (template_name) DO NOTHING;
        """, (template['name'], template['subject'], template['body'], template['type']))

def initialize_database():
    """Initialize all required database tables"""
    env = load_env_vars()
    conn = connect_postgres(env)
    cur = conn.cursor()
    
    ensure_resumes_table(cur)
    ensure_resumes_normal_table(cur)
    ensure_email_templates_table(cur)  # Add this line
    
    conn.commit()
    cur.close()
    conn.close()



