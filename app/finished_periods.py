"""Which periods the user ended early, kept across restarts.

"지금 종료" means "this class is over, don't record it again today". That used
to live only in memory, so quitting the app and reopening it inside the same
period started recording again -- the one thing the button exists to prevent.

Stored in the DB (`finished_periods` table) rather than its own file, so there
is one place state lives. It stays separate from the `lectures` row on purpose:
"I decided this class is over" and "a recording exists" are different facts,
and deriving one from the other would mean undoing a misclick required deleting
the lecture -- which deletes its audio too.

Entries carry the time they were ended, so a recording that looks short has an
answer on screen. Only today's matter for behaviour; older rows are pruned.
"""

import json
from datetime import datetime

from app import db
from app.paths import FINISHED_PERIODS_PATH

KEEP_DAYS = 14

# Entries written by the short-lived JSON version, imported once on startup.
_LEGACY_PATH = FINISHED_PERIODS_PATH
_LEGACY_DONE_PATH = FINISHED_PERIODS_PATH.with_suffix(".json.migrated")


def migrate_legacy_file() -> int:
    """Moves entries from the old finished_periods.json into the table, then
    renames the file so it is imported exactly once. Returns entries moved."""
    if not _LEGACY_PATH.is_file():
        return 0
    try:
        raw = json.loads(_LEGACY_PATH.read_text(encoding="utf-8")).get("finished", {})
    except (OSError, json.JSONDecodeError):
        raw = {}

    moved = 0
    if isinstance(raw, dict):
        for day, periods in raw.items():
            if not isinstance(periods, dict):
                continue
            for period, ended_at in periods.items():
                try:
                    db.mark_period_finished(day, int(period), str(ended_at), KEEP_DAYS)
                    moved += 1
                except (TypeError, ValueError):
                    continue
    try:
        _LEGACY_PATH.replace(_LEGACY_DONE_PATH)
    except OSError:
        pass  # left in place; the import is idempotent, so a retry is harmless
    return moved


def load() -> set[tuple[str, int]]:
    """{(날짜, 교시)} for every period ended early, in the shape
    `AutoRecordController` keys its in-memory set by."""
    return db.all_finished_periods()


def entries_for(day: str) -> dict[int, str]:
    """{교시: 끝낸 시각} for one day, for showing what is currently suppressed."""
    return db.finished_periods_for(day)


def record(day: str, period: int, ended_at: datetime) -> None:
    db.mark_period_finished(day, period, ended_at.strftime("%H:%M"), KEEP_DAYS)


def clear(day: str, period: int) -> None:
    """Re-arms a period that was ended early -- for when class actually
    resumes, or the button was pressed by mistake."""
    db.unmark_period_finished(day, period)
