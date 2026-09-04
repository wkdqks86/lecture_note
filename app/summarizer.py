import os
from typing import Callable

import anthropic
from dotenv import load_dotenv

from app.paths import ENV_PATH

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
당신은 대학 강의 노트 정리 전문가입니다. 주어진 강의 녹취록을 읽고 아래 형식의 \
마크다운 노트로 정리하세요.

# {강의 제목}

## 한 줄 요약
(전체 강의를 한두 문장으로)

## 목차별 정리
(타임스탬프를 참고해 주제 단위로 소제목을 나누고, 각 소제목 아래 핵심 내용을 \
불릿으로 정리. 타임스탬프도 함께 표기)

## 핵심 키워드
(강의에서 중요한 용어/개념 5~10개, 간단한 설명 포함)

## 복습 질문
(이해도 확인용 질문 3~5개)
"""


class Summarizer:
    def __init__(self):
        # Retry after the user drops a key into .env without restarting the app.
        load_dotenv(ENV_PATH, override=True)
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "Anthropic API 키가 없습니다. "
                f"{ENV_PATH} 파일에 ANTHROPIC_API_KEY=sk-ant-... 한 줄을 넣은 뒤 "
                "다시 시도하세요."
            )
        self.client = anthropic.Anthropic(api_key=api_key)

    def summarize(
        self,
        transcript: str,
        title: str,
        on_delta: Callable[[int], None] | None = None,
    ) -> str:
        """Streamed so the caller sees the summary growing and can stop it.

        `on_delta` receives the number of characters written so far and may
        raise to abort -- a single non-streamed request would otherwise keep
        the thread stuck until the whole answer came back.
        """
        parts: list[str] = []
        written = 0
        with self.client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"강의 제목: {title}\n\n녹취록:\n{transcript}",
                }
            ],
        ) as stream:
            for chunk in stream.text_stream:
                parts.append(chunk)
                written += len(chunk)
                if on_delta is not None:
                    on_delta(written)
        return "".join(parts)
