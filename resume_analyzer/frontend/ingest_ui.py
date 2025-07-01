import os
import sys
import time
import streamlit as st
import psycopg2
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# Ensure project root is on sys.path so that "resume_analyzer" can be imported
# ──────────────────────────────────────────────────────────────────────────────
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from resume_analyzer.ingestion.ingest_pg import ingest_all_resumes, load_env_vars
from resume_analyzer.ingestion.ingest_all import ingest_all_candidates
from resume_analyzer.ingestion.helpers import (
    connect_postgres,
    ensure_resumes_table,
    ensure_resumes_normal_table,
    upsert_resume_metadata,
    upsert_resumes_normal,
)
from resume_analyzer.ingestion.ingest_normal import ingest_resume_normal
from resume_analyzer.backend.model import Qwen2VLClient
from resume_analyzer.backend.helpers import chat_with_resumes, fetch_candidate_keys, detect_email_intent
from resume_analyzer.ingestion.ingest_normal import ingest_resume_normal
from resume_analyzer.ingestion.ingest_pg import extract_fields_with_qwen, qwen_client
from resume_analyzer.ingestion.helpers import convert_docx_to_pdf_via_libreoffice, initialize_database
from resume_analyzer.frontend.helpers import render_deletion_tab, render_overview_dashboard, get_quick_stats, render_skills_management_tab, render_score_table, render_delete_all_resumes
from resume_analyzer.backend.email_service import EmailService
from pdf2image import convert_from_path
import tempfile
import json

email_service = EmailService()

try:
    initialize_database()
    print("✅ Database initialized successfully")
except Exception as e:
    print(f"❌ Error initializing database: {e}")


# Initialize session state for pending emails
if 'pending_email' not in st.session_state:
    st.session_state.pending_email = None

# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()  # In case helpers need environment variables

