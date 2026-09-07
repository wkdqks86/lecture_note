import json
import shutil
from pathlib import Path

from app.paths import DAY_MATERIAL_PATH, MATERIALS_DIR

SUPPORTED_SUFFIXES = (".ipynb", ".py", ".md", ".txt")

# A day often has a handout plus one or more practice notebooks, so several
# files can be attached; the cap keeps the prompt (and its cost) sane.
MAX_MATERIALS = 5

# The whole notebook goes into the correction/summary prompt as context. A
# lecture notebook is normally well under this; the caps only guard against a
# pathological file (huge embedded data) crowding out the transcript itself.
MAX_CHARS = 40_000
MAX_TOTAL_CHARS = 100_000


def _cell_source(cell: dict) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    return str(source)


def _extract_ipynb(text: str) -> str:
    """Markdown and code cells only. Cell outputs are deliberately dropped --
    they're mostly dataframe dumps and tracebacks, which add a lot of tokens
    and no vocabulary the lecture actually used."""
    notebook = json.loads(text)
    chunks: list[str] = []
    for cell in notebook.get("cells", []):
        source = _cell_source(cell).strip()
        if not source:
            continue
        if cell.get("cell_type") == "markdown":
            chunks.append(source)
        elif cell.get("cell_type") == "code":
            chunks.append(f"```python\n{source}\n```")
    return "\n\n".join(chunks)


def extract_text(path: Path) -> str:
    """Readable text of a lecture handout, for use as prompt context."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".ipynb":
        try:
            text = _extract_ipynb(raw)
        except (json.JSONDecodeError, AttributeError):
            text = raw  # not a valid notebook after all -- use it as plain text
    else:
        text = raw

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n...(이하 생략)"
    return text


def decode_paths(value: str | None) -> list[str]:
    """Lectures can have several materials, stored in the single
    `material_path` column. A JSON array is the multi-file form; a bare path
    is the original single-file form, which older rows still hold."""
    if not value:
        return []
    value = value.strip()
    if value.startswith("["):
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in data if str(item).strip()]
    return [value]


def encode_paths(paths: list[str]) -> str | None:
    paths = [str(path) for path in paths if str(path).strip()]
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]  # keep the plain, readable form for the common case
    return json.dumps(paths, ensure_ascii=False)


def load_materials_text(material_path: str | None) -> str | None:
    """Combined text of every material attached, labelled per file.

    None when there's nothing attached or nothing readable -- callers treat
    materials as optional context, so a file that has since been moved or
    deleted must not break the correction or summary that was going to use
    it."""
    chunks: list[str] = []
    for stored in decode_paths(material_path):
        path = Path(stored)
        if not path.is_file():
            continue
        try:
            text = extract_text(path)
        except OSError:
            continue
        if text:
            chunks.append(f"----- 파일: {path.name} -----\n{text}")

    if not chunks:
        return None

    combined = "\n\n".join(chunks)
    if len(combined) > MAX_TOTAL_CHARS:
        combined = combined[:MAX_TOTAL_CHARS] + "\n...(이하 생략)"
    return combined


def store_for_lecture(lecture_id: int, source: Path) -> Path:
    """Copies the handout into MATERIALS_DIR so the lecture keeps working if
    the original is moved or deleted. Returns the stored path."""
    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MATERIALS_DIR / f"{lecture_id}_{source.name}"
    shutil.copy2(source, dest)
    return dest


# -- material registered ahead of time, for a whole day --------------------
#
# Auto recording creates the lecture row only when the period ends, and starts
# processing it immediately, so there's no practical moment to attach a
# handout in between. Registering the day's notebook up front instead means
# the very first correction and summary already use it, rather than needing a
# second (paid) correction pass afterwards. A day-level file also matches how
# these notebooks actually work -- one covers several periods.


def add_day_materials(date_iso: str, sources: list[Path]) -> list[str]:
    """Registers more files for the day, up to MAX_MATERIALS in total.
    Returns the full list of registered paths after the addition."""
    existing = get_day_materials(date_iso)
    room = MAX_MATERIALS - len(existing)
    if room <= 0:
        return existing

    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
    for source in sources[:room]:
        dest = MATERIALS_DIR / f"day_{date_iso.replace('-', '')}_{source.name}"
        shutil.copy2(source, dest)
        if str(dest) not in existing:
            existing.append(str(dest))

    DAY_MATERIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    DAY_MATERIAL_PATH.write_text(
        json.dumps({"date": date_iso, "paths": existing}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return existing


def get_day_materials(date_iso: str) -> list[str]:
    """The registered paths, but only for the day they were registered for --
    so files left over from an earlier day never silently attach themselves to
    today's lectures."""
    if not DAY_MATERIAL_PATH.is_file():
        return []
    try:
        data = json.loads(DAY_MATERIAL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if data.get("date") != date_iso:
        return []

    # "path" is the original single-file form of this file.
    paths = data.get("paths") or ([data["path"]] if data.get("path") else [])
    return [str(path) for path in paths if Path(str(path)).is_file()]


def clear_day_materials() -> None:
    try:
        DAY_MATERIAL_PATH.unlink(missing_ok=True)
    except OSError:
        pass
