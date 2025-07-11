# import os
# import glob
# import shutil
# import tempfile
# import concurrent.futures
# from typing import Optional, List, Callable
# import traceback

# from .ingest_pg import ingest_all_resumes   # your existing script
# from .ingest_normal import ingest_resume_normal  # your existing script


# def process_candidate(
#     root_folder: str,
#     person: str
# ) -> List[str]:
#     """
#     Processes one candidate folder:
#       - copies 'mikomiko' files into a temp dir → ingest_all_resumes
#       - copies other resumes into a temp dir → ingest_resume_normal
#     Returns a list of summary strings for that candidate.
#     """
#     summary_logs: List[str] = []
#     person_dir = os.path.join(root_folder, person)
#     if not os.path.isdir(person_dir):
#         return summary_logs

#     # gather all PDF/DOCX in this candidate folder
#     files = [
#         os.path.join(person_dir, f)
#         for f in os.listdir(person_dir)
#         if f.lower().endswith((".pdf", ".docx"))
#     ]
#     if not files:
#         print(f"[{person}] no resume files found, skipping")
#         return summary_logs

#     # split mikomiko vs normal
#     mik = [f for f in files if "mikomiko" in os.path.basename(f).lower()]
#     normal = [f for f in files if "mikomiko" not in os.path.basename(f).lower()]

#     # 1) ingest metadata PDF(s)
#     if mik:
#         with tempfile.TemporaryDirectory() as td:
#             for src in mik:
#                 shutil.copy(src, td)
#             print(f"[{person}] ingesting metadata resume(s): {[os.path.basename(f) for f in mik]}")
#             summary = ingest_all_resumes(td, person)
#             summary_logs.append(summary[0])
#     else:
#         print(f"[{person}] WARNING: no 'mikomiko' file found")

#     # 2) ingest normal PDF(s)
#     if normal:
#         with tempfile.TemporaryDirectory() as td:
#             for src in normal:
#                 shutil.copy(src, td)
#             print(f"[{person}] ingesting normal resume(s): {[os.path.basename(f) for f in normal]}")
#             summary = ingest_resume_normal(td, person)
#             summary_logs.append(summary[0])
#     else:
#         print(f"[{person}] WARNING: no normal resume file found")

#     return summary_logs

# def ingest_all_candidates(
#     root_folder: str,
#     progress_callback: Optional[Callable[[int, int, str], None]] = None,
#     max_workers: int = 8
# ) -> List[str]:
#     if not os.path.isdir(root_folder):
#         raise ValueError(f"{root_folder!r} is not a directory")

#     candidates = [d for d in os.listdir(root_folder)
#                   if os.path.isdir(os.path.join(root_folder, d))]
#     total = len(candidates)
#     if total == 0:
#         return ["⚠️ No candidates found in the folder."]

#     summary_logs: List[str] = []
#     completed = 0

#     with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
#         futures = {
#             executor.submit(process_candidate, root_folder, person): person
#             for person in candidates
#         }

#         for future in concurrent.futures.as_completed(futures):
#             person = futures[future]
#             try:
#                 summary_logs.extend(future.result())
#             except Exception as e:
#                 # your existing error logging…
#                 print(f"❌ {person} failed: {type(e).__name__}: {e!r}")
#             finally:
#                 completed += 1
#                 if progress_callback:
#                     # called on the main thread, safe to do st.progress()
#                     progress_callback(completed, total, person)

#     return summary_logs

# if __name__ == "__main__":
#     folder_path = "/path/to/your/resumes_root"
#     # you can also pass a callback or increase max_workers if desired
#     logs = ingest_all_candidates(folder_path, max_workers=10)
#     print("Ingestion complete. Summary:")
#     for log in logs:
#         print(" -", log)


import os
import glob
import shutil
import tempfile
import concurrent.futures
from typing import Optional, List, Callable
import traceback
import uuid
import psycopg2
from datetime import datetime

from .ingest_pg import ingest_all_resumes   
from .ingest_normal import ingest_resume_normal  

# ADD THESE IMPORTS
from .helpers import load_env_vars, connect_postgres
from ..backend.progress_tracker import ProgressTracker

