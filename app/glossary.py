import json

from app.paths import GLOSSARY_PATH


def load_glossary() -> list[str]:
    if not GLOSSARY_PATH.is_file():
        return []
    try:
        data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data.get("terms", [])


def save_glossary(terms: list[str]) -> None:
    GLOSSARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    cleaned: list[str] = []
    for term in terms:
        term = term.strip()
        if term and term not in seen:
            seen.add(term)
            cleaned.append(term)
    GLOSSARY_PATH.write_text(
        json.dumps({"terms": cleaned}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_terms(new_terms: list[str]) -> None:
    """Merge new terms into the glossary, keeping existing ones and order."""
    if not new_terms:
        return
    save_glossary(load_glossary() + new_terms)


def hotwords_string(max_terms: int = 100) -> str:
    """faster-whisper's `hotwords` wants a plain space-separated string that
    biases recognition toward these words/phrases across the whole audio.

    Terms are ranked by how many separate lectures they were corrected in
    before the cap is applied. Slicing the raw list instead would mean that
    once the glossary grows past `max_terms`, automatically collected terms --
    which are appended at the end -- could never make it into the hotwords."""
    terms = load_glossary()
    try:
        from app import term_stats

        counts = term_stats.lecture_counts()
    except Exception:
        counts = {}

    if counts:
        terms = sorted(terms, key=lambda term: counts.get(term, 0), reverse=True)
    return " ".join(terms[:max_terms])
