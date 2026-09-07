import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.anthropic_client import get_client
from app.transcriber import WordInfo

MODEL = "claude-opus-5"

# Below this per-word confidence, a word is a candidate for review.
PROBABILITY_THRESHOLD = 0.55
MAX_FLAGGED_WORDS = 40
MAX_OCCURRENCES_PER_WORD = 3

# Korean particles/fillers that are routinely low-confidence for reasons that
# have nothing to do with meaning (they're grammatical glue, not content) --
# flagging them would just bury the words actually worth a human's time.
_STOPWORDS = {
    "은", "는", "이", "가", "을", "를", "의", "에", "에서", "으로", "로", "와", "과",
    "도", "만", "요", "죠", "네", "예", "아", "어", "음", "그", "저", "이제", "막",
    "좀", "그냥", "그리고", "근데", "그래서", "뭐", "자", "우리", "여러분", "거", "게",
    "걸", "게요", "거예요", "이거", "저거", "그거",
}


@dataclass
class WordOccurrence:
    segment_index: int
    sentence: str


@dataclass
class FlaggedWord:
    word: str
    min_probability: float
    count: int
    occurrences: list[WordOccurrence] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)


def save_words(words_path: Path, words: list[WordInfo]) -> None:
    words_path.parent.mkdir(parents=True, exist_ok=True)
    words_path.write_text(json.dumps([asdict(w) for w in words], ensure_ascii=False), encoding="utf-8")


def load_words(words_path: Path) -> list[WordInfo]:
    data = json.loads(words_path.read_text(encoding="utf-8"))
    return [WordInfo(**d) for d in data]


def _is_reviewable(word: str) -> bool:
    cleaned = re.sub(r"[.,!?~…·\"'()\[\]]", "", word).strip()
    if len(cleaned) < 2:
        return False
    if cleaned in _STOPWORDS:
        return False
    if cleaned.isdigit():
        return False
    return True


def find_ambiguous_words(words: list[WordInfo], transcript_lines: list[str]) -> list[FlaggedWord]:
    """Groups low-confidence words by their (cleaned) text, each with a couple
    of example sentences pulled from the transcript by segment index so the
    reviewer has context, not just a bare word."""
    grouped: dict[str, FlaggedWord] = {}

    for w in words:
        cleaned = re.sub(r"[.,!?~…·\"'()\[\]]", "", w.word).strip()
        if not cleaned or w.probability >= PROBABILITY_THRESHOLD or not _is_reviewable(w.word):
            continue

        flagged = grouped.setdefault(cleaned, FlaggedWord(word=cleaned, min_probability=1.0, count=0))
        flagged.min_probability = min(flagged.min_probability, w.probability)
        flagged.count += 1

        if len(flagged.occurrences) < MAX_OCCURRENCES_PER_WORD and w.segment_index < len(transcript_lines):
            sentence = transcript_lines[w.segment_index]
            if not any(o.segment_index == w.segment_index for o in flagged.occurrences):
                flagged.occurrences.append(WordOccurrence(segment_index=w.segment_index, sentence=sentence))

    ranked = sorted(grouped.values(), key=lambda f: (f.min_probability, -f.count))
    return ranked[:MAX_FLAGGED_WORDS]


def generate_candidates(flagged: list[FlaggedWord], glossary_terms: list[str] | None = None) -> None:
    """Fills in `.candidates` on each FlaggedWord in place via one batched
    Claude call (instead of one request per word)."""
    if not flagged:
        return

    items = [
        {
            "word": f.word,
            "sentences": [o.sentence for o in f.occurrences],
        }
        for f in flagged
    ]

    glossary_note = ""
    if glossary_terms:
        glossary_note = "\n\n참고 용어집 (강의에서 자주 나오는 용어): " + ", ".join(glossary_terms)

    system = (
        "당신은 한국어 강의 음성 인식(STT) 결과를 검토하는 전문가입니다. "
        "아래는 신뢰도가 낮아 잘못 인식됐을 수 있는 단어들과, 그 단어가 등장한 문장들입니다.\n\n"
        "각 단어마다 문맥상 실제로 의도됐을 가능성이 있는 후보 단어를 최대 3개까지 제시하세요.\n"
        "- 후보는 원래 단어와 발음이 비슷하거나 문맥상 자연스러운 대체어여야 합니다.\n"
        "- 확신이 없으면 후보 개수를 줄이거나 빈 배열로 두세요. 억지로 채우지 마세요.\n"
        "- 이미 정확해 보이는 단어는 후보를 비워두세요.\n"
        f"{glossary_note}\n\n"
        '반드시 아래 JSON 형식으로만 답하세요 (설명 없이): '
        '{"결과": [{"word": "원래단어", "candidates": ["후보1", "후보2"]}, ...]}'
    )

    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")

    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = json.loads(match.group(0) if match else text)
    except (json.JSONDecodeError, AttributeError):
        return  # candidates stay empty -- reviewer can still type their own

    by_word = {f.word: f for f in flagged}
    for entry in parsed.get("결과", []):
        target = by_word.get(entry.get("word", ""))
        if target:
            target.candidates = [c for c in entry.get("candidates", []) if c][:3]
