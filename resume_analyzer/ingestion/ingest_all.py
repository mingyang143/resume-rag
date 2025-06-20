import os
import glob
import shutil
import tempfile
from typing import Dict, Optional, List, Callable

from .ingest_pg import ingest_all_resumes  # your existing script
from .ingest_normal import ingest_resume_normal   # your existing script

def ingest_all_candidates(root_folder: str, progress_callback: Optional[Callable[[int, int, str], None]] = None):
    """
    Walk each sub‐directory under `root_folder`, and for each:
      - find the PDF whose filename contains "mikomiko" → run ingest_all_resumes on it
      - find the other PDF → run ingest_resume_normal on it
    """
    if not os.path.isdir(root_folder):
        raise ValueError(f"{root_folder!r} is not a directory")

    candidates = [
        name for name in os.listdir(root_folder)
        if os.path.isdir(os.path.join(root_folder, name))
    ]
    total = len(candidates)
    summary_logs: List[str] = []

    if total == 0:
        summary_logs.append("⚠️ No candidates found in the folder.")
        return summary_logs

    for idx, person in enumerate(candidates, start=1):
        person_dir = os.path.join(root_folder, person)
        if not os.path.isdir(person_dir):
            continue


        # gather all PDF/DOCX in this candidate folder
        files = [
            os.path.join(person_dir, f)
            for f in os.listdir(person_dir)
            if f.lower().endswith((".pdf", ".docx"))
        ]
        if not files:
            print(f"[{person}] no resume files found, skipping")
            continue

        # split mikomiko vs normal
        mik = [f for f in files if "mikomiko" in os.path.basename(f).lower()]
        normal = [f for f in files if "mikomiko" not in os.path.basename(f).lower()]

        # 1) ingest metadata PDF(s)
        if mik:
            with tempfile.TemporaryDirectory() as td:
                for src in mik:
                    shutil.copy(src, td)
                print(f"[{person}] ingesting metadata resume(s): {[os.path.basename(f) for f in mik]}")
                summary = ingest_all_resumes(td, person)
                summary_logs.append(summary[0])
        else:
            print(f"[{person}] WARNING: no 'mikomiko' file found")

        # 2) ingest normal PDF(s)
        if normal:
            with tempfile.TemporaryDirectory() as td:
                for src in normal:
                    shutil.copy(src, td)
                print(f"[{person}] ingesting normal resume(s): {[os.path.basename(f) for f in normal]}")
                summary = ingest_resume_normal(td, person)
                summary_logs.append(summary[0])
        else:
            print(f"[{person}] WARNING: no normal resume file found")

        if progress_callback:
            progress_callback(idx, total, person)

    return summary_logs


if __name__ == "__main__":
    folder_path = "/home/peseyes/Desktop/resumeRAG/resume_analyzer/resumes/resumes_tgt"
    ingest_all_candidates(folder_path)