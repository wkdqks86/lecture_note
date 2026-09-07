import difflib
import json
import re

from app import glossary
from app.anthropic_client import get_client
from app.paths import TERM_STATS_PATH

MODEL = "claude-opus-5"

# How many *different* lectures a term has to be corrected in before it earns
# a place in the glossary. Repeats inside one lecture count once: a term the
# lecturer says twenty times in one class is often just that day's topic (or
# an STT repetition loop), whereas one that comes back next class is part of
# the course's vocabulary.
PROMOTE_AFTER_LECTURES = 2

TIMESTAMP_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2} -> \d{2}:\d{2}:\d{2}\]\s*")

# Only ask about changes that could plausibly be terminology, to keep the
# normalisation call small: pure Korean particle/spelling fixes aren't useful
# glossary material.
_TERMISH_RE = re.compile(r"[A-Za-z]|[가-힣]{2,}")


def _strip_timestamp(line: str) -> str:
    return TIMESTAMP_RE.sub("", line)


def extract_corrections(raw_text: str, corrected_text: str) -> list[tuple[str, str]]:
    """(before, after) phrase pairs the corrector changed.

    The corrector is instructed to keep the line count and timestamps intact,
    so lines pair up positionally; if that ever drifts, difflib realigns them
    instead of producing garbage."""
    raw_lines = raw_text.splitlines()
    corrected_lines = corrected_text.splitlines()

    pairs: list[tuple[str, str]] = []
    matcher = difflib.SequenceMatcher(None, raw_lines, corrected_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        for raw_line, corrected_line in zip(raw_lines[i1:i2], corrected_lines[j1:j2]):
            pairs += _line_corrections(_strip_timestamp(raw_line), _strip_timestamp(corrected_line))
    return pairs


def _line_corrections(raw_line: str, corrected_line: str) -> list[tuple[str, str]]:
    raw_words = raw_line.split()
    corrected_words = corrected_line.split()
    pairs: list[tuple[str, str]] = []
    matcher = difflib.SequenceMatcher(None, raw_words, corrected_words, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        before = " ".join(raw_words[i1:i2])
        after = " ".join(corrected_words[j1:j2])
        if not before or not after or before == after:
            continue
        if not _TERMISH_RE.search(after):
            continue
        pairs.append((before, after))
    return pairs


def normalize_terms(pairs: list[tuple[str, str]], max_pairs: int = 120) -> list[str]:
    """Turns raw diff spans into clean glossary entries.

    A mechanical diff yields things like ("컴퓨터 면접이", "confusion matrix예요")
    -- the useful part is the term, without the Korean ending attached, and
    plenty of changes aren't terminology at all. One batched call cleans that
    up far better than a suffix-stripping heuristic could."""
    if not pairs:
        return []

    # Deduplicate, keeping order, and cap what we send.
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)
    unique = unique[:max_pairs]

    listing = "\n".join(f'- "{before}" -> "{after}"' for before, after in unique)
    prompt = (
        "아래는 강의 녹취록 교정에서 실제로 바뀐 부분의 목록입니다 (교정 전 -> 교정 후).\n"
        "이 중에서 강의에 반복해서 등장할 만한 '전문 용어'만 골라내세요.\n\n"
        "규칙:\n"
        "1. 조사와 어미는 제거하고 용어 자체만 남기세요. (예: \"confusion matrix예요\" -> "
        "\"confusion matrix\")\n"
        "2. 영어 용어는 강의 자료에서 쓰는 표준 표기로 적으세요.\n"
        "3. 단순 오탈자 교정, 조사 교정, 말버릇 정리처럼 용어가 아닌 것은 제외하세요.\n"
        "4. 일반 명사나 일상어는 제외하고, 기술/학술 용어만 남기세요.\n\n"
        f"{listing}\n\n"
        '결과는 다음 JSON 형식으로만 답하세요: {"용어": ["...", "..."]}'
    )

    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text").strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    terms: list[str] = []
    for term in data.get("용어", []):
        term = str(term).strip()
        if term:
            terms.append(term)
    return terms


def _load() -> dict:
    if not TERM_STATS_PATH.is_file():
        return {"terms": {}}
    try:
        data = json.loads(TERM_STATS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"terms": {}}
    if not isinstance(data.get("terms"), dict):
        return {"terms": {}}
    return data


def _save(data: dict) -> None:
    TERM_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TERM_STATS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_lecture_terms(lecture_id: int, terms: list[str]) -> list[str]:
    """Tallies this lecture's corrected terms and promotes the ones that have
    now shown up in enough separate lectures. Returns the newly promoted terms.

    Lecture ids are stored as a set, so re-running correction on the same
    lecture doesn't inflate its own count."""
    if not terms:
        return []

    data = _load()
    entries = data["terms"]
    promoted_now: list[str] = []

    for term in terms:
        entry = entries.setdefault(term, {"lectures": [], "promoted": False})
        if lecture_id not in entry["lectures"]:
            entry["lectures"].append(lecture_id)
        if not entry["promoted"] and len(entry["lectures"]) >= PROMOTE_AFTER_LECTURES:
            entry["promoted"] = True
            promoted_now.append(term)

    _save(data)
    if promoted_now:
        glossary.add_terms(promoted_now)
    return promoted_now


def lecture_counts() -> dict[str, int]:
    """How many separate lectures each term was corrected in -- used to rank
    the glossary when it's longer than the hotwords budget."""
    return {term: len(entry.get("lectures", [])) for term, entry in _load()["terms"].items()}


def auto_added_terms() -> set[str]:
    return {term for term, entry in _load()["terms"].items() if entry.get("promoted")}


def collect_from_correction(lecture_id: int, raw_text: str, corrected_text: str) -> list[str]:
    """Full pass for one finished correction. Never raises: this runs at the
    tail of a lecture's processing, and a hiccup here must not fail work that
    already succeeded."""
    try:
        pairs = extract_corrections(raw_text, corrected_text)
        terms = normalize_terms(pairs)
        return record_lecture_terms(lecture_id, terms)
    except Exception:
        return []
