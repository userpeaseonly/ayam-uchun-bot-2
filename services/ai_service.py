import json
import logging
import aiohttp
from typing import Dict, Any, Tuple
import config

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self):
        self.provider = config.AI_PROVIDER

    async def evaluate_open_answer(
        self,
        question_num: int,
        rubric: str,
        student_answer: str
    ) -> Tuple[bool, str]:
        """
        Evaluates a student's open-ended answer against the teacher's rubric.
        Returns: (is_correct: bool, feedback: str)
        """
        if not student_answer or not student_answer.strip():
            return False, "Javob bo'sh qoldirilgan."

        system_prompt = (
            "Siz o'quvchilarning ochiq savollarga bergan javoblarini tekshiruvchi adolatli va professional ekspert-o'qituvchisiz.\n"
            "O'qituvchi tomonidan berilgan tekshirish ko'rsatmasi (rubric) asosida o'quvchining javobini xolis baholang.\n"
            "O'quvchi javobining mohiyati va mazmuni ko'rsatmaga mos kelsa, mayda orfografik yoki so'zlashuv xatolariga qaramasdan uni to'g'ri deb qabul qiling.\n"
            "Faqat quyidagi JSON formatida javob bering:\n"
            '{\n  "is_correct": true yoki false,\n  "explanation": "Natija haqida qisqa izoh (o\'zbek tilida)"\n}'
        )

        user_content = (
            f"Savol raqami: {question_num}\n"
            f"O'qituvchi ko'rsatmasi (Rubric): {rubric}\n"
            f"O'quvchining javobi: {student_answer}\n"
        )

        try:
            if self.provider == "deepseek" and config.DEEPSEEK_API_KEY:
                return await self._call_deepseek(system_prompt, user_content)
            elif self.provider == "gemini" and config.GEMINI_API_KEY:
                return await self._call_gemini(system_prompt, user_content)
            elif config.DEEPSEEK_API_KEY:
                return await self._call_deepseek(system_prompt, user_content)
            elif config.GEMINI_API_KEY:
                return await self._call_gemini(system_prompt, user_content)
            else:
                logger.warning("No AI API keys configured. Simulating fallback evaluation.")
                return True, "Avtomatik qabul qilindi (AI kalit o'rnatilmagan)."
        except Exception as e:
            logger.error(f"Error evaluating answer with AI: {e}", exc_info=True)
            return False, f"AI tekshiruvida xatolik yuz berdi: {str(e)[:50]}"

    async def _call_deepseek(self, system_prompt: str, user_content: str) -> Tuple[bool, str]:
        url = f"{config.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 250,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=25) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    content = res_json["choices"][0]["message"]["content"]
                    data = json.loads(content)
                    return bool(data.get("is_correct", False)), str(data.get("explanation", ""))
                else:
                    err_text = await resp.text()
                    logger.error(f"DeepSeek API returned {resp.status}: {err_text}")
                    return False, f"DeepSeek xatosi: {resp.status}"

    async def _call_gemini(self, system_prompt: str, user_content: str) -> Tuple[bool, str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": system_prompt + "\n\n" + user_content}
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2
            }
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=25) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    data = json.loads(raw_text)
                    return bool(data.get("is_correct", False)), str(data.get("explanation", ""))
                else:
                    err_text = await resp.text()
                    logger.error(f"Gemini API returned {resp.status}: {err_text}")
                    return False, f"Gemini xatosi: {resp.status}"


ai_evaluator = AIService()
