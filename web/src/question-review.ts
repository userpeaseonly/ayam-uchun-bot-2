import type { Question, TestDocument } from './types';

export function questionIssues(question: Question, passageIds: string[]): string[] {
  const issues: string[] = [];
  if (!question.text.trim()) issues.push('Savol matnini kiriting.');
  if (question.passage_id && !passageIds.includes(question.passage_id)) issues.push('Umumiy matnni tanlang.');
  if (question.kind !== 'open') {
    if (question.options.length < 2) issues.push('Kamida ikkita variant kerak.');
    if (!question.answer || !question.options.some(option => option.label === question.answer)) issues.push('To‘g‘ri javobni tanlang.');
    if (question.parts.length) issues.push('Variantli savolda a/b qismlar bo‘lmaydi.');
    if (!question.media.length && question.options.some(option => !option.text.trim())) issues.push('Variantlar matnini to‘ldiring.');
  } else {
    if (question.options.length) issues.push('Ochiq savoldan variantlarni olib tashlang.');
    if (!question.rubric.trim() && !question.accepted_answers.some(answer => answer.trim())) issues.push('Javob yoki tekshirish mezonini kiriting.');
    if (question.parts.length && !question.rubric.trim()) issues.push('Barcha qismlar uchun tekshirish mezonini kiriting.');
  }
  return issues;
}

export function prepareReview(document: TestDocument): TestDocument {
  const ids = document.passages.map(passage => passage.id);
  return { ...document, questions: document.questions.map(question => ({ ...question, reviewed: questionIssues(question, ids).length === 0 })) };
}
