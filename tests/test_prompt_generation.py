import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from models.api_models import ChatMessage
from services.openai_service import openai_service

# 파라메트리제이션: easy, intermediate, advanced
@pytest.mark.parametrize("level", ["easy", "intermediate", "advanced"])
@pytest.mark.asyncio
async def test_system_prompt_generation(monkeypatch, level):
    """generate_chat_response 호출 시 생성되는 시스템 프롬프트를 검증한다."""
    # --- Arrange ---
    user_language = "Korean"
    ai_language = "English"
    last_user_message = "What level are you?"
    messages = [
        ChatMessage(
            role="user",
            content=last_user_message,
            isUser=True,
            timestamp=datetime.utcnow()
        )
    ]

    captured = {}

    # Dummy OpenAI 응답 객체 생성
    def fake_create(model, messages, max_tokens, temperature, response_format):
        # 시스템 프롬프트 캡처
        captured["messages"] = messages
        # 최소한의 유효 JSON 응답 반환
        dummy_content = '{"response":"OK","learnWords":[]}'
        dummy_choice = SimpleNamespace(message=SimpleNamespace(content=dummy_content), finish_reason="stop")
        dummy_usage = SimpleNamespace(prompt_tokens=50, completion_tokens=10, total_tokens=60)
        return SimpleNamespace(choices=[dummy_choice], usage=dummy_usage)

    # monkeypatch
    monkeypatch.setattr(openai_service.client.chat.completions, "create", fake_create)

    # --- Act ---
    chat_response, learn_words = await openai_service.generate_chat_response(
        messages, user_language, ai_language, level, last_user_message
    )

    # --- Assert ---
    # 시스템 메시지는 첫 번째여야 한다
    sys_msg = captured["messages"][0]
    assert sys_msg["role"] == "system", "첫 번째 메시지가 system이 아닙니다."
    prompt = sys_msg["content"]

    # 프롬프트에 플레이스홀더가 남아있지 않아야 한다
    assert "{ai_language}" not in prompt, "ai_language 플레이스홀더가 치환되지 않았습니다."
    assert "{user_language}" not in prompt, "user_language 플레이스홀더가 치환되지 않았습니다."

    # JSON 예시 섹션이 포함되어야 한다
    assert "\"learnWords\"" in prompt, "learnWords 예시가 프롬프트에 없습니다."

    # 단어 수 제한 체크 (간단히 문자열 포함 여부)
    if level == "advanced":
        assert "up to 40 words" in prompt or "40 words" in prompt
    else:
        assert "18-22 words" in prompt

    # 함수 반환값이 예상대로인지
    assert isinstance(chat_response, str)
    assert chat_response == "OK"
    assert learn_words == [] 