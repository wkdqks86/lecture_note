import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.paths import DB_PATH, RECORDINGS_DIR
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

# Periods the user ended early with "지금 종료". Kept here rather than in its
# own file so there is one place state lives -- a separate JSON drifted out of
# step with the lectures table too easily.
#
# Deliberately *not* derived from the lectures table: "I decided this class is
# over" and "a recording exists" are different facts. Deriving it would mean
# undoing a misclick required deleting the lecture row, which deletes the audio
# with it -- losing a real recording to fix a button press.
FINISHED_PERIODS_SCHEMA = """
CREATE TABLE IF NOT EXISTS finished_periods (
    day TEXT NOT NULL,
    period INTEGER NOT NULL,
    ended_at TEXT NOT NULL,
    PRIMARY KEY (day, period)
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
    lecture_date: str | None = None
    period: int | None = None


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.execute(FINISHED_PERIODS_SCHEMA)
    for column in (
        "content_hash TEXT",
        "raw_transcript_path TEXT",
        "words_path TEXT",
        "material_path TEXT",
        # Which class this recording is, as data rather than something to be
        # parsed back out of the filename and the title string every time.
        "lecture_date TEXT",
        "period INTEGER",
    ):
        try:
            conn.execute(f"ALTER TABLE lectures ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass  # column already exists (pre-existing db file)
    return conn


# auto_<날짜>_<교시>.wav, 그리고 교시 중간 재시작이 만드는 auto_<날짜>_<교시>_<HHMM>[-n].wav
_AUTO_RECORDING_RE = re.compile(r"^auto_(\d{8})_(\d+)(?:_(\d{2})(\d{2})(?:-\d+)?)?$")


def parse_auto_filename(audio_path: str | Path) -> tuple[str | None, int | None]:
    """(날짜, 교시) from an auto-recording filename, or (None, None).

    The period has only ever existed in the filename and the title text, so
    every feature that wanted it was re-parsing strings. Parsed once here and
    stored in columns instead."""
    match = _AUTO_RECORDING_RE.match(Path(audio_path).stem)
    if not match:
        return None, None
    day, period = match.group(1), match.group(2)
    return f"{day[:4]}-{day[4:6]}-{day[6:]}", int(period)


def create_lecture(
    title: str,
    audio_path: str,
    content_hash: str | None = None,
    lecture_date: str | None = None,
    period: int | None = None,
) -> int:
    if lecture_date is None and period is None:
        lecture_date, period = parse_auto_filename(audio_path)
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO lectures (title, recorded_at, audio_path, status, content_hash, "
            "lecture_date, period) VALUES (?, ?, ?, 'recorded', ?, ?, ?)",
            (
                title,
                datetime.now().isoformat(timespec="seconds"),
                audio_path,
                content_hash,
                lecture_date,
                period,
            ),
        )
        return cur.lastrowid


def backfill_lecture_periods() -> int:
    """Fills `lecture_date`/`period` on rows written before those columns
    existed, reading them back out of the audio filename. Returns rows fixed."""
    fixed = 0
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, audio_path FROM lectures "
            "WHERE period IS NULL AND audio_path IS NOT NULL"
        ).fetchall()
        for row in rows:
            lecture_date, period = parse_auto_filename(row["audio_path"])
            if period is None:
                continue  # manual recording: no period to recover
            conn.execute(
                "UPDATE lectures SET lecture_date = ?, period = ? WHERE id = ?",
                (lecture_date, period, row["id"]),
            )
            fixed += 1
    return fixed


# -- periods ended early with "지금 종료" --

def finished_periods_for(day: str) -> dict[int, str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT period, ended_at FROM finished_periods WHERE day = ?", (day,)
        ).fetchall()
    return {row["period"]: row["ended_at"] for row in rows}


def all_finished_periods() -> set[tuple[str, int]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT day, period FROM finished_periods").fetchall()
    return {(row["day"], row["period"]) for row in rows}


def mark_period_finished(day: str, period: int, ended_at: str, keep_days: int = 14) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO finished_periods (day, period, ended_at) VALUES (?, ?, ?) "
            "ON CONFLICT(day, period) DO UPDATE SET ended_at = excluded.ended_at",
            (day, period, ended_at),
        )
        cutoff = (datetime.now().date() - timedelta(days=keep_days)).isoformat()
        conn.execute("DELETE FROM finished_periods WHERE day < ?", (cutoff,))


def unmark_period_finished(day: str, period: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM finished_periods WHERE day = ? AND period = ?", (day, period))


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


# Columns holding a path to a file this app wrote, in the order they're most
# likely to have been filed away by hand.
_FILE_PATH_COLUMNS = (
    "transcript_path",
    "raw_transcript_path",
    "words_path",
    "summary_path",
    "material_path",
)


def relink_filed_away_files() -> int:
    """Self-heals rows whose files were moved into an `old/` subfolder.

    Finished transcripts get filed into `transcripts/old/` by hand once their
    Notion write-up is done. The DB still points at the original location, so
    opening such a lecture showed "파일을 읽을 수 없습니다" even though nothing
    was lost. Rather than forbid the tidying, follow it: when a stored path is
    missing, look for the same filename one level down in `old/`.

    Only ever repoints to a file that actually exists, and leaves the row
    untouched when the file is simply gone. Returns the number of rows fixed."""
    fixed = 0
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, " + ", ".join(_FILE_PATH_COLUMNS) + " FROM lectures"
        ).fetchall()
        for row in rows:
            updates: dict[str, str] = {}
            for column in _FILE_PATH_COLUMNS:
                stored = row[column]
                if not stored:
                    continue
                path = Path(stored)
                if path.is_file():
                    continue
                moved = path.parent / "old" / path.name
                if moved.is_file():
                    updates[column] = str(moved)
            if updates:
                conn.execute(
                    f"UPDATE lectures SET {', '.join(f'{c} = ?' for c in updates)} WHERE id = ?",
                    (*updates.values(), row["id"]),
                )
                fixed += 1
    return fixed


def known_audio_paths() -> set[str]:
    """Every audio path the DB already knows, normalised for comparison --
    rows were written by different code paths over time, so the same file can
    appear with different capitalisation or separators."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT audio_path FROM lectures WHERE audio_path IS NOT NULL"
        ).fetchall()
    return {os.path.normcase(os.path.normpath(row["audio_path"])) for row in rows if row["audio_path"]}


