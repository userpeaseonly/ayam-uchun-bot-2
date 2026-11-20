import pytest
from utils.parser import (
    parse_admin_test_input,
    parse_student_answers,
    format_student_preview,
    ParseError,
)


def test_admin_parser_valid_standard():
    raw_text = """
    DTM Tayyorgarlik 1-variant
    1. A
    2. B
    3. C
    4. [OPEN] O'quvchi ma'nosini tushuntirishi lozim
    5. D
    """
    title, questions = parse_admin_test_input(raw_text)
    assert title == "DTM Tayyorgarlik 1-variant"
    assert len(questions) == 5
    assert questions[0]["question_num"] == 1
    assert questions[0]["question_type"] == "closed"
    assert questions[0]["correct_answer"] == "A"

    assert questions[3]["question_num"] == 4
    assert questions[3]["question_type"] == "open"
    assert questions[3]["correct_answer"] is None
    assert "tushuntirishi" in questions[3]["ai_instructions"]


def test_admin_parser_minimum_questions_limit():
    raw_text = """
    Test Title
    1. A
    2. B
    3. C
    4. D
    """
    with pytest.raises(ParseError, match="kamida 5 ta"):
        parse_admin_test_input(raw_text)


def test_admin_parser_maximum_questions_limit():
    lines = ["Test Title"] + [f"{i}. A" for i in range(1, 46)]
    with pytest.raises(ParseError, match="ko'pi bilan 44 ta"):
        parse_admin_test_input("\n".join(lines))


def test_admin_parser_maximum_open_questions():
    # 10 open questions out of 15
    lines = ["Test Title"]
    for i in range(1, 11):
        lines.append(f"{i}. [OPEN] Rubric {i}")
    for i in range(11, 16):
        lines.append(f"{i}. A")

    with pytest.raises(ParseError, match="ko'pi bilan 9 ta"):
        parse_admin_test_input("\n".join(lines))


def test_student_parser_multiline():
    text = """
    1. A
    2. B
    3. Gulchexra suv ichdi
    4. C
    5. Olmaning tagi oltin
    """
    res = parse_student_answers(text, 5)
    assert res[1] == "A"
    assert res[2] == "B"
    assert res[3] == "Gulchexra suv ichdi"
    assert res[4] == "C"
    assert res[5] == "Olmaning tagi oltin"


def test_student_parser_comma_delimited():
    text = "1:A, 2:B, 3:D, 4:gulchexra suv ichdi, 5:olmaning tagi oltin"
    res = parse_student_answers(text, 5)
    assert res[1] == "A"
    assert res[2] == "B"
    assert res[3] == "D"
    assert res[4] == "gulchexra suv ichdi"
    assert res[5] == "olmaning tagi oltin"


def test_student_parser_mixed_punctuation():
    text = "1) A, 2 - b; 3. C, 4: Toshkent, O'zbekiston, 5. d"
    res = parse_student_answers(text, 5)
    assert res[1] == "A"
    assert res[2] == "B"  # Normalized uppercase
    assert res[3] == "C"
    assert res[4] == "Toshkent, O'zbekiston"
    assert res[5] == "D"


def test_format_student_preview():
    questions = [
        {"question_num": 1, "question_type": "closed"},
        {"question_num": 2, "question_type": "closed"},
        {"question_num": 3, "question_type": "open"},
    ]
    answers = {1: "A", 3: "Ochiq javob"}
    preview, is_complete = format_student_preview(answers, questions)
    assert not is_complete
    assert "<b>2.</b> ⚠️ <i>[Javob berilmadi]</i>" in preview
    assert "Ochiq javob" in preview


def test_student_parser_user_exact_sample():
    text = "1:A, 2:B, 3:D, 4: qizil ishton keldi, 5: D, 6:A, 7:A, 8: daraxtdan darak tushdi."
    res = parse_student_answers(text, 8)
    assert res[1] == "A"
    assert res[2] == "B"
    assert res[3] == "D"
    assert res[4] == "qizil ishton keldi"
    assert res[5] == "D"
    assert res[6] == "A"
    assert res[7] == "A"
    assert res[8] == "daraxtdan darak tushdi."

