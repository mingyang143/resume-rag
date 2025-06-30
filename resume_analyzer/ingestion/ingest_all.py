import os
import glob
import shutil
import tempfile
import concurrent.futures
from typing import Optional, List, Callable
import traceback

from .ingest_pg import ingest_all_resumes   # your existing script
from .ingest_normal import ingest_resume_normal  # your existing script


def process_candidate(
    root_folder: str,
    person: str
) -> List[str]:
    """
    Processes one candidate folder:
      - copies 'mikomiko' files into a temp dir → ingest_all_resumes
      - copies other resumes into a temp dir → ingest_resume_normal
    Returns a list of summary strings for that candidate.
    """
    summary_logs: List[str] = []
    person_dir = os.path.join(root_folder, person)
    if not os.path.isdir(person_dir):
        return summary_logs

    # gather all PDF/DOCX in this candidate folder
    files = [
        os.path.join(person_dir, f)
        for f in os.listdir(person_dir)
        if f.lower().endswith((".pdf", ".docx"))
    ]
    if not files:
        print(f"[{person}] no resume files found, skipping")
        return summary_logs

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

    return summary_logs

def ingest_all_candidates(
    root_folder: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    max_workers: int = 8
) -> List[str]:
    if not os.path.isdir(root_folder):
        raise ValueError(f"{root_folder!r} is not a directory")

    candidates = [d for d in os.listdir(root_folder)
                  if os.path.isdir(os.path.join(root_folder, d))]
    total = len(candidates)
    if total == 0:
        return ["⚠️ No candidates found in the folder."]

    summary_logs: List[str] = []
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_candidate, root_folder, person): person
            for person in candidates
        }

        for future in concurrent.futures.as_completed(futures):
            person = futures[future]
            try:
                summary_logs.extend(future.result())
            except Exception as e:
                # your existing error logging…
                print(f"❌ {person} failed: {type(e).__name__}: {e!r}")
            finally:
                completed += 1
                if progress_callback:
                    # called on the main thread, safe to do st.progress()
                    progress_callback(completed, total, person)

    return summary_logs

if __name__ == "__main__":
    folder_path = "/path/to/your/resumes_root"
    # you can also pass a callback or increase max_workers if desired
    logs = ingest_all_candidates(folder_path, max_workers=10)
    print("Ingestion complete. Summary:")
    for log in logs:
        print(" -", log)
