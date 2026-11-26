import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetMyDescription

import config
from handlers.common import cmd_start
from services import bot_branding as branding
from services.deepseek_client import AIUnavailable


@pytest.fixture
def welcome_ai(monkeypatch):
    monkeypatch.setattr(config, "AI_WELCOME_ENABLED", True)
    monkeypatch.setattr(config, "AI_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(config, "MINI_APP_URL", "https://app.example")
    suggestions = branding.WelcomeSuggestions()
    monkeypatch.setattr(branding, "welcome_suggestions", suggestions)
    return suggestions


@pytest.mark.asyncio
async def test_welcome_100_students_never_wait_for_ai_and_escape_names(welcome_ai, monkeypatch):
    model = AsyncMock(side_effect=AssertionError("/start must not call AI"))
    monkeypatch.setattr(branding, "complete_json", model)
    messages = [SimpleNamespace(text="/start", from_user=SimpleNamespace(id=i, first_name="Aziza <b>&"),
                                answer=AsyncMock()) for i in range(100)]
    await asyncio.gather(*(cmd_start(message, AsyncMock()) for message in messages))
    for message in messages:
        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "Basirat" in text and "Bugungi tavsiya" in text
        assert "Aziza &lt;b&gt;&amp;" in text
        assert message.answer.await_args.kwargs["reply_markup"].keyboard[0][0].web_app.url == config.MINI_APP_URL
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_tips_are_shared_validated_and_keep_last_good_on_failure(welcome_ai, monkeypatch):
    tips = list(branding.FALLBACK_SUGGESTIONS[:3])
    model = AsyncMock(return_value=({"suggestions": tips}, {}))
    monkeypatch.setattr(branding, "complete_json", model)
    assert await welcome_ai.refresh()
    assert welcome_ai._tips == tuple(tips)
    for user in range(100):
        assert welcome_ai.for_user(user) in tips
    model.assert_awaited_once()
    request = model.await_args
    assert request.kwargs["timeout"] == 8 and request.kwargs["max_tokens"] == 900
    assert all("Aziza" not in message["content"] for message in request.args[0])
    model.return_value = ({"suggestions": ["<b>Bad content</b>"] * 3}, {})
    with pytest.raises(AIUnavailable):
        await welcome_ai.refresh()
    assert welcome_ai._tips == tuple(tips)
    model.side_effect = AIUnavailable("offline")
    with pytest.raises(AIUnavailable):
        await welcome_ai.refresh()
    assert welcome_ai._tips == tuple(tips)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"suggestions": "not a list"},
                                     {"suggestions": [True, "two", "three"]},
                                     {"suggestions": ["Read https://example.com for more study tips."] * 3},
                                     {"suggestions": [branding.FALLBACK_SUGGESTIONS[0]] * 3}])
async def test_malformed_ai_tips_leave_prepared_fallback(welcome_ai, monkeypatch, payload):
    monkeypatch.setattr(branding, "complete_json", AsyncMock(return_value=(payload, {})))
    with pytest.raises(AIUnavailable):
        await welcome_ai.refresh()
    assert welcome_ai._tips == branding.FALLBACK_SUGGESTIONS


@pytest.mark.asyncio
async def test_welcome_worker_retries_slowly_and_cancels_cleanly(welcome_ai, monkeypatch):
    model = AsyncMock(side_effect=AIUnavailable("offline"))
    monkeypatch.setattr(branding, "complete_json", model)
    sleeping = asyncio.Event()
    async def sleep(delay):
        assert delay == 900
        sleeping.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(branding.asyncio, "sleep", sleep)
    task = asyncio.create_task(welcome_ai.worker())
    await asyncio.wait_for(sleeping.wait(), 1)
    assert welcome_ai.for_user(123) in branding.FALLBACK_SUGGESTIONS
    model.assert_awaited_once()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_welcome_no_key_or_disabled_worker_has_no_requests(welcome_ai, monkeypatch):
    model = AsyncMock()
    monkeypatch.setattr(branding, "complete_json", model)
    for key in ("", "your_deepseek_api_key_here"):
        monkeypatch.setattr(config, "DEEPSEEK_API_KEY", key)
        await welcome_ai.worker()
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_WELCOME_ENABLED", False)
    await welcome_ai.worker()
    model.assert_not_awaited()


def description_bot():
    return SimpleNamespace(
        get_my_description=AsyncMock(return_value=SimpleNamespace(description="old")),
        get_my_short_description=AsyncMock(return_value=SimpleNamespace(short_description="old")),
        set_my_description=AsyncMock(), set_my_short_description=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_prestart_and_profile_descriptions_sync_only_when_changed():
    bot = description_bot()
    assert len(branding.BOT_DESCRIPTION) <= 512
    assert len(branding.BOT_SHORT_DESCRIPTION) <= 120
    assert await branding.sync_bot_branding(bot)
    assert bot.set_my_description.await_count == bot.set_my_short_description.await_count == 2
    assert {call.kwargs["language_code"] for call in bot.set_my_description.await_args_list} == {"", "uz"}
    bot.get_my_description.return_value.description = branding.BOT_DESCRIPTION
    bot.get_my_short_description.return_value.short_description = branding.BOT_SHORT_DESCRIPTION
    bot.set_my_description.reset_mock()
    bot.set_my_short_description.reset_mock()
    assert await branding.sync_bot_branding(bot)
    bot.set_my_description.assert_not_awaited()
    bot.set_my_short_description.assert_not_awaited()


@pytest.mark.asyncio
async def test_description_api_outage_is_nonfatal():
    bot = description_bot()
    bot.get_my_description.side_effect = TelegramNetworkError(method=GetMyDescription(), message="offline")
    assert not await branding.sync_bot_branding(bot)
    bot.set_my_description.assert_not_awaited()
    assert bot.set_my_short_description.await_count == 2


def test_bot_only_welcome_and_all_dynamic_text_is_escaped(welcome_ai, monkeypatch):
    monkeypatch.setattr(config, "MINI_APP_URL", "")
    welcome_ai._tips = ("A & B <img src=x> study suggestion",)
    text = branding.welcome_text("Ali", 1)
    assert "&lt;img src=x&gt;" in text and "A &amp; B" in text
    assert "test kodini" in text
