"""Small REST client; imports and grading use separate budgets."""

import json

import aiohttp
import config


class AIUnavailable(RuntimeError):
    pass


async def complete_json(messages, *, model, max_tokens, timeout):
    if not config.DEEPSEEK_API_KEY or config.DEEPSEEK_API_KEY.startswith("your_"):
        raise AIUnavailable("DeepSeek kaliti sozlanmagan.")
    payload = {
        "model": model, "messages": messages,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"}, "temperature": 0,
        "max_tokens": max_tokens,
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(
                config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"}, json=payload,
            ) as response:
                if response.status != 200:
                    # Never persist provider response bodies, URLs with credentials, or keys.
                    raise AIUnavailable(f"DeepSeek vaqtincha mavjud emas (HTTP {response.status}).")
                result = await response.json()
        choice = result["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise AIUnavailable("DeepSeek javobi to'liq emas. Importni qayta urinib ko'ring.")
        data = json.loads(choice["message"]["content"])
        if not isinstance(data, dict):
            raise ValueError("Expected JSON object")
        return data, result.get("usage", {})
    except AIUnavailable:
        raise
    except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as error:
        raise AIUnavailable("DeepSeek javobini olish yoki tekshirish imkoni bo'lmadi.") from error
