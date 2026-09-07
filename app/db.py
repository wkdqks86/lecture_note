import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.paths import DB_PATH
from app.utils import hash_file

# Higher rank = more complete, preferred as the "keeper" among duplicates.
STATUS_RANK = {"recorded": 0, "transcribed": 1, "summarized": 2}

SCHEMA = """
CREATE TABLE IF NOT EXISTS lectures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    audio_path TEXT,
    transcript_path TEXT,
    summary_path TEXT,
    status TEXT NOT NULL DEFAULT 'recorded',
    content_hash TEXT
);
"""


@dataclass
class Lecture:
    id: int
    title: str
    recorded_at: str
    audio_path: str | None
    transcript_path: str | None
    summary_path: str | None
    status: str
    content_hash: str | None = None
    raw_transcript_path: str | None = None
    words_path: str | None = None
    material_path: str | None = None


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    for column in ("content_hash TEXT", "raw_transcript_path TEXT", "words_path TEXT", "material_path TEXT"):
        try:
            conn.execute(f"ALTER TABLE lectures ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass  # column already exists (pre-existing db file)
    return conn


def create_lecture(title: str, audio_path: str, content_hash: str | None = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO lectures (title, recorded_at, audio_path, status, content_hash) "
            "VALUES (?, ?, ?, 'recorded', ?)",
            (title, datetime.now().isoformat(timespec="seconds"), audio_path, content_hash),
        )
        return cur.lastrowid


def find_lecture_by_hash(content_hash: str) -> Lecture | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM lectures WHERE content_hash = ? ORDER BY recorded_at DESC LIMIT 1",
            (content_hash,),
        ).fetchone()
        return Lecture(**dict(row)) if row else None


def update_title(lecture_id: int, title: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE lectures SET title = ? WHERE id = ?", (title, lecture_id))


def update_transcript(
    lecture_id: int,
    transcript_path: str,
    raw_transcript_path: str | None = None,
    words_path: str | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE lectures SET transcript_path = ?, raw_transcript_path = ?, words_path = ?, "
            "status = 'transcribed' WHERE id = ?",
            (transcript_path, raw_transcript_path, words_path, lecture_id),
        )


def update_transcript_path(lecture_id: int, transcript_path: str) -> None:
    """Used after the term-review UI edits the (already corrected) transcript
    in place -- doesn't touch raw_transcript_path/words_path or status."""
    with get_connection() as conn:
        conn.execute("UPDATE lectures SET transcript_path = ? WHERE id = ?", (transcript_path, lecture_id))


def update_material(lecture_id: int, material_path: str | None) -> None:
    """Links (or unlinks, with None) the lecture handout/notebook used as
    reference material when correcting and summarising this lecture."""
    with get_connection() as conn:
        conn.execute("UPDATE lectures SET material_path = ? WHERE id = ?", (material_path, lecture_id))


def update_summary(lecture_id: int, summary_path: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE lectures SET summary_path = ?, status = 'summarized' WHERE id = ?",
            (summary_path, lecture_id),
        )


def mark_failed(lecture_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE lectures SET status = 'failed' WHERE id = ?", (lecture_id,))


def list_lectures() -> list[Lecture]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM lectures ORDER BY recorded_at DESC").fetchall()
        return [Lecture(**dict(row)) for row in rows]


def get_lecture(lecture_id: int) -> Lecture | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        return Lecture(**dict(row)) if row else None


def delete_lecture(lecture_id: int, delete_files: bool = True) -> list[str]:
    """Deletes the row, plus its files when asked. Returns the files that could
    not be deleted -- on Windows unlink fails while the audio is still open by
    a running transcription, and letting that abort the whole call left the
    lecture sitting in the list as if the delete had been ignored. The row is
    now always removed, locked file or not."""
    undeleted: list[str] = []
    lecture = get_lecture(lecture_id)
    if lecture and delete_files:
        for path_str in (
            lecture.audio_path,
            lecture.transcript_path,
            lecture.summary_path,
            lecture.raw_transcript_path,
            lecture.words_path,
        ):
            if not path_str:
                continue
            path = Path(path_str)
            if not path.is_file():
                continue
            try:
                path.unlink()
            except OSError:
                undeleted.append(str(path))

    with get_connection() as conn:
        conn.execute("DELETE FROM lectures WHERE id = ?", (lecture_id,))
    return undeleted


def backfill_content_hashes() -> int:
    """Compute content_hash for older lectures that predate the dedup feature.
    Returns the number of rows updated."""
    updated = 0
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, audio_path FROM lectures WHERE content_hash IS NULL AND audio_path IS NOT NULL"
        ).fetchall()
        for row in rows:
            path = Path(row["audio_path"])
            if not path.is_file():
                continue
            digest = hash_file(path)
            conn.execute("UPDATE lectures SET content_hash = ? WHERE id = ?", (digest, row["id"]))
            updated += 1
    return updated


def backfill_raw_transcript_links() -> int:
    """Self-heals rows where correction actually ran and wrote a `_raw.txt`
    sibling file, but raw_transcript_path never got persisted (seen after a
    stale-build mismatch once already) -- relinks by filename convention so
    the correction-status indicator doesn't wrongly call these "구버전".
    Returns the number of rows fixed."""
    fixed = 0
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, transcript_path FROM lectures "
            "WHERE raw_transcript_path IS NULL AND transcript_path IS NOT NULL"
        ).fetchall()
        for row in rows:
            transcript_path = Path(row["transcript_path"])
            raw_candidate = transcript_path.with_name(transcript_path.stem + "_raw" + transcript_path.suffix)
            if raw_candidate.is_file():
                conn.execute(
                    "UPDATE lectures SET raw_transcript_path = ? WHERE id = ?",
                    (str(raw_candidate), row["id"]),
                )
                fixed += 1
    return fixed


def find_duplicate_groups() -> list[list[Lecture]]:
    """Groups of lectures that are likely duplicates. Primary signal is a
    matching audio content_hash; lectures whose audio file has since been
    deleted (so no hash exists) fall back to grouping by identical title --
    a reasonable proxy for "same import, re-run". Within each group, lectures
    are sorted with the best "keeper" candidate first (most complete status,
    then most recent)."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM lectures").fetchall()

    lectures = [Lecture(**dict(row)) for row in rows]

    hash_groups: dict[str, list[Lecture]] = {}
    unhashed: list[Lecture] = []
    for lecture in lectures:
        if lecture.content_hash:
            hash_groups.setdefault(lecture.content_hash, []).append(lecture)
        else:
            unhashed.append(lecture)

    title_groups: dict[str, list[Lecture]] = {}
    for lecture in unhashed:
        title_groups.setdefault(lecture.title, []).append(lecture)

    duplicate_groups = [g for g in hash_groups.values() if len(g) > 1]
    duplicate_groups += [g for g in title_groups.values() if len(g) > 1]

    for group in duplicate_groups:
        group.sort(key=lambda lec: (STATUS_RANK.get(lec.status, 0), lec.recorded_at), reverse=True)
    return duplicate_groups
