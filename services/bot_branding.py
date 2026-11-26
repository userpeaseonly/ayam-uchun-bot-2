"""Basirat onboarding copy and shared, nonblocking study suggestions."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram.exceptions import TelegramAPIError

import config
from services.deepseek_client import AIUnavailable, complete_json

logger = logging.getLogger(__name__)
TASHKENT = timezone(timedelta(hours=5))

BOT_DESCRIPTION = (
    "🎓 Basirat · Bilim sari birga\n\n"
    "Ona tili va adabiyot bo‘yicha bilimingizni sinang, mashq qiling va natijangizni kuzating.\n\n"
    "📚 O‘quvchilar uchun — testlar va shaxsiy natijalar.\n"
    "👩‍🏫 Ustozlar uchun — PDF yoki rasmdan test tayyorlash va natijalarni boshqarish.\n\n"
    "Basirat o‘quvchisi bo‘lishingiz shart emas. Barcha uchun ochiq.\n\n"
    "Tayyor bo‘lsangiz, Start tugmasini bosing."
)
BOT_SHORT_DESCRIPTION = (
    "Basirat · Ona tili va adabiyot testlari. O‘quvchilar va ustozlar uchun. Bilim sari birga."
)
FALLBACK_SUGGESTIONS = (
    "Bugun bitta testdan boshlang. So‘ng qiynalgan savollaringizga qaytib, tegishli qoidani takrorlang.",
    "Savoldagi kalit so‘zlarni diqqat bilan o‘qing. Ba’zan javobni topishga bitta qo‘shimcha yordam beradi.",
    "Xato — qaysi mavzuni takrorlash kerakligini ko‘rsatadigan belgi. Bugun bitta qoidani mustahkamlang.",
    "Javob variantlarini tanlashdan oldin savol sizdan aynan nimani so‘rayotganini aniqlang.",
    "O‘xshash so‘zlarni kichik misollarda solishtiring. Farqni tushunish qoidani eslab qolishni osonlashtiradi.",
)


class WelcomeSuggestions:
    def __init__(self):
        self._tips = FALLBACK_SUGGESTIONS

    def for_user(self, user_id):
        # Local selection only: no names, IDs, answers or activity go to the model.
        day = datetime.now(TASHKENT).date().toordinal()
        return self._tips[(user_id + day) % len(self._tips)]

    async def refresh(self):
        if not (config.AI_WELCOME_ENABLED and config.AI_PROVIDER == "deepseek"
                and config.DEEPSEEK_API_KEY and not config.DEEPSEEK_API_KEY.startswith("your_")):
            return False
        data, _ = await complete_json([
            {"role": "system", "content": (
                "Siz Basirat ta’lim platformasining samimiy va muloyim o‘quv yordamchisisiz. "
                "Ona tili va adabiyot testlariga tayyorlanayotgan o‘quvchilar uchun "
                "5 ta turli, amaliy, qisqa o‘qish tavsiyasi yozing. Har biri 1–2 jumla, "
                "30–180 belgi, o‘zbek lotin yozuvida bo‘lsin. "
                "Quruq shior o‘rniga bajarish mumkin bo‘lgan kichik qadam taklif qiling. "
                "O‘quvchining darajasi, oldingi natijasi yoki faoliyati haqida taxmin qilmang. "
                "Baho, sertifikat yoki muvaffaqiyatni kafolatlamang. Reklama, to‘lov, "
                "havola, emoji, HTML, Markdown va savollarning tayyor javoblarini kiritmang. "
                'Faqat JSON qaytaring: {"suggestions": ["tavsiya", "..."]}.'
            )},
            {"role": "user", "content": "Bugungi tavsiyalar: " + datetime.now(TASHKENT).date().isoformat()},
        ], model=config.DEEPSEEK_MODEL, max_tokens=900, timeout=8)
        tips = data.get("suggestions") if isinstance(data, dict) else None
        if not isinstance(tips, list) or not 3 <= len(tips) <= 8:
            raise AIUnavailable("Welcome suggestions have an invalid shape.")
        cleaned = []
        for tip in tips:
            if not isinstance(tip, str):
                raise AIUnavailable("Welcome suggestion is not text.")
            tip = " ".join(tip.split())
            if not 30 <= len(tip) <= 180 or any(marker in tip.lower() for marker in ("<", ">", "http", "www.", "t.me", "**", "[", "]")):
                raise AIUnavailable("Welcome suggestion is invalid.")
            if tip not in cleaned:
                cleaned.append(tip)
        if len(cleaned) < 3:
            raise AIUnavailable("Welcome suggestions must be distinct.")
        self._tips = tuple(cleaned)
        return True

    async def worker(self):
        while True:
            try:
                if not await self.refresh():
                    return
                delay = 24 * 60 * 60
            except (AIUnavailable, asyncio.TimeoutError) as error:
                # No provider payload, key or user data in logs.
                logger.warning("Welcome suggestions unavailable (%s); keeping prepared tips.", type(error).__name__)
                delay = 15 * 60
            await asyncio.sleep(delay)


welcome_suggestions = WelcomeSuggestions()


def welcome_text(first_name, user_id):
    action = ("Boshlash uchun quyidagi <b>📚 Testlarni ochish</b> tugmasini bosing."
              if config.MINI_APP_URL else
              "<b>✍️ Test topshirish</b> tugmasini bosing yoki ustozingiz bergan test kodini yuboring.")
    return (
        "🎓 <b>Basirat</b>\n<i>Bilim sari birga.</i>\n\n"
        f"Assalomu alaykum, <b>{escape(first_name)}</b>!\n"
        "Ona tili va adabiyot bo‘yicha bilimingizni sinab ko‘ramizmi?\n\n"
        f"💡 <b>Bugungi tavsiya</b>\n{escape(welcome_suggestions.for_user(user_id))}\n\n"
        + action
    )


async def sync_bot_branding(bot):
    """Update default/Uzbek descriptions only when changed; failure is nonfatal."""
    synced = True
    for language in ("", "uz"):
        for field, text, read, write in (
            ("description", BOT_DESCRIPTION, bot.get_my_description, bot.set_my_description),
            ("short_description", BOT_SHORT_DESCRIPTION, bot.get_my_short_description, bot.set_my_short_description),
        ):
            try:
                current = await read(language_code=language, request_timeout=5)
                if getattr(current, field) != text:
                    await write(**{field: text}, language_code=language, request_timeout=5)
            except (TelegramAPIError, asyncio.TimeoutError) as error:
                logger.warning("Bot description sync unavailable (%s); will retry.", type(error).__name__)
                synced = False
    return synced


async def branding_worker(bot):
    while not await sync_bot_branding(bot):
        await asyncio.sleep(15 * 60)
