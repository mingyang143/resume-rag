import psycopg2
from datetime import datetime
from typing import Optional, Dict, Any
import json

class ProgressTracker:
    def __init__(self, conn):
        self.conn = conn
        self.ensure_table_exists()
    
    def ensure_table_exists(self):
        """Create progress tracking table if it doesn't exist"""
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_progress (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(255) UNIQUE,
                status VARCHAR(50),
                total_files INTEGER,
                processed_files INTEGER,
                current_file VARCHAR(255),
                started_at TIMESTAMP,
                updated_at TIMESTAMP,
                metadata JSONB,
                errors TEXT[]
            )
        """)
        self.conn.commit()
        cur.close()
    
    # Update the start_ingestion method:

    def start_ingestion(self, session_id: str, total_files: int, metadata: Dict[str, Any] = None):
        """Start tracking a new ingestion session"""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO ingestion_progress 
            (session_id, status, total_files, processed_files, current_file, started_at, updated_at, metadata, errors)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE SET
                status = EXCLUDED.status,
                total_files = EXCLUDED.total_files,
                processed_files = EXCLUDED.processed_files,
                started_at = EXCLUDED.started_at,
                updated_at = EXCLUDED.updated_at,
                metadata = EXCLUDED.metadata,
                errors = EXCLUDED.errors
        """, (
            session_id, 
            "RUNNING", 
            total_files, 
            0, 
            None, 
            datetime.now(), 
            datetime.now(), 
            json.dumps(metadata) if metadata else json.dumps({}),  # Always convert to JSON string
            []
        ))
        self.conn.commit()
        cur.close()

    # And update the get_progress method:
    def get_progress(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get current progress for a session"""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT session_id, status, total_files, processed_files, current_file, 
                started_at, updated_at, metadata, errors
            FROM ingestion_progress 
            WHERE session_id = %s
        """, (session_id,))
        
        row = cur.fetchone()
        cur.close()
        
        if row:
            return {
                "session_id": row[0],
                "status": row[1],
                "total_files": row[2],
                "processed_files": row[3],
                "current_file": row[4],
                "started_at": row[5],
                "updated_at": row[6],
                "metadata": json.loads(row[7]) if row[7] and isinstance(row[7], str) else (row[7] if row[7] else {}),
                "errors": row[8] or []
            }
        return None

    # And update get_all_active_sessions:
    def get_all_active_sessions(self):
        """Get all active ingestion sessions"""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT session_id, status, total_files, processed_files, current_file, 
                started_at, updated_at, metadata, errors
            FROM ingestion_progress 
            WHERE status = 'RUNNING'
            ORDER BY started_at DESC
        """)
        
        rows = cur.fetchall()
        cur.close()
        
        sessions = []
        for row in rows:
            sessions.append({
                "session_id": row[0],
                "status": row[1],
                "total_files": row[2],
                "processed_files": row[3],
                "current_file": row[4],
                "started_at": row[5],
                "updated_at": row[6],
                "metadata": json.loads(row[7]) if row[7] and isinstance(row[7], str) else (row[7] if row[7] else {}),
                "errors": row[8] or []
            })
        
        return sessions
    
    def update_progress(self, session_id: str, processed_files: int, current_file: str = None, error: str = None):
        """Update progress for a session"""
        cur = self.conn.cursor()
        
        if error:
            cur.execute("""
                UPDATE ingestion_progress 
                SET processed_files = %s, current_file = %s, updated_at = %s, errors = array_append(errors, %s)
                WHERE session_id = %s
            """, (processed_files, current_file, datetime.now(), error, session_id))
        else:
            cur.execute("""
                UPDATE ingestion_progress 
                SET processed_files = %s, current_file = %s, updated_at = %s
                WHERE session_id = %s
            """, (processed_files, current_file, datetime.now(), session_id))
        
        self.conn.commit()
        cur.close()
    
    def finish_ingestion(self, session_id: str, status: str = "COMPLETED"):
        """Mark ingestion as finished"""
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE ingestion_progress 
            SET status = %s, updated_at = %s
            WHERE session_id = %s
        """, (status, datetime.now(), session_id))
        self.conn.commit()
        cur.close()
    
    
    
    