def _orphan_title(path: Path) -> str:
    """The title `auto_recorder` would have given this file, rebuilt from its
    name so a recovered row is indistinguishable from a normally-recorded one."""
    match = _AUTO_RECORDING_RE.match(path.stem)
    if not match:
        # Manual recordings are named <날짜>_<시각>.wav; fall back to the stem
        # rather than inventing a period number that isn't in the filename.
        return path.stem
    day, period, hour, minute = match.groups()
    title = f"{day[:4]}-{day[4:6]}-{day[6:]} {int(period)}교시 (자동 녹음"
    return title + (f" · {hour}:{minute} 재시작)" if hour else ")")


def register_orphan_recordings() -> list[str]:
    """Adds recordings that exist on disk but were never written to the DB.

    A period's row is created when recording *stops* (`period_stopped`), so a
    crash or a force-quit mid-period leaves the audio on disk with no list
    entry at all -- invisible, and impossible to transcribe from the app. The
    file itself survives (the WAV header is patched on every flush), so the
    only thing missing is the row.

    Safe to run on every launch: deleting a lecture from the list deletes its
    audio too, so a row the user removed on purpose does not come back.

    `recorded_at` comes from the file's modification time -- when the recording
    actually ended -- so recovered lectures sort into their own day rather than
    piling up under today. Returns the titles that were added."""
    if not RECORDINGS_DIR.is_dir():
        return []

    known = known_audio_paths()
    added: list[str] = []

    with get_connection() as conn:
        for path in sorted(RECORDINGS_DIR.glob("*.wav")):
            if os.path.normcase(os.path.normpath(str(path))) in known:
                continue
            try:
                recorded_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
            except OSError:
                continue
            try:
                content_hash = hash_file(path)
            except OSError:
                content_hash = None
            title = _orphan_title(path)
            lecture_date, period = parse_auto_filename(path)
            conn.execute(
                "INSERT INTO lectures (title, recorded_at, audio_path, status, content_hash, "
                "lecture_date, period) VALUES (?, ?, ?, 'recorded', ?, ?, ?)",
                (title, recorded_at, str(path), content_hash, lecture_date, period),
            )
            added.append(title)

    return added


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
