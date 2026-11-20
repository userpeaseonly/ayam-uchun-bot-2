"""Container startup validation; local development can still use main.py."""

import asyncio

import config


def validate_configuration():
    missing = []
    if not config.BOT_TOKEN or config.BOT_TOKEN == "your_telegram_bot_token_here":
        missing.append("BOT_TOKEN")
    if not config.ADMIN_IDS:
        missing.append("ADMIN_IDS")
    providers = {
        "deepseek": ("DEEPSEEK_API_KEY", config.DEEPSEEK_API_KEY),
        "gemini": ("GEMINI_API_KEY", config.GEMINI_API_KEY),
    }
    if config.AI_PROVIDER not in providers:
        raise ValueError("AI_PROVIDER must be deepseek or gemini")
    key_name, key_value = providers[config.AI_PROVIDER]
    if not key_value or key_value.startswith("your_"):
        missing.append(key_name)
    if missing:
        raise ValueError("Missing container configuration: " + ", ".join(missing))


if __name__ == "__main__":
    validate_configuration()
    from main import main

    asyncio.run(main())
