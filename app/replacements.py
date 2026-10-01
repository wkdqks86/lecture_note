import json
import re

from app.paths import REPLACEMENTS_PATH
from app.term_stats import TIMESTAMP_RE

# Same reasoning as the glossary's promotion rule: a fix seen in a single
# lecture may be specific to that day's context, while one that comes back in
# a different lecture is a repeatable mishearing of this speaker/mic/vocabulary.
PROMOTE_AFTER_LECTURES = 2


def _load() -> dict:
    if not REPLACEMENTS_PATH.is_file():
        return {"pairs": {}}
    try:
        data = json.loads(REPLACEMENTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"pairs": {}}
    if not isinstance(data.get("pairs"), dict):
        return {"pairs": {}}
    return data


def _save(data: dict) -> None:
    REPLACEMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPLACEMENTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _tokens_present(text: str, phrase: str) -> bool:
    """Whether `phrase` survives in `text` as whole whitespace-separated tokens."""
    tokens = phrase.split()
    if not tokens:
        return False
    pattern = r"(?<!\S)" + r"\s+".join(re.escape(token) for token in tokens) + r"(?!\S)"
    return re.search(pattern, text) is not None


def record(
    lecture_id: int,
    pairs: list[tuple[str, str]],
    corrected_text: str | None = None,
) -> list[tuple[str, str]]:
    """Tallies this lecture's (misheard -> corrected) pairs. Returns the pairs
    that just became active.

    Three guards keep a bad entry from silently rewriting future transcripts:

    1. seen in PROMOTE_AFTER_LECTURES separate lectures;
    2. corrected the *same way* every time -- a phrase fixed differently in
       different lectures depends on context, so no blind replacement is safe;
    3. never left alone elsewhere in a corrected transcript. This is the one
       that matters most in practice: "텍스트" really was a mishearing of
       "테스트" once, but it is also a perfectly good word the lecturer uses,
       so replacing every occurrence would corrupt correct text. A misheard
       form that is never valid anywhere ("결칙지") passes this test."""
    if not pairs and corrected_text is None:
        return []

    data = _load()
    entries = data["pairs"]
    activated: list[tuple[str, str]] = []

    for before, after in pairs:
        before = before.strip()
        after = after.strip()
        if not before or not after or before == after:
            continue

        entry = entries.setdefault(
            before, {"targets": {}, "active": False, "disabled_by_user": False, "also_valid": False}
        )
        lectures = entry["targets"].setdefault(after, [])
        if lecture_id not in lectures:
            lectures.append(lecture_id)

        if len(entry["targets"]) > 1:
            entry["active"] = False  # became context-dependent
            continue
        if entry["active"] or entry.get("disabled_by_user") or entry.get("also_valid"):
            continue
        if len(lectures) >= PROMOTE_AFTER_LECTURES:
            entry["active"] = True
            activated.append((before, after))

    # Any phrase the corrector deliberately left standing in this transcript is
    # a legitimate word here, whatever it was mistaken for elsewhere.
    if corrected_text:
        for before, entry in entries.items():
            if entry.get("also_valid"):
                continue
            if _tokens_present(corrected_text, before):
                entry["also_valid"] = True
                entry["active"] = False
        activated = [pair for pair in activated if not entries[pair[0]].get("also_valid")]

    _save(data)
    return activated


def _is_active(entry: dict) -> bool:
    return (
        bool(entry.get("active"))
        and not entry.get("disabled_by_user")
        and not entry.get("also_valid")
        and len(entry.get("targets") or {}) == 1
    )


def active_pairs() -> dict[str, str]:
    """{misheard: corrected} for every pair cleared for automatic use."""
    pairs: dict[str, str] = {}
    for before, entry in _load()["pairs"].items():
        if _is_active(entry):
            pairs[before] = next(iter(entry["targets"]))
    return pairs


def all_entries() -> list[dict]:
    """Everything tallied so far, for the management UI. Sorted with active
    pairs first, then by how many lectures back them."""
    rows: list[dict] = []
    for before, entry in _load()["pairs"].items():
        targets = entry.get("targets") or {}
        lecture_count = max((len(ids) for ids in targets.values()), default=0)
        rows.append(
            {
                "before": before,
                "after": " / ".join(targets) if targets else "",
                "lectures": lecture_count,
                "active": _is_active(entry),
                "ambiguous": len(targets) > 1,
                "also_valid": bool(entry.get("also_valid")),
                "disabled_by_user": bool(entry.get("disabled_by_user")),
            }
        )
    rows.sort(key=lambda row: (not row["active"], -row["lectures"], row["before"]))
    return rows


def set_disabled(before: str, disabled: bool) -> None:
    data = _load()
    entry = data["pairs"].get(before)
    if entry is None:
        return
    entry["disabled_by_user"] = disabled
    _save(data)


def forget(before: str) -> None:
    data = _load()
    if data["pairs"].pop(before, None) is not None:
        _save(data)


def apply(text: str) -> tuple[str, int]:
    """Applies the learned pairs to a raw transcript. Returns the new text and
    how many replacements were made.

    Line-by-line and whitespace-token based, so the line count and the leading
    timestamps survive untouched -- everything downstream (the ambiguous-word
    review, re-correction from raw) relies on that alignment."""
    pairs = active_pairs()
    if not pairs:
        return text, 0

    # Longest first, so a multi-word phrase wins over a single word inside it.
    ordered = sorted(pairs.items(), key=lambda item: len(item[0].split()), reverse=True)

    replaced = 0
    out_lines: list[str] = []
    for line in text.splitlines():
        match = TIMESTAMP_RE.match(line)
        prefix, body = (match.group(0), line[match.end():]) if match else ("", line)

        for before, after in ordered:
            tokens = before.split()
            if not tokens:
                continue
            # Match the phrase only as whole whitespace-separated tokens.
            pattern = r"(?<!\S)" + r"\s+".join(re.escape(token) for token in tokens) + r"(?!\S)"
            body, count = re.subn(pattern, after.replace("\\", r"\\"), body)
            replaced += count

        out_lines.append(prefix + body)

    result = "\n".join(out_lines)
    if text.endswith("\n"):
        result += "\n"
    return result, replaced
