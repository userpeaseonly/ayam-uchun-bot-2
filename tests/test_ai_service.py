import pytest
from unittest.mock import AsyncMock
from services.ai_service import AIService


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
async def test_ai_service_deepseek_mock():
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
