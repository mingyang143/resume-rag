import os
import json
import tempfile
import psycopg2
import subprocess
from typing import Dict, Optional, List, Callable
from dateutil import parser

from pdf2image import convert_from_path    # pip install pdf2image
from dotenv import load_dotenv

from ..backend.model import Qwen2VLClient    
from .helpers import connect_postgres, convert_docx_to_pdf_via_libreoffice, compute_months_between, normalize_salary, normalize_partfull_time, normalize_university, ensure_resumes_table, upsert_resume_metadata
from ..frontend.pdf_server import pdf_server

load_dotenv()

qwen_client = Qwen2VLClient(
        host="http://localhost",
        port=8001,
        model="Qwen/Qwen2.5-VL-7B-Instruct",
        temperature=0.7
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

def extract_fields_with_qwen(
    client: Qwen2VLClient,
    page_image_paths: List[str]
) -> Dict[str, Optional[str]]:
    """
    Given a list containing exactly the first‐page image of a resume,
    call Qwen2VL to extract these fields *including raw from_date & to_date*. Then
    in Python we compute the 'work_duration_category' by parsing those two fields.

    Returns a dict with keys:
      • email                    (email address or None)
      • work_duration_category   (one of "2-4 MONTHS"/"5-7 MONTHS"/"MORE THAN 7 MONTHS"/None)
      • university               (string or None)
      • applied_position         (string or None)
      • salary                   (string or None)
      • part_or_full             (PARTTIME/FULLTIME or None)
      • is_credit_bearing        (YES/NO or None)
      • citizenship              (CITIZEN/PR/FOREIGNER or None)
      • from_date                (raw string or None)
      • to_date                  (raw string or None)
    """

    fields: Dict[str, Optional[str]] = {
        "email":                  None,
        "work_duration_category": None,
        "university":             None,
        "applied_position":       None,
        "salary":                 None,
        "part_or_full":           None,
        "is_credit_bearing":      None,
        "citizenship":            None,
        # new raw date fields:
        "from_date":              None,
        "to_date":                None,
    }

    prompt_template = (
        "You are given an image of a single page from a candidate’s resume "
        "(an internship application form).  First, locate the “JOB APPLICATION” "
        "section (if it exists) on this page.  Within that section (or anywhere "
        "else on the page if no such heading exists), extract exactly the "
        "following ten fields and return precisely one JSON object (no extra text):\n\n"

        "  1. email                (email address from personal information section; e.g. \"john.doe@university.edu\" or null if not found)\n\n"
        "  2. from_date            (raw start date of the FIRST complete date–range under the label “Intended Internship Period,” exactly as it appears, or null)\n"
        "  3. to_date              (raw end date of that FIRST complete date–range under the label “Intended Internship Period,” exactly as it appears, or null)\n"
        "     – Only look at the dates listed next to “Intended Internship Period:”.  \n"
        "     – IF you ever see a slash (\"/\") in the date field, **ignore everything before the slash**.  \n"
        "       For example, if the text reads “20 May/10 July 2025”, treat “10 July” as the end date.  \n"
        "     – If you see multiple separate ranges under “Intended Internship Period”\n"
        "       (e.g. “10 June 2025 – 12 July 2025”, “12 July 2025 – 13 August 2025”),\n"
        "       choose the FIRST complete range (“10 June 2025 – 12 July 2025”) to split into from_date and to_date.\n"
        "     – If there are multiple separate ranges (e.g. “Jan – Mar”, “Mar – May”), always pick the FIRST one.  \n"
        "       - If that first range is “Jan – Mar”, then from_date = “Jan” and to_date = “Mar”.  \n"
        "       - If you see “Jan – Mar full-time”, drop “full-time” and return only “Jan – Mar”.  \n"
        "     – If you see a range written simply as “Jan – Dec”, split on the hyphen: \n"
        "       treat “Jan” as from_date and “Dec” as to_date.  \n"
        "     – If no date–range appears under “Intended Internship Period,” set both from_date and to_date to null.\n\n"


        "  4. university              (text string from the “JOB APPLICATION” or Education\n"
        "                             area, or null if not found)\n\n"

        "  5. applied_position        (text string from the “JOB APPLICATION” section; e.g.\n"
        "                             “GenAI Marketing & Promotion Intern,” or null if not found)\n\n"

        "  6. salary                  (text string found under the “School Recommended Internship Fee” section;\n"
        "                             e.g. “$1500/month” or “$15/hr,” or null if not found)\n\n"

        "  7. part_or_full            (ONE-word code: \n"
        "       – You are examining the **JOB APPLICATION** section of a resume. Your task:\n"
        "       – Find the exact question: “Is this a full-time or part-time internship?”\n"
        "       – Read its answer:\n"
        "       – If the answer contains “full time”, “full-time”, or “full” (case-insensitive), return exactly: FULLTIME\n\n"
        "       – If the answer contains “part time”, “part-time”, or “part” (case-insensitive), return exactly: PARTTIME\n\n"
        "       – If the answer is not clear, or if no such question is found, return null)\n\n"
        "       **Important:** Do **not** infer from any other part of the resume. Focus only on that one question and its immediate answer.\n\n"   

        "  8. is_credit_bearing       (ONE-word code:  \n"
        "       – You are examining the **JOB APPLICATION** section of a resume. Your task:\n"
        "       – Find the exact question: “Is this Internship School Credit Bearing?”\n"
        "       – Read its answer:\n"
        "       – If the answer contains “yes”, “credit-bearing”, return exactly: YES\n\n"
        "       – If the answer contains “no”, return exactly: NO\n\n"
        "       – If the answer is not clear, or if no such question is found, return null)\n\n"
        "       **Important:** Do **not** infer from any other part of the resume. Focus only on that one question and its immediate answer.\n\n"   

        "  9. citizenship             (ONE-word code based on the “Citizenship” checkbox row:  \n"
        "       – “CITIZEN” if the checkbox next to “Citizen” is checked,\n"
        "       – “PR”      if the checkbox next to “Singapore PR” is checked,\n"
        "       – “FOREIGNER” if the checkbox next to “Foreigner” is checked,\n"
        "       – null if none of those checkboxes are marked clearly)\n\n"

        "If any field is missing on this page (or in the “JOB APPLICATION” section), "
        "set that field’s value to null.  Do not return any extra keys beyond these nine.  "
        "Example valid output:\n"
        "{\"email\":\"john.doe@university.edu\","
        "\"from_date\":\"10 June 2025\","
        "\"to_date\":\"12 July 2025\","
        "\"university\":\"National University of Singapore\","
        "\"applied_position\":\"GenAI Marketing & Promotion Intern\","
        "\"salary\":\"$1500\","
        "\"part_or_full\":\"FULLTIME\","
        "\"is_credit_bearing\":\"NO\","
        "\"citizenship\":\"PR\"}\n"
    )

    # We expect exactly one page image in `page_image_paths`.
    for image_path in page_image_paths:
        try:
            reply = client.chat_completion(
                question=prompt_template,
                image_path=image_path,
                system_prompt="You are a JSON-extractor assistant."
            )
            # Print raw Qwen reply for human inspection:
            print("----------------------------------------------------")
            print(f"[{os.path.basename(image_path)}] Raw reply from Qwen:")
            print(reply.strip())
            print("----------------------------------------------------")
        except Exception as e:
            print(f"Error calling Qwen on {image_path}: {e}")
            continue

        lines = [
            line
            for line in reply.splitlines()
            if not line.strip().startswith("```")
        ]
        cleaned = "\n".join(lines)

        try:
            j = json.loads(cleaned.strip())
        except json.JSONDecodeError:
            continue

        for key in fields:
            if fields[key] is None and key in j:
                fields[key] = j[key]

        if fields["from_date"] and fields["to_date"]:
            category = compute_months_between(fields["from_date"], fields["to_date"])
            fields["work_duration_category"] = category

        if fields["university"]:
            uni = normalize_university(qwen_client, fields["university"])
            fields["university"] = uni

        if fields["part_or_full"]:
            pf = normalize_partfull_time(qwen_client, fields["part_or_full"])
            fields["part_or_full"] = pf

        
        salary = normalize_salary(qwen_client, fields["salary"])
        print("----------------------------------------------------")
        print(f"Normalized salary: {salary}")
        print("----------------------------------------------------")
        fields["salary"] = salary

        print("----------------------------------------------------")
        print("Ultimate extracted fields:\n")
        print(json.dumps(fields, indent=2, ensure_ascii=False))
        print("----------------------------------------------------")

        if all(fields[k] is not None for k in fields):
            break



    return fields

def ingest_all_resumes(
    resumes_folder: str,
    candidate_key: str,
) -> List[str]:
    """
    Main ingestion routine (no embedding):
      • Converts only first page → image.
      • Calls Qwen2VL to extract the 7 fields.
      • Inserts/Updates one row in Postgres.
      • Uploads PDF to web server and stores URL.
    """
    env = load_env_vars()
    conn = connect_postgres(env)
    cur = conn.cursor()

    print("----------------------------------------------------")
    print("Ensuring table exists in Postgres…")
    print("----------------------------------------------------")
    ensure_resumes_table(cur)
    conn.commit()

    all_files = [f for f in os.listdir(resumes_folder)
                 if f.lower().endswith((".pdf", ".docx"))]
    total = len(all_files)
    summary_logs: List[str] = []

    if total == 0:
        summary_logs.append("⚠️ No PDF/DOCX files found in the folder.")
        return summary_logs

    for idx, fname in enumerate(all_files, start=1):
        lower = fname.lower()

        # 1) If it's a .docx, convert to PDF first:
        if lower.endswith(".docx"):
            docx_path = os.path.join(resumes_folder, fname)
            pdf_basename = os.path.splitext(fname)[0] + ".pdf"
            pdf_path = os.path.join(resumes_folder, pdf_basename)

            print("----------------------------------------------------")
            print(f"Found DOCX: {fname} → converting to PDF → {pdf_basename}")
            print("----------------------------------------------------")
            try:
                convert_docx_to_pdf_via_libreoffice(docx_path, pdf_path)
            except Exception as e:
                summary_logs.append(f"❌ ERROR converting {fname} to PDF: {e}")
                continue  # skip this file if conversion fails

            processing_pdf = pdf_basename

        # 2) If it's already a .pdf, use it directly:
        elif lower.endswith(".pdf"):
            processing_pdf = fname
            pdf_path = os.path.join(resumes_folder, processing_pdf)

        else:
            continue

        print("----------------------------------------------------")
        print(f"Processing PDF: {fname}")
        print("----------------------------------------------------")

        # 3) Only convert the FIRST page:
        with tempfile.TemporaryDirectory() as per_resume_tmpdir:
            pages = convert_from_path(pdf_path, dpi=150, first_page=1, last_page=1)
            if not pages:
                summary_logs.append(f"⚠️ No pages in {processing_pdf}, skipping.")
                continue

            image_for_qwen = os.path.join(
                per_resume_tmpdir,
                f"{os.path.splitext(fname)[0]}_page_1.jpg"
            )
            pages[0].save(image_for_qwen, "JPEG")

            # 4) Extract via Qwen:
            print("----------------------------------------------------")
            print("  • Calling Qwen to extract metadata fields (first page only)…")
            print("----------------------------------------------------")
            fields = extract_fields_with_qwen(qwen_client, [image_for_qwen])

            wd_cat = fields.get("work_duration_category")
            if wd_cat is None:
                print("----------------------------------------------------")
                print("No valid work_duration_category found.")
                print("  • Skipping this resume.")
                print("----------------------------------------------------")
                summary_logs.append(
                    f"⚠️ {processing_pdf} skipped (no valid work_duration_category)."
                )
                continue

            # 5) Upload PDF to web server BEFORE database insertion
            print("----------------------------------------------------")
            print(f"  • Uploading PDF to web server: {fname}")
            print("----------------------------------------------------")
            
            # Determine file type
            if 'mikomiko' in fname.lower():
                file_type = 'mikomiko'
            else:
                file_type = 'resume'
            
            # Upload PDF and get URL
            pdf_url = pdf_server.upload_pdf(pdf_path, candidate_key, file_type)
            
            # Add PDF URL to fields if upload successful
            if pdf_url:
                fields['pdf_url'] = pdf_url
                print(f"✅ PDF uploaded to server: {pdf_url}")
            else:
                print(f"❌ Failed to upload PDF: {fname}")
                fields['pdf_url'] = None

            # 6) Upsert into Postgres (now includes PDF URL):
            print("----------------------------------------------------")
            print("  • Upserting metadata into Postgres…")
            print("----------------------------------------------------")
            upsert_resume_metadata(cur, processing_pdf, candidate_key, fields)
            conn.commit()
            print(f"  ✓ Metadata and PDF URL stored for {fname}.")

            summary_logs.append(f"✓ Done with {processing_pdf}")

    cur.close()
    conn.close()
    
    print("----------------------------------------------------")
    print("All resumes processed (first-page only).")
    print("----------------------------------------------------")

    return summary_logs