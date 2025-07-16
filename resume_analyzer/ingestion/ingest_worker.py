# import os
# import sys
# import time
# import traceback
# import json
# from datetime import datetime
# from typing import Optional, List

# from .ingest_all import ingest_all_candidates_with_progress
# from .helpers import load_env_vars, connect_postgres

# def run_ingestion_worker(root_folder: str, session_id: str, max_workers: int = 4) -> None:
#     """
#     Standalone worker function that runs in a separate process.
#     Creates detailed log files for troubleshooting.
#     """
#     print(f"🚀 Worker process started for session {session_id}")
#     print(f"📂 Processing folder: {root_folder}")
#     print(f"🧵 Using {max_workers} worker threads")
    
#     # Create logs directory
#     logs_dir = os.path.join(os.path.dirname(root_folder), "ingestion_logs")
#     os.makedirs(logs_dir, exist_ok=True)
    
#     # Create detailed log file
#     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#     log_file = os.path.join(logs_dir, f"ingestion_log_{session_id[:8]}_{timestamp}.txt")
    
#     def log_to_file(message: str):
#         """Helper to write to both console and log file"""
#         print(message)
#         with open(log_file, "a", encoding="utf-8") as f:
#             f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
    
#     log_to_file("=" * 80)
#     log_to_file(f"INGESTION SESSION: {session_id}")
#     log_to_file(f"ROOT FOLDER: {root_folder}")
#     log_to_file(f"MAX WORKERS: {max_workers}")
#     log_to_file(f"LOG FILE: {log_file}")
#     log_to_file("=" * 80)
    
#     try:
#         # Run the ingestion with enhanced logging
#         summary_logs, completed_session_id = ingest_all_candidates_with_progress(
#             root_folder, 
#             progress_callback=None,
#             max_workers=max_workers,
#             session_id=session_id
#         )
        
#         log_to_file("\n" + "=" * 50)
#         log_to_file("INGESTION SUMMARY")
#         log_to_file("=" * 50)
        
#         for log in summary_logs:
#             log_to_file(log)
        
#         # Store summary in database
#         env = load_env_vars()
#         conn = connect_postgres(env)
#         cur = conn.cursor()
        
#         # Store both logs and log file path in database
#         cur.execute("""
#             UPDATE ingestion_progress 
#             SET metadata = jsonb_set(
#                 COALESCE(metadata, '{}'::jsonb), 
#                 '{summary_logs}', 
#                 %s::jsonb
#             )
#             WHERE session_id = %s
#         """, (json.dumps(summary_logs), session_id))
        
#         # Also store log file path
#         cur.execute("""
#             UPDATE ingestion_progress 
#             SET metadata = jsonb_set(
#                 metadata, 
#                 '{log_file_path}', 
#                 %s::jsonb
#             )
#             WHERE session_id = %s
#         """, (json.dumps(log_file), session_id))
        
#         conn.commit()
#         cur.close()
#         conn.close()
        
#         log_to_file(f"\n✅ Worker process completed successfully for session {session_id}")
#         log_to_file(f"📋 Processed {len(summary_logs)} items")
#         log_to_file(f"📄 Detailed log saved to: {log_file}")
        
#     except Exception as e:
#         error_msg = f"❌ Worker process failed for session {session_id}: {e}"
#         log_to_file(error_msg)
#         log_to_file(traceback.format_exc())
#         raise e


import os
import sys
import time
import traceback
import json
from datetime import datetime
from typing import Optional, List

from .ingest_all import ingest_all_candidates_with_progress_stoppable  # CHANGED: Use stoppable version
from .helpers import load_env_vars, connect_postgres

def run_ingestion_worker(root_folder: str, session_id: str, max_workers: int = 4) -> None:
    """
    Standalone worker function that runs in a separate process.
    Creates detailed log files for troubleshooting.
    Now supports graceful stopping via database status checks.
    """
    print(f"🚀 Worker process started for session {session_id}")
    print(f"📂 Processing folder: {root_folder}")
    print(f"🧵 Using {max_workers} worker threads")
    
    # Create logs directory
    logs_dir = os.path.join(os.path.dirname(root_folder), "ingestion_logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    # Create detailed log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(logs_dir, f"ingestion_log_{session_id[:8]}_{timestamp}.txt")
    
    def log_to_file(message: str):
        """Helper to write to both console and log file"""
        print(message)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
    
    # NEW: Add stop checking function
    def check_should_stop():
        """Check if we should stop based on database status"""
        try:
            env = load_env_vars()
            conn = connect_postgres(env)
            cur = conn.cursor()
            
            cur.execute("""
                SELECT status FROM ingestion_progress 
                WHERE session_id = %s
            """, (session_id,))
            
            result = cur.fetchone()
            cur.close()
            conn.close()
            
            if result and result[0] in ['ABANDONED', 'ARCHIVED']:
                log_to_file(f"🛑 Stop signal detected: status = {result[0]}")
                return True
            return False
            
        except Exception as e:
            log_to_file(f"⚠️ Error checking stop signal: {e}")
            return False
    
    log_to_file("=" * 80)
    log_to_file(f"INGESTION SESSION: {session_id}")
    log_to_file(f"ROOT FOLDER: {root_folder}")
    log_to_file(f"MAX WORKERS: {max_workers}")
    log_to_file(f"LOG FILE: {log_file}")
    log_to_file("=" * 80)
    
    try:
        # CHANGED: Use the enhanced stoppable version
        summary_logs, completed_session_id = ingest_all_candidates_with_progress_stoppable(
            root_folder, 
            progress_callback=None,
            max_workers=max_workers,
            session_id=session_id,
            stop_check_callback=check_should_stop  # NEW: Pass stop checker
        )
        
        # Check if we stopped gracefully
        if check_should_stop():
            log_to_file(f"🛑 Ingestion stopped gracefully for session {session_id}")
        else:
            log_to_file(f"✅ Ingestion completed successfully for session {session_id}")
        
        log_to_file("\n" + "=" * 50)
        log_to_file("INGESTION SUMMARY")
        log_to_file("=" * 50)
        
        for log in summary_logs:
            log_to_file(log)
        
        # Store summary in database
        env = load_env_vars()
        conn = connect_postgres(env)
        cur = conn.cursor()
        
        # Store both logs and log file path in database
        cur.execute("""
            UPDATE ingestion_progress 
            SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb), 
                '{summary_logs}', 
                %s::jsonb
            )
            WHERE session_id = %s
        """, (json.dumps(summary_logs), session_id))
        
        # Also store log file path
        cur.execute("""
            UPDATE ingestion_progress 
            SET metadata = jsonb_set(
                metadata, 
                '{log_file_path}', 
                %s::jsonb
            )
            WHERE session_id = %s
        """, (json.dumps(log_file), session_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        log_to_file(f"\n✅ Worker process completed for session {session_id}")
        log_to_file(f"📋 Processed {len(summary_logs)} items")
        log_to_file(f"📄 Detailed log saved to: {log_file}")
        
    except Exception as e:
        error_msg = f"❌ Worker process failed for session {session_id}: {e}"
        log_to_file(error_msg)
        log_to_file(traceback.format_exc())
        raise e