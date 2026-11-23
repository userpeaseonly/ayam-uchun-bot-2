import pytest
from unittest.mock import AsyncMock
from services.ai_service import AIService
from services.deepseek_client import AIUnavailable
import config


@pytest.mark.asyncio
async def test_ai_service_empty_answer():
    ai = AIService()
    is_corr, exp = await ai.evaluate_open_answer(
        question_num=1,
        rubric="O'simliklar fotosintez jarayoni haqida",
        student_answer=""
    )
    assert not is_corr
    assert "bo'sh" in exp


@pytest.mark.asyncio
async def test_ai_service_deepseek_mock(monkeypatch):
    # The mocked provider must not depend on credentials from a developer's .env.
    import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "fake-unit-test-key")
    ai = AIService()
    ai.provider = "deepseek"
    ai._call_deepseek = AsyncMock(
        return_value=(True, "Javob to'liq va to'g'ri tushuntirilgan")
    )

    is_corr, exp = await ai.evaluate_open_answer(
        question_num=4,
        rubric="O'quvchi Quyosh nuri va xlorofill haqida yozishi shart",
        student_answer="Fotosintez uchun xlorofill va quyosh nuri zarur"
    )

    assert is_corr is True
    assert "to'liq" in exp


@pytest.mark.asyncio
async def test_no_key_is_pending_instead_of_automatic_acceptance(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(AIUnavailable):
        await AIService().evaluate_open_answer(1, "Teacher criteria", "Student answer")


def test_grading_rejects_string_boolean_and_missing_fields():
    with pytest.raises(AIUnavailable):
        AIService._validated_grade({"is_correct": "false", "explanation": "Bad response"})
    with pytest.raises(AIUnavailable):
        AIService._validated_grade({"is_correct": True})
