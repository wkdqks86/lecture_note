from typing import Callable

from app.anthropic_client import get_client

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
당신은 강의 녹취록 교정 전문가입니다. 아래는 음성 인식(STT)으로 자동 변환된 녹취록입니다. \
음성 인식 특성상 발음이 비슷한 다른 단어로 잘못 인식되거나, 특히 영어 전문 용어/약어가 \
엉뚱한 한글로 깨져서 나온 부분이 있을 수 있습니다.

다음 규칙을 반드시 지켜서 교정하세요:
1. 명백한 오인식(오타, 비슷한 발음의 다른 단어)만 최소한으로 고치세요.
2. 문장 구조, 어순, 화자의 말투나 반복되는 구어체 표현은 그대로 두세요. 요약하거나 \
다듬지 마세요 -- 이건 요약이 아니라 교정입니다.
3. 뜻이 통하지 않아 무슨 단어인지 전혀 추측할 수 없는 부분은 억지로 바꾸지 말고 원문 \
그대로 두세요.
4. 각 줄 맨 앞의 타임스탬프 `[00:00:00 -> 00:00:00]` 형식은 절대 건드리지 말고 그대로 \
유지하세요. 줄 수도 원문과 동일하게 유지하세요.
5. 아래 용어집이 주어지면, 발음이 비슷하게 깨진 부분을 용어집의 정확한 표기로 맞추는 데 \
활용하세요.

출력은 교정된 녹취록 전체만 반환하세요. 설명, 안내 문구, 요약을 덧붙이지 마세요.
"""


class TranscriptCorrector:
    def __init__(self):
        self.client = get_client()

    def correct(
        self,
        transcript: str,
        glossary_terms: list[str] | None = None,
        on_delta: Callable[[int], None] | None = None,
        material_text: str | None = None,
    ) -> str:
        """Streamed for the same reason Summarizer.summarize is -- correction
        output is roughly as long as the input, so a non-streamed call on a
        long lecture would sit blocked for a long time with no feedback.
        """
        system = SYSTEM_PROMPT
        if glossary_terms:
            system += "\n\n참고 용어집: " + ", ".join(glossary_terms)
        if material_text:
            # Far stronger signal than the glossary word list: the day's own
            # notebook shows the exact library, function and concept names the
            # lecturer was saying, in context.
            system += (
                "\n\n아래는 이 강의에서 실제로 사용한 강의 자료입니다. 여기 나오는 용어, "
                "라이브러리·함수 이름, 개념어의 정확한 표기를 기준으로 녹취록의 오인식을 "
                "바로잡으세요. 자료에 없는 내용을 녹취록에 새로 넣지는 마세요.\n\n"
                "===== 강의 자료 시작 =====\n"
                f"{material_text}\n"
                "===== 강의 자료 끝 =====")

        parts: list[str] = []
        written = 0
        with self.client.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=system,
            messages=[{"role": "user", "content": transcript}],
        ) as stream:
            for chunk in stream.text_stream:
                parts.append(chunk)
                written += len(chunk)
                if on_delta is not None:
                    on_delta(written)
        return "".join(parts)