def process_candidate(root_folder: str, person: str) -> List[str]:
    """Process one candidate folder (unchanged)"""
    print(f"🔍 DEBUG: process_candidate started for {person}")
    
    summary_logs: List[str] = []
    person_dir = os.path.join(root_folder, person)
    if not os.path.isdir(person_dir):
        print(f"🔍 DEBUG: {person} directory does not exist")
        return summary_logs

    files = [
        os.path.join(person_dir, f)
        for f in os.listdir(person_dir)
        if f.lower().endswith((".pdf", ".docx"))
    ]
    
    if not files:
        print(f"🔍 DEBUG: No files found for {person}")
        return summary_logs

    print(f"🔍 DEBUG: Found {len(files)} files for {person}: {[os.path.basename(f) for f in files]}")

    mik = [f for f in files if "mikomiko" in os.path.basename(f).lower()]
    normal = [f for f in files if "mikomiko" not in os.path.basename(f).lower()]
    
    print(f"🔍 DEBUG: {person} - mikomiko files: {len(mik)}, normal files: {len(normal)}")

    if mik:
        print(f"🔍 DEBUG: Processing mikomiko files for {person}")
        with tempfile.TemporaryDirectory() as td:
            for src in mik:
                shutil.copy(src, td)
            print(f"[{person}] ingesting metadata resume(s): {[os.path.basename(f) for f in mik]}")
            try:
                summary = ingest_all_resumes(td, person)
                summary_logs.extend(summary)
                print(f"🔍 DEBUG: ingest_all_resumes succeeded for {person}")
            except Exception as e:
                print(f"🔍 DEBUG: ingest_all_resumes failed for {person}: {e}")
                raise

    if normal:
        print(f"🔍 DEBUG: Processing normal files for {person}")
        with tempfile.TemporaryDirectory() as td:
            for src in normal:
                shutil.copy(src, td)
            print(f"[{person}] ingesting normal resume(s): {[os.path.basename(f) for f in normal]}")
            try:
                summary = ingest_resume_normal(td, person)
                summary_logs.extend(summary)
                print(f"🔍 DEBUG: ingest_resume_normal succeeded for {person}")
            except Exception as e:
                print(f"🔍 DEBUG: ingest_resume_normal failed for {person}: {e}")
                raise

    print(f"🔍 DEBUG: process_candidate completed for {person}, returning {len(summary_logs)} summary logs")
    return summary_logs

def ingest_all_candidates_with_progress(
    root_folder: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    max_workers: int = 4,
    session_id: Optional[str] = None
) -> tuple[List[str], str]:
    """Enhanced version with database progress tracking that persists across UI refreshes."""
    
    if not os.path.isdir(root_folder):
        raise ValueError(f"{root_folder!r} is not a directory")

    if session_id is None:
        session_id = str(uuid.uuid4())

    candidates = [d for d in os.listdir(root_folder)
                  if os.path.isdir(os.path.join(root_folder, d))]
    total = len(candidates)
    
    if total == 0:
        return ["⚠️ No candidates found in the folder."], session_id

    print(f"🚀 Starting ingestion of {total} candidates with session {session_id[:8]}...")

    # Initialize session ONCE at the start
    try:
        env = load_env_vars()
        init_conn = connect_postgres(env)
        init_tracker = ProgressTracker(init_conn)
        
        metadata = {
            "source": "batch_ingestion",
            "root_folder": root_folder,
            "total_candidates": total
        }
        init_tracker.start_ingestion(session_id, total, metadata)
        print(f"✅ Started tracking session {session_id}")
        
        init_conn.close()  # Close immediately after initialization
        
    except Exception as e:
        print(f"⚠️ Failed to initialize progress tracking: {e}")

    summary_logs: List[str] = []
    completed = 0

    # Define callback for UI updates
    def enhanced_progress_callback(idx: int, total: int, filename: str):
        print(f"📊 Progress callback: {idx}/{total} - {filename}")
        
        # Create FRESH database connection for each update
        try:
            env = load_env_vars()
            fresh_conn = connect_postgres(env)
            fresh_tracker = ProgressTracker(fresh_conn)
            
            fresh_tracker.update_progress(
                session_id, 
                idx, 
                f"Completed {filename}",
                None
            )
            
            fresh_conn.close()  # Always close after use
            print(f"✅ Database updated: {idx}/{total}")
            
        except Exception as e:
            print(f"⚠️ Failed to update database progress: {e}")
        
        # Call UI callback safely (might fail if user navigated away)
        if progress_callback:
            try:
                progress_callback(idx, total, filename)
                print(f"✅ UI updated: {idx}/{total}")
            except Exception as e:
                print(f"⚠️ UI callback failed (page may have been refreshed): {e}")
    # Run the actual ingestion
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_candidate, root_folder, person): person
                for person in candidates
            }

            for future in concurrent.futures.as_completed(futures):
                person = futures[future]
                try:
                    candidate_summary = future.result()
                    summary_logs.extend(candidate_summary)
                    print(f"✅ Successfully processed {person}")
                    
                except Exception as e:
                    error_msg = f"{person} failed: {type(e).__name__}: {e!r}"
                    print(f"❌ {error_msg}")
                    summary_logs.append(f"❌ {error_msg}")
                    
                    # Update database with error using fresh connection
                    try:
                        env = load_env_vars()
                        error_conn = connect_postgres(env)
                        error_tracker = ProgressTracker(error_conn)
                        error_tracker.update_progress(session_id, completed + 1, person, error_msg)
                        error_conn.close()
                    except Exception as db_err:
                        print(f"⚠️ Failed to log error to database: {db_err}")
                    
                    traceback.print_exc()
                
                # Always increment and update progress
                completed += 1
                enhanced_progress_callback(completed, total, person)

        # Mark session as completed using fresh connection
        try:
            env = load_env_vars()
            final_conn = connect_postgres(env)
            final_tracker = ProgressTracker(final_conn)
            final_tracker.finish_ingestion(session_id, "COMPLETED")
            final_conn.close()
            print(f"✅ Session {session_id} marked as COMPLETED")
        except Exception as e:
            print(f"⚠️ Failed to mark session as completed: {e}")
        
        return summary_logs, session_id

    except Exception as e:
        # Mark session as failed using fresh connection
        try:
            env = load_env_vars()
            fail_conn = connect_postgres(env)
            fail_tracker = ProgressTracker(fail_conn)
            fail_tracker.finish_ingestion(session_id, "FAILED")
            fail_conn.close()
            print(f"❌ Session {session_id} marked as FAILED")
        except:
            pass
        raise e

