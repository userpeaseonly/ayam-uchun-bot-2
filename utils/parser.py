import re
from typing import Dict, Any, List, Tuple, Optional


class ParseError(Exception):
    """Custom exception for parsing errors with user-friendly Uzbek messages."""
    pass


def parse_admin_test_input(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Parses test configuration created by an admin.
    Returns: (title, list of questions)
    Each question dict:
        {
            'question_num': int,
            'question_type': 'closed' | 'open',
            'correct_answer': 'A' | 'B' | ... or None,
            'ai_instructions': str or None
        }
    """
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise ParseError("Test ma'lumotlari kiritilmadi!")

    title = "Yangi test"
    start_idx = 0

    # If first line is a command or title
    first_line = lines[0]
    if first_line.startswith("/newtest"):
        parts = first_line.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            title = parts[1].strip()
        start_idx = 1
    elif not re.match(r"^\d+[\.:\)\-]", first_line):
        title = first_line
        start_idx = 1

    content_text = "\n".join(lines[start_idx:])
    
    # Split questions by number prefix at line start or after delimiter
    # Pattern looks for: \d+ followed by separator
    pattern = re.compile(
        r"(?:^|[\n;])\s*(\d{1,2})\s*[\.:\)\-]\s*(.*?)(?=(?:[\n;]\s*\d{1,2}\s*[\.:\)\-]|\Z))",
        re.DOTALL
    )

    matches = pattern.findall(content_text)
    if not matches:
        # Fallback to comma separation if no newline matches
        pattern_comma = re.compile(
            r"(?:^|[,;])\s*(\d{1,2})\s*[\.:\)\-]\s*(.*?)(?=(?:[,;]\s*\d{1,2}\s*[\.:\)\-]|\Z))",
            re.DOTALL
        )
        matches = pattern_comma.findall(content_text)

    if not matches:
        raise ParseError(
            "Savollar formati noto'g'ri!\n"
            "Namuna:\n"
            "1. A\n2. B\n3. [OPEN] AI ko'rsatmasi...\n4. D"
        )

    parsed_questions: Dict[int, Dict[str, Any]] = {}
    open_count = 0

    for num_str, body in matches:
        q_num = int(num_str)
        body = body.strip()

        # Check if question is OPEN
        open_match = re.match(
            r"^(?:\[?(?:OPEN|OCHIQ)\]?|RUBRIC:?)\s*(?:[:|\-]\s*)?(.*)$",
            body,
            re.IGNORECASE | re.DOTALL
        )

        if open_match:
            instructions = open_match.group(1).strip()
            if not instructions:
                raise ParseError(f"{q_num}-savol ochiq savol deb belgilangan, lekin tekshirish ko'rsatmasi (rubric) kiritilmagan!")
            parsed_questions[q_num] = {
                "question_num": q_num,
                "question_type": "open",
                "correct_answer": None,
                "ai_instructions": instructions,
            }
            open_count += 1
        else:
            # Closed question: single letter (A, B, C, D, E)
            clean_ans = body.upper().strip()
            # In case teacher wrote "Variant A" or "A)"
            letter_match = re.search(r"\b([A-E])\b", clean_ans)
            if not letter_match:
                # If body is longer text without OPEN tag, assume teacher forgot [OPEN] tag
                if len(body) > 3:
                    raise ParseError(
                        f"{q_num}-savol javobi '{body}' tushunarsiz.\n"
                        f"Agar bu ochiq savol bo'lsa, 'OPEN | ko'rsatma...' ko'rinishida yozing.\n"
                        f"Yopiq savol bo'lsa, faqat A, B, C, D yoki E harfini kiriting."
                    )
                raise ParseError(f"{q_num}-savol uchun to'g'ri variant (A, B, C, D) topilmadi!")
            
            parsed_questions[q_num] = {
                "question_num": q_num,
                "question_type": "closed",
                "correct_answer": letter_match.group(1),
                "ai_instructions": None,
            }

    # Validate question counts
    total = len(parsed_questions)
    if total < 5:
        raise ParseError(f"Savollar soni kamida 5 ta bo'lishi kerak! (Hozir: {total} ta)")
    if total > 44:
        raise ParseError(f"Savollar soni ko'pi bilan 44 ta bo'lishi kerak! (Hozir: {total} ta)")
    if open_count > 9:
        raise ParseError(f"Ochiq savollar soni ko'pi bilan 9 ta bo'lishi mumkin! (Hozir: {open_count} ta)")

    # Check contiguous numbering 1 to total
    sorted_nums = sorted(parsed_questions.keys())
    expected = list(range(1, total + 1))
    if sorted_nums != expected:
        missing = set(expected) - set(sorted_nums)
        raise ParseError(f"Savollar ketma-ketligida kamchilik bor! Qolib ketgan raqamlar: {sorted(list(missing))}")

    return title, [parsed_questions[i] for i in expected]


def parse_student_answers(text: str, total_expected: int) -> Dict[int, str]:
    """
    Parses student answers from a message.
    Supports formats:
    - Multiline:
        1. A
        2. B
        3. Gulchexra suv ichdi
        4. D
    - Delimited:
        1:A, 2:B, 3:Gulchexra suv ichdi, 4:D
    Returns dict: {1: 'A', 2: 'B', 3: 'Gulchexra suv ichdi', ...}
    """
    raw = text.strip()
    if not raw:
        raise ParseError("Javoblar kiritilmadi!")

    # Regex matches: (number) [.:)-] (answer text until next number prefix or end)
    pattern = re.compile(
        r"(?:^|[\n,;])\s*(?:savol\s*)?(\d{1,2})\s*[\.:\)\-]\s*(.*?)(?=(?:[\n,;]\s*(?:savol\s*)?\d{1,2}\s*[\.:\)\-]|\Z))",
        re.IGNORECASE | re.DOTALL
    )

    matches = pattern.findall(raw)
    if not matches:
        raise ParseError(
            "Javoblar formati aniqlanmadi!\n"
            "Namuna:\n"
            "1. A\n2. B\n3. Ochiq savol javobi matni\n4. D\n"
            "yoki:\n"
            "1:A, 2:B, 3:ochiq javob, 4:D"
        )

    answers: Dict[int, str] = {}
    for num_str, ans_val in matches:
        q_num = int(num_str)
        ans = ans_val.strip()
        if not ans:
            continue
        # If single letter closed answer, normalize uppercase
        if len(ans) == 1 and ans.isalpha():
            ans = ans.upper()
        answers[q_num] = ans

    if not answers:
        raise ParseError("Hech qanday savol javobi aniqlanmadi!")

    return answers


def format_student_preview(
    answers: Dict[int, str], questions: List[Dict[str, Any]]
) -> Tuple[str, bool]:
    """
    Formats parsed answers into a confirmation preview text for the student.
    Returns (formatted_text, is_complete)
    """
    total = len(questions)
    missing = []
    lines = ["📝 <b>Kiritilgan javoblarni tekshiring:</b>\n"]

    for q in questions:
        q_num = q["question_num"]
        q_type = q["question_type"]
        if q_num in answers:
            ans = answers[q_num]
            type_badge = "<i>(ochiq)</i>" if q_type == "open" else ""
            # Escape HTML characters
            safe_ans = ans.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            lines.append(f"<b>{q_num}.</b> {safe_ans} {type_badge}")
        else:
            missing.append(q_num)
            lines.append(f"<b>{q_num}.</b> ⚠️ <i>[Javob berilmadi]</i>")

    is_complete = len(missing) == 0
    lines.append(f"\n📊 <b>Jami berilgan javoblar:</b> {len(answers)} / {total}")

    if missing:
        lines.append(
            f"⚠️ <b>Diqqat:</b> Quyidagi savollarga javob kiritilmadi: {', '.join(map(str, missing))}"
        )
    else:
        lines.append("✅ Barcha savollarga javob berildi.")

    return "\n".join(lines), is_complete
