import os
import sys
from pathlib import Path

# BASE_DIR: where the running code itself lives (the exe's own folder when
# frozen, the project root otherwise). Only used to locate bundled resources.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

# DATA_DIR: where the user's actual data lives (recordings, transcripts,
# summaries, the DB, schedule, .env). This must NOT be the exe's own folder --
# rebuilding/redistributing the exe (PyInstaller's --onedir COLLECT step, or
# just replacing the folder) wipes and recreates that folder from scratch,
# which previously destroyed real recordings during a routine rebuild. Windows'
# per-user AppData folder is the standard, rebuild-proof place for this.
if getattr(sys, "frozen", False):
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(BASE_DIR))) / "LectureNotes"
else:
    DATA_DIR = BASE_DIR

MODEL_DIR = DATA_DIR / "models"
# CUDA runtime DLLs, downloaded on demand rather than shipped in the exe.
CUDA_DIR = DATA_DIR / "cuda"
RECORDINGS_DIR = DATA_DIR / "recordings"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
SUMMARIES_DIR = DATA_DIR / "summaries"
DB_PATH = DATA_DIR / "lecture_notes.db"
SCHEDULE_PATH = DATA_DIR / "schedule.json"
ENV_PATH = DATA_DIR / ".env"


def ensure_dirs() -> None:
    """A fresh install (e.g. a newly copied exe distribution folder, or the
    first-ever run) starts with none of these -- create them all up front
    instead of relying on each write site to remember to."""
    for path in (MODEL_DIR, RECORDINGS_DIR, TRANSCRIPTS_DIR, SUMMARIES_DIR):
        path.mkdir(parents=True, exist_ok=True)