def ingest_all_candidates_with_progress_stoppable(
    root_folder: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    max_workers: int = 4,
    session_id: Optional[str] = None,
    stop_check_callback: Optional[Callable[[], bool]] = None
) -> tuple[List[str], str]:
    """
    Enhanced version with graceful stopping capability.
    Checks for stop signals between candidate processing.
    """
    
    def process_candidate_with_stop_check(candidate_data):
        """Process a single candidate with stop signal checking"""
        root_folder, person, candidate_idx, total_candidates = candidate_data
        
        # Check for stop signal BEFORE processing candidate
        if stop_check_callback and stop_check_callback():
            print(f"🛑 Stop signal received, skipping {person}")
            return f"⏭️ Skipped {person} due to stop signal"
        
        try:
            print(f"📁 Starting candidate {candidate_idx + 1}/{total_candidates}: {person}")
            
            # Use your existing process_candidate function
            candidate_summary = process_candidate(root_folder, person)
            
            # Check for stop signal AFTER processing
            if stop_check_callback and stop_check_callback():
                print(f"🛑 Stop signal received after processing {person}")
                # Clean up any partial data for this candidate if needed
                cleanup_partial_candidate(person)
                return f"✅ Completed {person} but stopping after this"
            
            print(f"✅ Completed candidate {candidate_idx + 1}/{total_candidates}: {person}")
            return candidate_summary
            
        except Exception as e:
            error_msg = f"❌ Failed to process {person}: {e}"
            print(error_msg)
            # Clean up any partial data on error
            cleanup_partial_candidate(person)
            return [error_msg]

    def cleanup_partial_candidate(candidate_key: str):
        """Remove partial data for a candidate"""
        try:
            env = load_env_vars()
            conn = connect_postgres(env)
            cur = conn.cursor()
            
            # Remove from both tables
            cur.execute("DELETE FROM resumes_metadata WHERE candidate_key = %s", (candidate_key,))
            cur.execute("DELETE FROM resumes_normal WHERE candidate_key = %s", (candidate_key,))
            
            conn.commit()
            cur.close()
            conn.close()
            
            print(f"🧹 Cleaned up partial data for {candidate_key}")
        except Exception as e:
            print(f"❌ Failed to cleanup {candidate_key}: {e}")

    # Main function logic (similar to your existing function)
    if not os.path.isdir(root_folder):
        raise ValueError(f"{root_folder!r} is not a directory")

    if session_id is None:
        session_id = str(uuid.uuid4())

    candidates = [d for d in os.listdir(root_folder)
                  if os.path.isdir(os.path.join(root_folder, d))]
    total = len(candidates)
    
    if total == 0:
        return ["⚠️ No candidates found in the folder."], session_id

    print(f"🚀 Starting stoppable ingestion of {total} candidates with session {session_id[:8]}...")

    # Initialize session ONCE at the start
    try:
        env = load_env_vars()
        init_conn = connect_postgres(env)
        init_tracker = ProgressTracker(init_conn)
        
        metadata = {
            "source": "batch_ingestion_stoppable",
            "root_folder": root_folder,
            "total_candidates": total
        }
        init_tracker.start_ingestion(session_id, total, metadata)
        print(f"✅ Started tracking session {session_id}")
        
        init_conn.close()
        
    except Exception as e:
        print(f"⚠️ Failed to initialize progress tracking: {e}")

    summary_logs: List[str] = []
    completed = 0

    # Enhanced progress callback with stop checking
    def enhanced_progress_callback(idx: int, total: int, filename: str):
        print(f"📊 Progress callback: {idx}/{total} - {filename}")
        
        # Update database progress
        try:
            env = load_env_vars()
            fresh_conn = connect_postgres(env)
            fresh_tracker = ProgressTracker(fresh_conn)
            
            # Check if we should stop before updating
            if stop_check_callback and stop_check_callback():
                fresh_tracker.update_progress(session_id, idx, f"Stopping after {filename}", None)
            else:
                fresh_tracker.update_progress(session_id, idx, f"Completed {filename}", None)
            
            fresh_conn.close()
            print(f"✅ Database updated: {idx}/{total}")
            
        except Exception as e:
            print(f"⚠️ Failed to update database progress: {e}")
        
        # Call UI callback safely
        if progress_callback:
            try:
                progress_callback(idx, total, filename)
                print(f"✅ UI updated: {idx}/{total}")
            except Exception as e:
                print(f"⚠️ UI callback failed: {e}")

    # Main processing loop with ThreadPoolExecutor and stop checking
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Prepare candidate data
            candidate_data = [(root_folder, candidates[i], i, total) for i in range(total)]
            
            # Submit all tasks
            future_to_candidate = {
                executor.submit(process_candidate_with_stop_check, data): data[1] 
                for data in candidate_data
            }
            
            for future in concurrent.futures.as_completed(future_to_candidate):
                # Check for stop signal before processing results
                if stop_check_callback and stop_check_callback():
                    print("🛑 Stop signal received, cancelling remaining tasks")
                    
                    # Cancel remaining futures
                    for remaining_future in future_to_candidate:
                        if not remaining_future.done():
                            remaining_future.cancel()
            
                    print(f"🛑 Graceful stop completed - status remains ARCHIVED")
                    
                    summary_logs.append(f"🛑 Ingestion stopped gracefully after {completed}/{total} candidates")
                    return summary_logs, session_id
                
                # Process completed future
                person = future_to_candidate[future]
                
                try:
                    result = future.result()
                    
                    # Handle different return types from process_candidate_with_stop_check
                    if isinstance(result, list):
                        summary_logs.extend(result)
                    elif isinstance(result, str):
                        summary_logs.append(result)
                    
                    print(f"✅ Successfully processed {person}")
                    
                except Exception as e:
                    error_msg = f"{person} failed: {type(e).__name__}: {e!r}"
                    print(f"❌ {error_msg}")
                    summary_logs.append(f"❌ {error_msg}")
                    
                    # Update database with error using fresh connection
                    try:
                        env = load_env_vars()
                        error_conn = connect_postgres(env)
                        error_tracker = ProgressTracker(error_conn)
                        error_tracker.update_progress(session_id, completed + 1, person, error_msg)
                        error_conn.close()
                    except Exception as db_err:
                        print(f"⚠️ Failed to log error to database: {db_err}")
                    
                    traceback.print_exc()
                
                # Always increment and update progress
                completed += 1
                enhanced_progress_callback(completed, total, person)

        # Mark session as completed (if not stopped)
        if not (stop_check_callback and stop_check_callback()):
            try:
                env = load_env_vars()
                final_conn = connect_postgres(env)
                final_tracker = ProgressTracker(final_conn)
                final_tracker.finish_ingestion(session_id, "COMPLETED")
                final_conn.close()
                print(f"✅ Session {session_id} marked as COMPLETED")
            except Exception as e:
                print(f"⚠️ Failed to mark session as completed: {e}")
        
        return summary_logs, session_id

    except Exception as e:
        # Mark session as failed
        try:
            env = load_env_vars()
            fail_conn = connect_postgres(env)
            fail_tracker = ProgressTracker(fail_conn)
            fail_tracker.finish_ingestion(session_id, "FAILED")
            fail_conn.close()
            print(f"❌ Session {session_id} marked as FAILED")
        except:
            pass
        raise e

# Keep the original function for backward compatibility
def ingest_all_candidates(
    root_folder: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    max_workers: int = 8
) -> List[str]:
    """Original function - now calls the enhanced version"""
    summary_logs, _ = ingest_all_candidates_with_progress(
        root_folder, progress_callback, max_workers
    )
    return summary_logs

if __name__ == "__main__":
    folder_path = "/path/to/your/resumes_root"
    logs = ingest_all_candidates(folder_path, max_workers=10)
    print("Ingestion complete. Summary:")
    for log in logs:
        print(" -", log)