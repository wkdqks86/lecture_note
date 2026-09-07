from typing import Callable

from app.anthropic_client import get_client

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
        self.client = get_client()

    def summarize(
        self,
        transcript: str,
        title: str,
        on_delta: Callable[[int], None] | None = None,
        material_text: str | None = None,
    ) -> str:
        """Streamed so the caller sees the summary growing and can stop it.

        `on_delta` receives the number of characters written so far and may
        raise to abort -- a single non-streamed request would otherwise keep
        the thread stuck until the whole answer came back.
        """
        system = SYSTEM_PROMPT
        if material_text:
            # The day's own notebook: use it to get terminology and section
            # names right, but the note must still describe what was actually
            # said, not just restate the handout.
            system += (
                "\n\n아래는 이 강의에서 사용한 강의 자료입니다. 용어의 정확한 표기와 "
                "주제 구성을 파악하는 데 참고하세요. 다만 노트는 어디까지나 녹취록에서 "
                "실제로 다룬 내용을 정리해야 하며, 자료에만 있고 강의에서 다루지 않은 "
                "내용을 채워 넣지 마세요.\n\n"
                "===== 강의 자료 시작 =====\n"
                f"{material_text}\n"
                "===== 강의 자료 끝 =====")

        parts: list[str] = []
        written = 0
        with self.client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=system,
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
