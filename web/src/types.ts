export type Region = { page: number; x: number; y: number; width: number; height: number; asset_id: string };
export type Passage = { id: string; title: string; text: string; source_pages: number[]; media: Region[] };
export type Question = {
  number: number; kind: 'choice' | 'matching' | 'open'; text: string;
  options: { label: string; text: string }[]; passage_id: string | null;
  parts: { id: string; prompt: string }[]; source_pages: number[]; media: Region[];
  answer: string; rubric: string; accepted_answers: string[]; points: number;
  reviewed: boolean; warnings: string[];
};
export type TestDocument = { version: 1; title: string; passages: Passage[]; questions: Question[]; warnings: string[] };
export type ImportRecord = {
  id: string; title: string; status: string; progress: number; error: string | null;
  revision: number; document: TestDocument | null; published_test_id: number | null;
  assets: { id: string; kind: string; page: number; original_name: string }[];
};
export type TestSummary = { id: number; code: string; title: string; status: string; total_questions: number };
export type Answers = Record<string, string | Record<string, string>>;
export type Submission = { id: number; answers: { number: number; status: string; correct: boolean | null }[]; score?: number; rank?: number; total_correct?: number };
export type StudentQuestion = Pick<Question, 'number' | 'kind' | 'text' | 'options' | 'passage_id' | 'parts'> & { media: string[] };
export type StudentTest = {
  id: number; code: string; status: string; revision: number; draft: Answers; submission: Submission | null;
  document: { title: string; questions: StudentQuestion[]; passages: (Pick<Passage, 'id' | 'title' | 'text'> & { media: string[] })[] };
};
export type Results = {
  test: TestSummary;
  submissions: { id: number; first_name: string; last_name: string; user_id: number; total_correct: number; total_score: number; rank: number | null }[];
  answers: { id: number; submission_id: number; question_num: number; user_answer: string; is_correct: number; grading_status: string; ai_feedback: string | null }[];
  questions: { question_num: number; correct_count: number; assigned_points: number | null; assigned_tier: string | null }[];
};

declare global {
  interface Window {
    Telegram?: { WebApp: { initData: string; ready(): void; expand(): void; close(): void; openTelegramLink(url: string): void; enableClosingConfirmation(): void; disableClosingConfirmation(): void; initDataUnsafe?: { start_param?: string } } };
  }
}
