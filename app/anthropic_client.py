import os

import anthropic
from dotenv import load_dotenv

from app.paths import ENV_PATH


def get_client() -> anthropic.Anthropic:
    # Retry after the user drops a key into .env without restarting the app.
    load_dotenv(ENV_PATH, override=True)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Anthropic API 키가 없습니다. "
            f"{ENV_PATH} 파일에 ANTHROPIC_API_KEY=sk-ant-... 한 줄을 넣은 뒤 다시 시도하세요."
        )
    return anthropic.Anthropic(api_key=api_key)