# ──────────────────────────────────────────────────────────────────────────────
# STREAMLIT APP
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="📥 Resume Management Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS (optional)
st.markdown(
    """
    <style>
    body {
        background-color: #f5f5f5;
    }
    .stApp [data-testid="stSidebar"] {
        background-color: #2E3B4E;
        color: white;
    }
    .stApp [data-testid="stSidebar"] .css-1d391kg {
        background-color: #2E3B4E;
    }
    .stApp .css-18e3th9 {
        padding-top: 1rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    .title {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
    }
    .subtitle {
        font-size: 1.2rem;
        color: #333333;
    }
    .log-entry {
        font-family: monospace;
        font-size: 0.9rem;
        color: #333333;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Sidebar: Three Modes (Ingestion / Manual Add / Filter) ---
with st.sidebar:
    st.markdown("## ⚙️ Select Mode")
    mode = st.radio(
        "Select mode",
        [   "📊 Overview", 
            "📥 Ingestion",
            "✏️ Manual Add",
            "📋 Skill Categories",
            "🗑️ Deletion",
            "🔍 Filter Records",
            
        ],
        index=0,
    )

    if mode == "📥 Ingestion":
        st.markdown("### 📂 Ingestion Settings")
        resumes_folder = st.text_input(
            "Folder Path",
            placeholder="/path/to/resumes/folder",
        )
        st.caption("Enter the absolute path to the folder containing PDF/DOCX resumes.")
        run_button = st.button("🔄 Run Ingestion")
        
    elif mode == "✏️ Manual Add":
        pass

    elif mode == "📋 Skill Categories":
        render_skills_management_tab()
        
    elif mode == "🔍 Filter Records":
        st.markdown("### 🔍 Filter Records")
        st.caption("Choose filters and click “Apply Filters” to retrieve matching filenames.")
        filter_button = st.button("🗂️ Apply Filters")

# --- Main Area Header ---
st.markdown('<div class="title">📥 Resume Management Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">Use the sidebar to ingest, add, or filter records.</div>',
    unsafe_allow_html=True,
)
st.markdown("---")

# Placeholder containers for progress/logs/result
progress_placeholder = st.empty()
status_placeholder = st.empty()
log_placeholder = st.empty()
results_placeholder = st.empty()

# Update the main content section to handle the new Overview mode
# ──────────────────────────────────────────────────────────────────────────────
# Overview Mode
# ──────────────────────────────────────────────────────────────────────────────
if mode == "📊 Overview":
    render_overview_dashboard()
    render_score_table()

    
# ──────────────────────────────────────────────────────────────────────────────
# Ingestion Mode
# ──────────────────────────────────────────────────────────────────────────────
elif mode == "📥 Ingestion":

    if not resumes_folder:
        status_placeholder.info("Enter a folder path in the sidebar to begin ingestion.")
        st.stop()

    if not os.path.isdir(resumes_folder):
        status_placeholder.error("❌ The provided path does not exist or is not a directory.")
        st.stop()

    # Show folder summary
    candidates = [
        d for d in os.listdir(resumes_folder)
        if os.path.isdir(os.path.join(resumes_folder, d))
    ]

    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("📂 Folder", os.path.basename(resumes_folder))
        st.metric("🗂️ Candidates", len(candidates))
    with col2:
        st.dataframe(
            {
                "Candidate folder": candidates,
                "Num Resumes": [
                    len([f for f in os.listdir(os.path.join(resumes_folder, d))
                    if f.lower().endswith((".pdf", ".docx"))
                ])
                for d in candidates
                ],
            },
            height=200,
        )

    st.markdown("---")

    if run_button:
        # Clear placeholders
        progress_placeholder.empty()
        status_placeholder.empty()
        log_placeholder.empty()
        results_placeholder.empty()

        total_folders = len(candidates)
        if total_folders == 0:
            status_placeholder.warning("⚠️ No folders found to ingest.")
        else:
            # Initialize progress bar
            progress_bar = progress_placeholder.progress(0.0, text="Starting…")
            status_placeholder.info(f"Starting ingestion of {total_folders} folder(s)…")

            logs: list[str] = []

            # Define callback for each processed file
            def progress_callback(idx: int, total: int, filename: str):
                fraction = idx / total
                progress_bar.progress(fraction, text=f"Processing {filename} ({idx}/{total})")
                logs.append(f"[{idx}/{total}] Processed: {filename}")
                log_placeholder.text("\n".join(logs))

            # Run ingestion
            summary = ingest_all_candidates(resumes_folder, progress_callback)

            # Finalize progress and status
            progress_bar.progress(1.0, text="Completed")
            status_placeholder.success("✅ Ingestion complete!")

            # Append summary logs
            for line in summary:
                logs.append(line)
            log_placeholder.text("\n".join(logs))

    else:
        status_placeholder.info("Click 'Run Ingestion' in the sidebar to begin.")

# ──────────────────────────────────────────────────────────────────────────────
# Manual Add Mode
# ──────────────────────────────────────────────────────────────────────────────
elif mode == "✏️ Manual Add":
    st.markdown("### 📁 Folder-based Ingestion with Manual Editing")
    st.caption("Select a folder containing exactly 2 files: one with 'mikomiko' in filename, one without.")
    
    folder_path = st.text_input(
        "📂 Folder Path", 
        placeholder="/path/to/candidate/folder",
        help="Path to folder containing exactly 2 resume files (PDF/DOCX)"
    )
    
    extract_button = st.button("🔍 Extract Fields", key="extract_fields")

    if extract_button and folder_path:
        if not os.path.isdir(folder_path):
            st.error("❌ Invalid folder path")
        else:
            with st.spinner("🔍 Scanning folder and extracting metadata..."):
                try:
                    # Get all PDF/DOCX files in the folder
                    files = [f for f in os.listdir(folder_path) 
                           if f.lower().endswith(('.pdf', '.docx'))]
                    
                    if len(files) != 2:
                        st.error(f"❌ Expected exactly 2 files (PDF/DOCX), found {len(files)}: {files}")
                    else:
                        # Identify which file has "mikomiko" in filename
                        miko_file = None
                        other_file = None
                        
                        for f in files:
                            if "mikomiko" in f.lower():
                                miko_file = f
                            else:
                                other_file = f
                        
                        if not miko_file:
                            st.error("❌ No file with 'mikomiko' in filename found")
                        elif not other_file:
                            st.error("❌ Expected one file with 'mikomiko' and one without")
                        else:
                            # Store file info in session state
                            st.session_state.folder_files = {
                                'miko_file': miko_file,
                                'other_file': other_file,
                                'folder_path': folder_path
                            }
                            
                            # Process mikomiko file for metadata extraction
                            miko_path = os.path.join(folder_path, miko_file)
                            st.info(f"📋 Found mikomiko file: {miko_file}")
                            st.info(f"📄 Found other file: {other_file}")
                            
                            try:
                                # Convert DOCX to PDF if needed
                                processing_path = miko_path
                                if miko_file.lower().endswith('.docx'):
                                    st.info("🔄 Converting DOCX to PDF...")
                                    pdf_basename = os.path.splitext(miko_file)[0] + ".pdf"
                                    pdf_path = os.path.join(folder_path, pdf_basename)
                                    convert_docx_to_pdf_via_libreoffice(miko_path, pdf_path)
                                    processing_path = pdf_path
                                    st.success("✅ DOCX converted to PDF")
                                
                                # Extract metadata fields using ingest_pg logic
                                st.info("🔍 Extracting metadata fields...")
                                with tempfile.TemporaryDirectory() as tmpdir:
                                    # Convert first page to image
                                    pages = convert_from_path(processing_path, dpi=150, first_page=1, last_page=1)
                                    if not pages:
                                        st.error("❌ Could not extract pages from PDF")
                                    else:
                                        image_path = os.path.join(tmpdir, "page_1.jpg")
                                        pages[0].save(image_path, "JPEG")
                                        
                                        # Extract fields using the same function as ingest_pg
                                        extracted_fields = extract_fields_with_qwen(qwen_client, [image_path])
                                        st.session_state.extracted_fields = extracted_fields
                                        st.success("✅ Metadata extracted successfully!")

                                        # Add print statements to inspect the extracted fields
                                        print("=" * 60)
                                        print("EXTRACTED FIELDS INSPECTION")
                                        print("=" * 60)
                                        print(f"Type of extracted_fields: {type(extracted_fields)}")
                                        print(f"Raw extracted_fields: {extracted_fields}")
                                        print("-" * 40)
                                
                            except Exception as e:
                                st.error(f"❌ Error processing mikomiko file: {e}")
                                st.session_state.extracted_fields = {}
                
                except Exception as e:
                    st.error(f"❌ Error scanning folder: {e}")

    # Show editable fields if we have scanned files
    if hasattr(st.session_state, 'folder_files') and st.session_state.folder_files:
        files_info = st.session_state.folder_files
        extracted = getattr(st.session_state, 'extracted_fields', {})
        
        st.markdown("---")
        st.markdown("#### ✏️ Edit Extracted Metadata")
        st.caption("Review and modify the extracted fields before ingestion")
        
        # Show file information
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"📋 Metadata source: {files_info['miko_file']}")
        with col2:
            st.info(f"📄 Resume file: {files_info['other_file']}")
        
        # Create editable form
        with st.form("metadata_edit_form"):
            st.markdown("##### 📝 Metadata Fields")
            
            # Get candidate key from folder name
            folder_name = os.path.basename(files_info['folder_path'])
            candidate_key = st.text_input(
                "🔑 Candidate Key", 
                value=folder_name,
                help="Usually the folder name"
            )
            
            col1, col2 = st.columns(2)
            
            with col1:
                work_duration = st.text_input(
                    "⏱️ Work Duration Category",
                    value=extracted.get('work_duration_category', ''),
                    placeholder="e.g., 2-4 MONTHS"
                )
                
                university = st.text_input(
                    "🎓 University",
                    value=extracted.get('university', ''),
                    placeholder="e.g., National University of Singapore"
                )
                
                email = st.text_input(
                    "📧 Email Address",
                    value=extracted.get('email', ''),
                    placeholder="e.g., student@university.edu",
                    help="Required field for sending notifications"
                )
                
                applied_position = st.text_input(
                    "💼 Applied Position",
                    value=extracted.get('applied_position', ''),
                    placeholder="e.g., Software Engineer Intern"
                )
                
                salary = st.text_input(
                    "💰 Salary",
                    value=extracted.get('salary', ''),
                    placeholder="e.g., 1500 or any"
                )
                
                from_date = st.text_input(
                    "📅 From Date",
                    value=extracted.get('from_date', ''),
                    placeholder="e.g., 10 Jun 2025"
                )
            
            with col2:
                part_or_full = st.selectbox(
                    "⏰ Employment Type",
                    ["", "FULLTIME", "PARTTIME"],
                    index=0 if not extracted.get('part_or_full') else 
                          (1 if extracted.get('part_or_full') == 'FULLTIME' else 2)
                )
                
                is_credit_bearing = st.selectbox(
                    "🎖️ Credit Bearing",
                    ["", "YES", "NO"],
                    index=0 if not extracted.get('is_credit_bearing') else 
                          (1 if extracted.get('is_credit_bearing') == 'YES' else 2)
                )
                
                citizenship_options = ["", "CITIZEN", "PR", "FOREIGNER"]
                citizenship_value = extracted.get('citizenship', '').upper()
                citizenship_index = citizenship_options.index(citizenship_value) if citizenship_value in citizenship_options else 0
                
                citizenship = st.selectbox(
                    "🌍 Citizenship",
                    citizenship_options,
                    index=citizenship_index
                )
                
                to_date = st.text_input(
                    "📅 To Date",
                    value=extracted.get('to_date', ''),
                    placeholder="e.g., 18 Jul 2025"
                )
            
            # Show preview of what will be ingested
            st.markdown("##### 👀 Preview")
            preview_data = {
                "candidate_key": candidate_key,
                "email": email or None,
                "work_duration_category": work_duration or None,
                "university": university or None,
                "applied_position": applied_position or None,
                "salary": salary or None,
                "part_or_full": part_or_full or None,
                "is_credit_bearing": is_credit_bearing or None,
                "citizenship": citizenship or None,
                "from_date": from_date or None,
                "to_date": to_date or None,
            }
            st.json(preview_data)
            
            # Ingest button
            ingest_folder_button = st.form_submit_button("🚀 Ingest Folder", type="primary")
            
            if ingest_folder_button:
                if not candidate_key.strip():
                    st.error("❌ Candidate key is required")
                elif not email.strip():
                    st.error("❌ Email address is required")
                else:
                    try:
                        # Connect to database
                        env = load_env_vars()
                        conn = connect_postgres(env)
                        cur = conn.cursor()
                        ensure_resumes_table(cur)
                        ensure_resumes_normal_table(cur)
                        conn.commit()
                        
                        success_count = 0
                        
                        with st.spinner("🔄 Processing files..."):
                            # Process mikomiko file - insert metadata into resumes_metadata
                            miko_filename = files_info['miko_file']
                            
                            # Prepare metadata fields from the edited form
                            fields = {
                                "email": email.strip(),
                                "work_duration_category": work_duration.strip() or None,
                                "university": university.strip() or None,
                                "applied_position": applied_position.strip() or None,
                                "salary": salary.strip() or None,
                                "part_or_full": part_or_full.strip() or None,
                                "is_credit_bearing": is_credit_bearing.strip() or None,
                                "citizenship": citizenship.strip() or None,
                                "from_date": from_date.strip() or None,
                                "to_date": to_date.strip() or None,
                            }
                            
                            # Insert mikomiko file metadata into resumes_metadata
                            upsert_resume_metadata(cur, miko_filename, candidate_key.strip(), fields)
                            st.success(f"✅ Metadata inserted for: {miko_filename}")
                            success_count += 1
                            
                            # Process other file - insert metadata into resumes_metadata
                            other_filename = files_info['other_file']
                            
                            # Process other file with ingest_normal for resumes_normal table
                            other_file_path = os.path.join(files_info['folder_path'], other_filename)
                            other_file_path = os.path.join(files_info['folder_path'], other_filename)
                            try:
                                # Create temporary folder with just this file
                                with tempfile.TemporaryDirectory() as temp_folder:
                                    # Copy the file to temp folder (or create symlink)
                                    import shutil
                                    temp_file_path = os.path.join(temp_folder, other_filename)
                                    shutil.copy2(other_file_path, temp_file_path)
                                    ingest_resume_normal(temp_folder, candidate_key.strip())
                                    
                                st.success(f"✅ Skills extracted and upserted for: {other_filename}")
                                success_count += 1
                            except Exception as e:
                                st.error(f"❌ Error processing {other_filename} with ingest_normal: {e}")

                        conn.commit()
                        cur.close()
                        conn.close()
                        
                        st.success(f"🎉 Successfully processed {success_count} operations!")
                        
                        # Clear session state
                        if hasattr(st.session_state, 'folder_files'):
                            del st.session_state.folder_files
                        if hasattr(st.session_state, 'extracted_fields'):
                            del st.session_state.extracted_fields
                            
                    except Exception as e:
                        st.error(f"❌ Error during ingestion: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# Deletion Mode
# ──────────────────────────────────────────────────────────────────────────────
elif mode == "🗑️ Deletion":
    render_deletion_tab()
    render_delete_all_resumes()
    
# ──────────────────────────────────────────────────────────────────────────────
# Filter Records Mode
# ──────────────────────────────────────────────────────────────────────────────

elif mode == "🔍 Filter Records":
    if "matched_files" not in st.session_state:
        st.session_state.matched_files = []

    with st.expander("🔍 Filter & Chat", expanded=True):
        st.caption("Select filters, hit Apply, then chat about the results below.")

        st.markdown("### 🔍 Filter Records")

        # Step 1: Fetch distinct values from the database for each non‐salary column
        env = load_env_vars()
        conn = connect_postgres(env)
        cur = conn.cursor()

        ensure_resumes_table(cur)
        conn.commit()

        def fetch_distinct(column: str) -> list:
            cur.execute(f"SELECT DISTINCT {column} FROM public.resumes_metadata;")
            return [row[0] for row in cur.fetchall() if row[0] is not None]

        # Fetch distinct skills categories from resumes_normal table
        def fetch_distinct_skills_categories() -> list:
            """Fetch all unique skills categories from resumes_normal table."""
            try:
                cur.execute("""
                    SELECT DISTINCT unnest(skills_categories) as category 
                    FROM public.resumes_normal 
                    WHERE skills_categories IS NOT NULL 
                    AND array_length(skills_categories, 1) > 0
                    ORDER BY category;
                """)
                return [row[0] for row in cur.fetchall()]
            except Exception as e:
                st.error(f"Error fetching skills categories: {e}")
                return []
            
        distinct_wd       = fetch_distinct("work_duration_category")
        distinct_uni      = fetch_distinct("university")
        distinct_applied_pos = fetch_distinct("applied_position") 
        distinct_part     = fetch_distinct("part_or_full")
        distinct_credit   = fetch_distinct("is_credit_bearing")
        distinct_citizen  = fetch_distinct("citizenship")
        distinct_skills   = fetch_distinct_skills_categories()

        # Step 2: Show multiselect filters for everything except salary
        sel_wd       = st.multiselect("Work Duration Category", distinct_wd)
        sel_uni      = st.multiselect("University", distinct_uni)
        sel_applied  = st.multiselect("Applied Position", distinct_applied_pos)
        sel_part     = st.multiselect("Part or Full", distinct_part)
        sel_credit   = st.multiselect("Credit Bearing", distinct_credit)
        sel_citizen  = st.multiselect("Citizenship", distinct_citizen)
        sel_skills   = st.multiselect("Skills Categories", distinct_skills)

        # Step 3: Add a fixed Salary Range dropdown
        salary_ranges = [
            "ANY",         # means “no numeric restriction; include all rows (even 'any')”
            "800-1000",
            "1000-1200",
            "1200-1400",
            "1400-1600"
        ]
        sel_salary = st.selectbox("Salary Range", salary_ranges, index=0)

        if filter_button:
            clauses = []
            params = []

            base_query = """
                SELECT DISTINCT rm.filename 
                FROM public.resumes_metadata rm
                JOIN public.resumes_normal rn ON rm.candidate_key = rn.candidate_key
                WHERE 1=1
            """

            # non‐salary filters (same as before)
            if sel_wd:
                clauses.append("work_duration_category = ANY(%s)")
                params.append(sel_wd)
            if sel_uni:
                clauses.append("university = ANY(%s)")
                params.append(sel_uni)
            if sel_applied:
                clauses.append("applied_position = ANY(%s)")
                params.append(sel_applied)
            if sel_part:
                clauses.append("part_or_full = ANY(%s)")
                params.append(sel_part)
            if sel_credit:
                clauses.append("is_credit_bearing = ANY(%s)")
                params.append(sel_credit)
            if sel_citizen:
                clauses.append("citizenship = ANY(%s)")
                params.append(sel_citizen)
            if sel_skills:
                # Check if ANY of the selected skills are in the skills_categories array
                skills_conditions = []
                for skill in sel_skills:
                    skills_conditions.append("(%s = ANY(rn.skills_categories))")
                    params.append(skill)
                
                if skills_conditions:
                    clauses.append("(" + " OR ".join(skills_conditions) + ")")


            # Salary filter (add rm. prefix)
            if sel_salary != "ANY":
                low_str, high_str = sel_salary.split("-")
                low, high = int(low_str), int(high_str)
                clauses.append(
                    "(rm.salary = 'any' OR (rm.salary ~ '^[0-9]+$' AND CAST(rm.salary AS INTEGER) BETWEEN %s AND %s))"
                )  # ← Added rm. prefix
                params.extend([low, high])

            # where_clause = " AND ".join(clauses) if clauses else "TRUE"
            # query = f"""
            #     SELECT filename 
            #     FROM public.resumes_metadata 
            #     WHERE {where_clause}
            #     ORDER BY filename;
            # """

            if clauses:
                where_clause = " AND " + " AND ".join(clauses)
            else:
                where_clause = ""
            
            query = base_query + where_clause + " ORDER BY rm.filename;"

            try:
                cur.execute(query, tuple(params))
                matched = [row[0] for row in cur.fetchall()]
                st.session_state.matched_files = matched
                # if matched:
                #     results_placeholder.success(f"Found {len(matched)} matching file(s):")
                #     results_placeholder.table({"Filename": matched})
                # else:
                #     results_placeholder.info("No records matched the selected filters.")
            except Exception as e:
                results_placeholder.error(f"❌ Error querying Postgres: {e}")
                cur.close()
                conn.close()

            cur.close()
            conn.close()

            results_block = results_placeholder.container()

            with results_block:
                if matched:
                    st.success(f"Found {len(matched)} matching file(s):")
                    st.table({"Filename": matched})

                    # Show summary of applied filters
                    filter_summary = []
                    if sel_wd: filter_summary.append(f"Work Duration: {', '.join(sel_wd)}")
                    if sel_uni: filter_summary.append(f"University: {', '.join(sel_uni)}")
                    if sel_applied: filter_summary.append(f"Position: {', '.join(sel_applied)}")
                    if sel_part: filter_summary.append(f"Employment: {', '.join(sel_part)}")
                    if sel_credit: filter_summary.append(f"Credit: {', '.join(sel_credit)}")
                    if sel_citizen: filter_summary.append(f"Citizenship: {', '.join(sel_citizen)}")
                    if sel_skills: filter_summary.append(f"Skills: {', '.join(sel_skills)}")
                    if sel_salary != "ANY": filter_summary.append(f"Salary: {sel_salary}")
                    
                    if filter_summary:
                        st.info("🔍 **Applied Filters:** " + " | ".join(filter_summary))
                                
                else:
                    st.info("No records matched the selected filters.")


    # ————— expander closed here —————

    # Now, **outside** the expander, render the chat interface if there are matches:
    matched = st.session_state.matched_files
    print("----------------------------------------------------")
    print(f"Matched files: {matched}")
    print("----------------------------------------------------")
    if matched:
        st.markdown("---")
        st.markdown("### 💬 Chat about these resumes")

        # Get candidate keys from matched filenames
        try:
            filename_to_candidate = fetch_candidate_keys(matched)
            candidate_keys = list(filename_to_candidate.values())
            
            print("----------------------------------------------------")
            print(f"Retrieved candidate keys: {candidate_keys}")
            print("----------------------------------------------------")
            
            if not candidate_keys:
                st.warning("⚠️ No candidate keys found for the matched files. Please check the database.")
            else:
                # Show which candidates are available for chat
                st.info(f"💬 Ready to chat about {len(candidate_keys)} candidates: {', '.join(candidate_keys)}")
                
        except Exception as e:
            st.error(f"❌ Error retrieving candidate keys: {e}")
            candidate_keys = []

        if candidate_keys:
            # use a unique key per set of files
            chat_key = "chat_" + "_".join(sorted(matched))  # Sort for consistent key
            if chat_key not in st.session_state:
                st.session_state[chat_key] = []

            # display history
            for msg in st.session_state[chat_key]:
                st.chat_message(msg["role"]).write(msg["content"])

            # user input
            user_input = st.chat_input("Ask me anything about these candidates...", key="input_"+chat_key)

            if user_input:
                # Add user message to history
                st.session_state[chat_key].append({"role":"user","content":user_input})
                st.chat_message("user").write(user_input)
                
                # Check if this is a confirmation response FIRST (outside all other logic)
                if st.session_state.get('pending_email'):
                    confirmation_words = ['send', 'yes', 'confirm', 'ok', 'proceed', 'go ahead', 'y']
                    cancel_words = ['cancel', 'no', 'stop', 'abort', 'don\'t send', 'n']
                    
                    user_response = user_input.lower().strip()
                    
                    # Use exact word matching instead of substring matching
                    is_confirmation = any(user_response == word or user_response.startswith(word + ' ') or user_response.endswith(' ' + word) for word in confirmation_words)
                    is_cancellation = any(user_response == word or user_response.startswith(word + ' ') or user_response.endswith(' ' + word) for word in cancel_words)
                    
                    if is_confirmation:
                        # User confirmed - send the email
                        pending = st.session_state.pending_email
                        
                        with st.spinner(f"📧 Sending {pending['template_type'].replace('_', ' ')} to {pending['candidate_key']}..."):
                            try:
                                result = email_service.send_template_email_with_fields(
                                    pending['candidate_key'], 
                                    pending['template_type'], 
                                    pending['extracted_fields'],
                                    preview_only=False  # Actually send this time
                                )

                                if result['success']:
                                    reply = f"✅ {result['message']}"
                                    
                                    # Show final confirmation
                                    with st.expander("📧 Email Sent Details"):
                                        st.write(f"**To:** {pending['recipient_email']}")
                                        st.write(f"**Subject:** {result['subject']}")
                                        st.text_area("Email Body:", result['body'], height=200)
                                else:
                                    reply = f"❌ {result['error']}"
                                    
                            except Exception as e:
                                reply = f"❌ Error sending email: {str(e)}"
                        
                        # Clear pending email
                        del st.session_state.pending_email
                        
                    elif is_cancellation:
                        # User cancelled
                        reply = "📧 Email sending cancelled."
                        del st.session_state.pending_email
                        
                    else:
                        # User entered something else - remind them about pending email
                        pending = st.session_state.pending_email
                        reply = f"⚠️ **Please respond to the pending email first!**\n\n"
                        reply += f"There is an email to **{pending['candidate_key']}** waiting for your confirmation.\n\n"
                        reply += "Please reply with:\n"
                        reply += "• **'send'**, **'yes'**, **'confirm'**, **'ok'**, **'proceed'** to send the email\n"
                        reply += "• **'cancel'**, **'no'**, **'stop'**, **'abort'** to cancel the email\n\n"
                        reply += f"Your response '{user_input}' was not recognized as a clear confirmation or cancellation.\n"
                        reply += "I cannot process other requests until you decide on this email."
                
                else:
                    # No pending email - proceed with normal logic
                    filename_to_candidate = fetch_candidate_keys(matched)
                    current_candidate_keys = list(set(filename_to_candidate.values()))
                    
                    print("----------------------------------------------------")
                    print(f"📧 Checking email intent for: {user_input}")
                    print("----------------------------------------------------")
                    
                    email_intent = detect_email_intent(user_input, current_candidate_keys)
                    
                    print("----------------------------------------------------")
                    print(f"📧 Email intent detected: {email_intent}")
                    print("----------------------------------------------------")

                    if email_intent['is_email_request']:
                        # Handle email sending with extracted fields
                        template_type = email_intent['template_type']
                        candidate_key = email_intent['candidate_key']
                        extracted_fields = email_intent.get('extracted_fields', {})
                        
                        if not candidate_key:
                            reply = f"❌ I understand you want to send an email, but I couldn't identify which candidate you're referring to. Available candidates in current results: {', '.join(current_candidate_keys)}"
                        elif not template_type:
                            reply = f"❌ I understand you want to send an email to {candidate_key}, but I couldn't determine what type of email. Available types: offer, rejection, interview."
                        else:
                            # First time - show preview
                            with st.spinner(f"📧 Preparing {template_type.replace('_', ' ')} for {candidate_key}..."):
                                try:
                                    result = email_service.send_template_email_with_fields(
                                        candidate_key, 
                                        template_type, 
                                        extracted_fields,
                                        preview_only=True  # Preview mode
                                    )

                                    if result['success'] and result.get('preview_mode'):
                                        # Show email preview
                                        reply = "📧 Email Preview - Please review before sending:"
                                        
                                        col1, col2 = st.columns([3, 1])
                                        with col1:
                                            st.write(f"**To:** {result['recipient_email']}")
                                            st.write(f"**Subject:** {result['subject']}")
                                        with col2:
                                            st.write(f"**Template:** {template_type}")
                                        
                                        # Show email body in expandable section
                                        with st.expander("📧 Full Email Preview", expanded=True):
                                            st.text_area("Email Body:", result['body'], height=300)
                                        
                                        # Store pending email in session state
                                        st.session_state.pending_email = {
                                            'candidate_key': candidate_key,
                                            'template_type': template_type,
                                            'extracted_fields': extracted_fields,
                                            'recipient_email': result['recipient_email']
                                        }
                                        
                                        # Show confirmation prompt
                                        reply += "\n\n⚠️ **Confirmation Required:** Reply with **'send'**, **'yes'**, or **'confirm'** to send this email, or **'cancel'** to abort."
                                        
                                    else:
                                        reply = f"❌ {result.get('error', 'Failed to prepare email preview')}"
                                        
                                except Exception as e:
                                    reply = f"❌ Error preparing email: {str(e)}"

                    else:
                        # Handle regular chat
                        with st.spinner("🤔 Analyzing your question..."):
                            try:
                                # Use the intelligent chat function
                                result = chat_with_resumes(
                                    user_query=user_input,
                                    candidate_keys=candidate_keys,
                                    context_limit=3
                                )
                                
                                # Get the response
                                reply = result["answer"]
                                query_type = result["query_type"]
                                skills_extracted = result.get("skills_extracted", [])
                                candidates_analyzed = result.get("candidates_analyzed", [])
                                
                                # Add metadata to the response for transparency
                                if query_type == "skill_matching" and skills_extracted:
                                    reply += f"\n\n*🔍 Skills identified: {', '.join(skills_extracted)}*"
                                
                                if candidates_analyzed:
                                    reply += f"\n\n*👥 Candidates analyzed: {', '.join(candidates_analyzed)}*"
                                
                                print("----------------------------------------------------")
                                print(f"Chat response - Query type: {query_type}")
                                print(f"Skills extracted: {skills_extracted}")
                                print(f"Candidates analyzed: {candidates_analyzed}")
                                print("----------------------------------------------------")
                                
                            except Exception as e:
                                reply = f"❌ I encountered an error while processing your question: {str(e)}"
                                print("----------------------------------------------------")
                                print(f"Chat error: {e}")
                                print("----------------------------------------------------")
                
                # Add assistant response to history and display
                st.session_state[chat_key].append({"role":"assistant","content":reply})
                st.chat_message("assistant").write(reply)


            
            # if user_input:
            #     # Add user message to history
            #     st.session_state[chat_key].append({"role":"user","content":user_input})
            #     st.chat_message("user").write(user_input)
                
            #     # Check if this is an email request using LLM
            #     filename_to_candidate = fetch_candidate_keys(matched)
            #     current_candidate_keys = list(set(filename_to_candidate.values()))
            #     email_intent = detect_email_intent(user_input, current_candidate_keys)

            #     # if email_intent['is_email_request']:
            #     #     # Handle email sending with extracted fields
            #     #     template_type = email_intent['template_type']
            #     #     candidate_key = email_intent['candidate_key']
            #     #     extracted_fields = email_intent.get('extracted_fields', {})
                    
            #     #     if not candidate_key:
            #     #         reply = f"❌ I understand you want to send an email, but I couldn't identify which candidate you're referring to. Available candidates in current results: {', '.join(current_candidate_keys)}"
            #     #     elif not template_type:
            #     #         reply = f"❌ I understand you want to send an email to {candidate_key}, but I couldn't determine what type of email. Available types: offer, rejection, interview."
            #     #     else:
            #     #         # Show what fields were extracted
            #     #         extracted_info = []
            #     #         for field, value in extracted_fields.items():
            #     #             if value:
            #     #                 extracted_info.append(f"{field}: {value}")
                        
            #     #         if extracted_info:
            #     #             st.info(f"📋 **Extracted Information:** {', '.join(extracted_info)}")
                        
            #     #         with st.spinner(f"📧 Sending {template_type.replace('_', ' ')} to {candidate_key}..."):
            #     #             try:
            #     #                 # Use the new method with extracted fields
            #     #                 result = email_service.send_template_email_with_fields(
            #     #                     candidate_key, 
            #     #                     template_type, 
            #     #                     extracted_fields
            #     #                 )
                                
            #     #                 if result['success']:
            #     #                     reply = f"✅ {result['message']}\n\n**Subject:** {result['subject']}\n\n**Email Preview:**\n{result['body'][:300]}..."
            #     #                 else:
            #     #                     reply = f"❌ Failed to send email: {result['error']}"
                                    
            #     #             except Exception as e:
            #     #                 reply = f"❌ Error sending email: {str(e)}"
            #     if email_intent['is_email_request']:
            #         # Handle email sending with extracted fields
            #         template_type = email_intent['template_type']
            #         candidate_key = email_intent['candidate_key']
            #         extracted_fields = email_intent.get('extracted_fields', {})
                    
            #         if not candidate_key:
            #             reply = f"❌ I understand you want to send an email, but I couldn't identify which candidate you're referring to. Available candidates in current results: {', '.join(current_candidate_keys)}"
            #         elif not template_type:
            #             reply = f"❌ I understand you want to send an email to {candidate_key}, but I couldn't determine what type of email. Available types: offer, rejection, interview."
            #         else:
            #             # Extract fields from the detected email intent
            #             extracted_fields = email_intent['extracted_fields']
                        
            #             # Check if this is a confirmation response
            #             if st.session_state.get('pending_email'):
            #                 confirmation_words = ['send', 'yes', 'confirm', 'ok', 'proceed', 'go ahead']
            #                 cancel_words = ['cancel', 'no', 'stop', 'abort', 'don\'t send']
                            
            #                 user_response = user_input.lower().strip()
                            
            #                 if any(word in user_response for word in confirmation_words):
            #                     # User confirmed - send the email
            #                     pending = st.session_state.pending_email
                                
            #                     with st.spinner(f"📧 Sending {pending['template_type'].replace('_', ' ')} to {pending['candidate_key']}..."):
            #                         try:
            #                             result = email_service.send_template_email_with_fields(
            #                                 pending['candidate_key'], 
            #                                 pending['template_type'], 
            #                                 pending['extracted_fields'],
            #                                 preview_only=False  # Actually send this time
            #                             )

            #                             if result['success']:
            #                                 reply = f"✅ {result['message']}"
                                            
            #                                 # Show final confirmation
            #                                 with st.expander("📧 Email Sent Details"):
            #                                     st.write(f"**To:** {pending['recipient_email']}")
            #                                     st.write(f"**Subject:** {result['subject']}")
            #                                     st.text_area("Email Body:", result['body'], height=200)
            #                             else:
            #                                 reply = f"❌ {result['error']}"
                                            
            #                         except Exception as e:
            #                             reply = f"❌ Error sending email: {str(e)}"
                                
            #                     # Clear pending email
            #                     del st.session_state.pending_email
                                
            #                 elif any(word in user_response for word in cancel_words):
            #                     # User cancelled
            #                     reply = "📧 Email sending cancelled."
            #                     del st.session_state.pending_email
                                
            #                 else:
            #                     # Invalid response
            #                     reply = "Please reply with 'send', 'yes', 'confirm' to send the email, or 'cancel', 'no' to abort."
                                
            #             else:
            #                 # First time - show preview
            #                 with st.spinner(f"📧 Preparing {template_type.replace('_', ' ')} for {candidate_key}..."):
            #                     try:
            #                         result = email_service.send_template_email_with_fields(
            #                             candidate_key, 
            #                             template_type, 
            #                             extracted_fields,
            #                             preview_only=True  # Preview mode
            #                         )

            #                         if result['success'] and result.get('preview_mode'):
            #                             # Show email preview
            #                             reply = "📧 Email Preview - Please review before sending:"
                                        
            #                             col1, col2 = st.columns([3, 1])
            #                             with col1:
            #                                 st.write(f"**To:** {result['recipient_email']}")
            #                                 st.write(f"**Subject:** {result['subject']}")
            #                             with col2:
            #                                 st.write(f"**Template:** {template_type}")
                                        
            #                             # Show email body in expandable section
            #                             with st.expander("📧 Full Email Preview", expanded=True):
            #                                 st.text_area("Email Body:", result['body'], height=300)
                                        
            #                             # Store pending email in session state
            #                             st.session_state.pending_email = {
            #                                 'candidate_key': candidate_key,
            #                                 'template_type': template_type,
            #                                 'extracted_fields': extracted_fields,
            #                                 'recipient_email': result['recipient_email']
            #                             }
                                        
            #                             # Show confirmation prompt
            #                             reply += "\n\n⚠️ **Confirmation Required:** Reply with 'send', 'yes', or 'confirm' to send this email, or 'cancel' to abort."
                                        
            #                         else:
            #                             reply = f"❌ {result.get('error', 'Failed to prepare email preview')}"
                                        
            #                     except Exception as e:
            #                         reply = f"❌ Error preparing email: {str(e)}"

            #     else:
            #         # Handle regular chat
            #         # Show processing indicator
            #         with st.spinner("🤔 Analyzing your question..."):
            #             try:
            #                 # Use the intelligent chat function
            #                 result = chat_with_resumes(
            #                     user_query=user_input,
            #                     candidate_keys=candidate_keys,
            #                     context_limit=3
            #                 )
                            
            #                 # Get the response
            #                 reply = result["answer"]
            #                 query_type = result["query_type"]
            #                 skills_extracted = result.get("skills_extracted", [])
            #                 candidates_analyzed = result.get("candidates_analyzed", [])
                            
            #                 # Add metadata to the response for transparency
            #                 if query_type == "skill_matching" and skills_extracted:
            #                     reply += f"\n\n*🔍 Skills identified: {', '.join(skills_extracted)}*"
                            
            #                 if candidates_analyzed:
            #                     reply += f"\n\n*👥 Candidates analyzed: {', '.join(candidates_analyzed)}*"
                            
            #                 print("----------------------------------------------------")
            #                 print(f"Chat response - Query type: {query_type}")
            #                 print(f"Skills extracted: {skills_extracted}")
            #                 print(f"Candidates analyzed: {candidates_analyzed}")
            #                 print("----------------------------------------------------")
                            
            #             except Exception as e:
            #                 reply = f"❌ I encountered an error while processing your question: {str(e)}"
            #                 print("----------------------------------------------------")
            #                 print(f"Chat error: {e}")
            #                 print("----------------------------------------------------")
                
            #     # Add assistant response to history and display
            #     st.session_state[chat_key].append({"role":"assistant","content":reply})
            #     st.chat_message("assistant").write(reply)
        
       # Show helpful examples
with st.expander("💡 Example questions you can ask"):
    st.markdown("""
    **Skill-based queries:**
    - "Find candidates with Python and machine learning experience"
    - "Who has React and Node.js skills?"
    - "Which candidates know cloud computing?"
    
    **Candidate-specific queries:**
    - "What's Leon's educational background?"
    - "Tell me about Xiang's work experience"
    - "What projects has DIAN worked on?"
    
    **Email commands:**
    
    **Job Offers:**
    - "Send offer email to mingyang for software engineer position, starting January 15th, salary $2000/month, 6 months"
    - "Email offer to john for data analyst role, beginning February 1st, salary 2500, 4 months"
    - "Offer alice the UI/UX designer position, start Monday, $1800/month, 3 months"
    - "Send offer to bob for summer internship, starting June 1st, salary $1500/month"
    
    ***Special Program Offers (ATAP & SIP):***
    - "Send offer to lisa for ATAP program, starting March 1st, salary $2500/month"
    - "Email offer to mike for SIP program, salary 1800, start May 12th"
    
    **Interview Invitations:**
    - "Invite Sarah for interview tomorrow at 2pm via Zoom, 45 minutes"
    - "Send interview email to Mike for January 20th at 10am, in-person, 1 hour"
    - "Schedule interview with Lisa next Monday 3pm, online meeting, 30 minutes"
    
    **Job Rejection emails:**
    - "Send rejection letter to Alice"
    - "Reject Bob via email"
    """)