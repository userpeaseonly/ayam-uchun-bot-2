import { describe, expect, it } from 'vitest';
import type { Question, TestDocument } from './types';
import { prepareReview, questionIssues } from './question-review';
import { isSaveShortcut } from './content-protection';

const choice = (): Question => ({ number: 1, kind: 'choice', text: 'Savol', options: [{ label: 'A', text: 'Ha' }, { label: 'B', text: 'Yo‘q' }],
  passage_id: null, parts: [], source_pages: [], media: [], answer: 'A', rubric: '', accepted_answers: [], points: 2.5, reviewed: false, warnings: [] });

describe('automatic teacher answer readiness', () => {
  it('marks a complete answer ready without a manual checkbox and keeps the input immutable', () => {
    const source: TestDocument = { version: 1, title: 'Test', passages: [], questions: [choice()], warnings: [] };
    expect(prepareReview(source).questions[0].reviewed).toBe(true);
    expect(source.questions[0].reviewed).toBe(false);
  });
  it.each([
    { answer: '' }, { answer: 'F' }, { text: ' ' }, { passage_id: 'missing' },
    { options: [{ label: 'A', text: '' }, { label: 'B', text: 'Ha' }] },
  ])('never treats incomplete content as reviewed: %o', patch => {
    const question = { ...choice(), ...patch, reviewed: true };
    expect(questionIssues(question, []).length).toBeGreaterThan(0);
  });
  it('requires a rubric for multipart open answers, while accepting simple exact answers', () => {
    const question: Question = { ...choice(), kind: 'open', options: [], answer: '', accepted_answers: ['suv'] };
    expect(questionIssues(question, [])).toEqual([]);
    question.parts = [{ id: 'a', prompt: 'Birinchi qism' }];
    expect(questionIssues(question, []).length).toBeGreaterThan(0);
    question.rubric = 'Barcha qismlar uchun mezon';
    expect(questionIssues(question, [])).toEqual([]);
  });
});

it('discourages page saving/printing without intercepting answer editing shortcuts', () => {
  expect(isSaveShortcut('s', true, false)).toBe(true);
  expect(isSaveShortcut('P', false, true)).toBe(true);
  expect(isSaveShortcut('s', false, false)).toBe(false);
  for (const key of ['c', 'v', 'x', 'a', 'z']) expect(isSaveShortcut(key, true, false)).toBe(false);
});
