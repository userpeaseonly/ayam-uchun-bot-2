export type Region = { page: number; x: number; y: number; width: number; height: number; asset_id: string };
export type Passage = { id: string; title: string; text: string; source_pages: number[]; media: Region[] };
export type Question = {
  number: number; kind: 'choice' | 'matching' | 'open'; text: string;
  options: { label: string; text: string }[]; passage_id: string | null;
  parts: { id: string; prompt: string }[]; source_pages: number[]; media: Region[];
  answer: string; rubric: string; accepted_answers: string[]; points: number;
  explanation_audio?: string;
  reviewed: boolean; warnings: string[];
};
export type TestDocument = { version: 1; title: string; passages: Passage[]; questions: Question[]; warnings: string[] };
export type ImportRecord = {
  id: string; title: string; status: string; progress: number; error: string | null;
  duration_minutes: number | null; visibility: Visibility; subject: string; revision: number; document: TestDocument | null; published_test_id: number | null;
  assets: { id: string; kind: string; page: number; original_name: string }[];
};
export type Visibility = 'public' | 'unlisted';
export type Profile = { full_name: string };
export type TestSummary = { id: number; public_id: string; code: string; title: string; status: string; total_questions: number;
  duration_minutes: number | null; active_attempts?: number; open_questions_count: number; visibility: Visibility; subject: string; publisher_name: string; created_at: string;
  share_url: string; template_id: number | null; standard_price_uzs: number; submission_id: number | null; draft_revision: number | null; score: number | null; rank: number | null };
export type TeacherCounts = { total: number; active: number; review: number };
export type CatalogPage = { counts?: TeacherCounts; items: TestSummary[]; next_cursor: number | null; subjects: string[] };
export type Answers = Record<string, string | Record<string, string>>;
export type Submission = { id: number; auto_submitted?: boolean; answers: { number: number; status: string; correct: boolean | null; explanation_audio_url?: string }[]; score?: number; rank?: number; total_correct?: number };
export type StudentQuestion = Pick<Question, 'number' | 'kind' | 'text' | 'options' | 'passage_id' | 'parts'> & { media: string[] };
export type AttemptTimer = { started_at: number; deadline_at: number; server_now: number };
export type StudentTest = {
  timer: AttemptTimer | null;
  id: number; public_id: string; publisher_name: string; code: string; status: string; revision: number; draft: Answers; submission: Submission | null;
  document: { title: string; questions: StudentQuestion[]; passages: (Pick<Passage, 'id' | 'title' | 'text'> & { media: string[] })[] };
};
export type Results = {
  test: TestSummary;
  submissions: { id: number; first_name: string; last_name: string; user_id: number; total_correct: number; total_score: number; rank: number | null }[];
  answers: { id: number; submission_id: number; question_num: number; user_answer: string; is_correct: number; grading_status: string; ai_feedback: string | null }[];
  questions: { question_num: number; correct_count: number; assigned_points: number | null; assigned_tier: string | null }[];
};

export type InvoiceStatus = 'paid' | 'cancelled' | 'failed' | 'pending';
export type PaymentOrder = {
  id: string; amount: number; currency: 'XTR'; purpose: string; environment: 'test' | 'live';
  created_at: number; expires_at: number; invoice_url: string | null;
  status: 'created' | 'invoice_ready' | 'invoice_failed' | 'checkout' | 'paid' | 'refund_pending' | 'refunded' | 'expired';
};
export type PaymentHistory = {
  settings: { enabled: boolean; environment: 'test' | 'live'; amount: number; currency: 'XTR'; terms_version: string; terms_text: string; support_url: string | null };
  orders: PaymentOrder[];
  additional_payments: { amount: number; status: string; received_at: number }[];
};

declare global {
  interface Window {
    Telegram?: { WebApp: { initData: string; ready(): void; expand(): void; close(): void; openTelegramLink(url: string): void; openInvoice?(url: string, callback?: (status: InvoiceStatus) => void): void; enableClosingConfirmation(): void; disableClosingConfirmation(): void; setHeaderColor?(color: string): void; setBackgroundColor?(color: string): void; BackButton?: { show(): void; hide(): void; onClick(callback: () => void): void; offClick(callback: () => void): void }; initDataUnsafe?: { start_param?: string } } };
  }
}
