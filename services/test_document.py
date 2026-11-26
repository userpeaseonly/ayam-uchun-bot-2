"""Versioned test content, independent of Telegram and the AI provider."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Region(ContentModel):
    page: int = Field(ge=1, le=30)
    x: float = Field(default=0, ge=0, lt=1)
    y: float = Field(default=0, ge=0, lt=1)
    width: float = Field(default=1, gt=0, le=1)
    height: float = Field(default=1, gt=0, le=1)
    asset_id: str = ""

    @model_validator(mode="after")
    def bounds(self):
        if self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise ValueError("Rasm chegarasi sahifadan tashqarida")
        return self


class Option(ContentModel):
    label: str = Field(pattern=r"^[A-F]$")
    text: str = Field(max_length=10000)


class Part(ContentModel):
    id: str = Field(pattern=r"^[a-z]$")
    prompt: str = Field(min_length=1, max_length=10000)


class Passage(ContentModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    title: str = Field(default="", max_length=300)
    text: str = Field(default="", max_length=100000)
    source_pages: list[int] = Field(default_factory=list, max_length=30)
    media: list[Region] = Field(default_factory=list, max_length=20)


class Question(ContentModel):
    number: int = Field(ge=1, le=44)
    kind: Literal["choice", "matching", "open"]
    text: str = Field(min_length=1, max_length=20000)
    options: list[Option] = Field(default_factory=list, max_length=6)
    passage_id: str | None = None
    parts: list[Part] = Field(default_factory=list, max_length=6)
    source_pages: list[int] = Field(default_factory=list, max_length=30)
    media: list[Region] = Field(default_factory=list, max_length=20)
    answer: str = Field(default="", max_length=10)
    rubric: str = Field(default="", max_length=20000)
    accepted_answers: list[str] = Field(default_factory=list, max_length=50)
    explanation_audio: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    points: float = Field(default=2.5, gt=0, le=100)
    reviewed: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("accepted_answers")
    @classmethod
    def nonempty_accepted_answers(cls, values):
        return [value.strip() for value in values if value.strip()]

    @model_validator(mode="after")
    def unique_labels(self):
        labels = [o.label for o in self.options]
        parts = [p.id for p in self.parts]
        if len(labels) != len(set(labels)) or len(parts) != len(set(parts)):
            raise ValueError("Takroriy variant yoki qism belgisi")
        return self


    def readiness_errors(self, passage_ids: set[str]) -> list[str]:
        errors = []
        if not self.text.strip():
            errors.append("savol matni bo'sh.")
        if self.passage_id and self.passage_id not in passage_ids:
            errors.append("umumiy matn topilmadi.")
        if self.kind != "open":
            if len(self.options) < 2 or self.answer not in [o.label for o in self.options]:
                errors.append("variantlar va to'g'ri javobni kiriting.")
            if self.parts:
                errors.append("qismlar faqat ochiq savolda mumkin.")
            if any(not o.text.strip() for o in self.options) and not self.media:
                errors.append("bo'sh variantlarga matn yoki rasm kerak.")
        elif self.options or (not self.rubric.strip() and not self.accepted_answers):
            errors.append("ochiq savol mezonini kiriting va variantlarni olib tashlang.")
        if self.parts and not self.rubric.strip():
            errors.append("barcha qismlar uchun umumiy tekshirish mezoni kerak.")
        return errors


class TestDocument(ContentModel):
    version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=300)
    passages: list[Passage] = Field(default_factory=list, max_length=44)
    questions: list[Question] = Field(default_factory=list, max_length=44)
    warnings: list[str] = Field(default_factory=list, max_length=100)

    def publication_errors(self) -> list[str]:
        errors = []
        numbers = sorted(q.number for q in self.questions)
        if not 5 <= len(numbers) <= 44 or numbers != list(range(1, len(numbers) + 1)):
            errors.append("5–44 savol bo'lishi va raqamlar 1 dan uzluksiz kelishi kerak.")
        if sum(q.kind == "open" for q in self.questions) > 9:
            errors.append("Ko'pi bilan 9 ta ochiq savol mumkin; qismlar alohida savol emas.")
        ids = [p.id for p in self.passages]
        if len(ids) != len(set(ids)):
            errors.append("Matn identifikatorlari takrorlangan.")
        for q in self.questions:
            prefix = f"{q.number}-savol: "
            if not q.reviewed:
                errors.append(prefix + "savol va javob mezoni tasdiqlanmagan.")
            errors.extend(prefix + error for error in q.readiness_errors(set(ids)))
        if not self.title.strip():
            errors.append("Test nomi bo'sh.")
        return errors


def normalize_answer(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold().translate(str.maketrans("‘’ʻʼ`", "'''''")))


def student_document(document: dict) -> dict:
    """Explicit allowlist: never send keys, rubrics, warnings or source pages."""
    parsed = TestDocument.model_validate(document)
    return {
        "title": parsed.title,
        "passages": [
            {"id": p.id, "title": p.title, "text": p.text,
             "media": [m.asset_id for m in p.media if m.asset_id]}
            for p in parsed.passages
        ],
        "questions": [
            {"number": q.number, "kind": q.kind, "text": q.text,
             "options": [o.model_dump() for o in q.options], "passage_id": q.passage_id,
             "parts": [p.model_dump() for p in q.parts],
             "media": [m.asset_id for m in q.media if m.asset_id]}
            for q in sorted(parsed.questions, key=lambda q: q.number)
        ],
    }
