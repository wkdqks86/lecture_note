import json

from app.paths import SETTINGS_PATH

# How a transcript gets corrected after speech recognition:
#   api          - Claude corrects the whole transcript (best quality, costs money)
#   local_then_api - learned replacements first, then Claude
#   local        - learned replacements only, no API call at all (free)
CORRECTION_MODES = ("api", "local_then_api", "local")
CORRECTION_MODE_LABELS = {
    "api": "Claude 교정 (기본)",
    "local_then_api": "치환 사전 + Claude 교정",
    "local": "치환 사전만 (API 사용 안 함)",
}

# Which model does the correction pass. Correction is the expensive stage --
# its output is as long as its input, and output tokens cost 5x input -- so
# this is the single biggest lever on what a lecture costs to process.
# Summarising stays on Opus: it needs the judgement and its output is short,
# so it's cheap either way.
CORRECTION_MODELS = ("claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5")
CORRECTION_MODEL_LABELS = {
    "claude-sonnet-5": "Sonnet 5 — 권장 (강의당 약 $0.2)",
    "claude-opus-5": "Opus 5 — 최고 품질 (강의당 약 $0.45)",
    "claude-haiku-4-5": "Haiku 4.5 — 가장 저렴 (강의당 약 $0.09)",
}

DEFAULTS = {
    "correction_mode": "api",
    "correction_model": "claude-sonnet-5",
    # Which stages run by themselves after a recording finishes.
    #   auto_transcribe - speech recognition + correction. Recognition is local
    #     and free; correction follows correction_mode above.
    #   auto_summarize  - the summary note and the glossary learning that goes
    #     with it. Both are API calls, so this is the switch to flip when you'd
    #     rather write the summary yourself in the Claude desktop app.
    # Either way, both stages stay available on demand from the list's context
    # menu, so turning them off delays work rather than losing it.
    "auto_transcribe": True,
    "auto_summarize": True,
}

BOOL_KEYS = ("auto_transcribe", "auto_summarize")


def load() -> dict:
    if not SETTINGS_PATH.is_file():
        return dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update({key: data[key] for key in DEFAULTS if key in data})
    return merged


def save(values: dict) -> None:
    """Unknown keys and invalid values are dropped rather than written -- a bad
    value on disk would silently reset the user's real choice to the default
    on the next read."""
    current = load()
    for key in DEFAULTS:
        if key not in values:
            continue
        if key == "correction_mode" and values[key] not in CORRECTION_MODES:
            continue
        if key == "correction_model" and values[key] not in CORRECTION_MODELS:
            continue
        if key in BOOL_KEYS and not isinstance(values[key], bool):
            continue
        current[key] = values[key]
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def correction_mode() -> str:
    mode = load().get("correction_mode", "api")
    return mode if mode in CORRECTION_MODES else "api"


def correction_model() -> str:
    model = load().get("correction_model", "claude-sonnet-5")
    return model if model in CORRECTION_MODELS else "claude-sonnet-5"


def auto_transcribe() -> bool:
    return bool(load().get("auto_transcribe", True))


def auto_summarize() -> bool:
    return bool(load().get("auto_summarize", True))
