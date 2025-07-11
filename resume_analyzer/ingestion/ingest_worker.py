import os
import sys
import time
import traceback
from typing import Optional, List

from .ingest_all import ingest_all_candidates_with_progress
from .helpers import load_env_vars, connect_postgres

def run_ingestion_worker(root_folder: str, session_id: str, max_workers: int = 4) -> None:
    """
    Standalone worker function that runs in a separate process.
    This will continue running even if the Streamlit UI refreshes or navigates away.
    """
    print(f"🚀 Worker process started for session {session_id}")
    print(f"📂 Processing folder: {root_folder}")
    print(f"🧵 Using {max_workers} worker threads")
    
    try:
        # Run the ingestion without a UI callback (database updates only)
        summary_logs, completed_session_id = ingest_all_candidates_with_progress(
            root_folder, 
            progress_callback=None,  # No UI callback since we're in a different process
            max_workers=max_workers,
            session_id=session_id
        )
        
        print(f"✅ Worker process completed successfully for session {session_id}")
        print(f"📋 Processed {len(summary_logs)} items")
        
    except Exception as e:
        print(f"❌ Worker process failed for session {session_id}: {e}")
        traceback.print_exc()