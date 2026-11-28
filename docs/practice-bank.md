# Mavzulashtirilgan: Basirat exam-position practice

Students enter **Testlar → Mavzulashtirilgan**, choose an original exam question
number, and work through questions with that number from different curated
papers. Numbers mean exam positions, not linguistic topics. The grid runs from
1 to the highest published number (currently the document schema supports 44),
with empty positions disabled and question counts per tile.

## Publishing and brand permissions

1. Upload a PDF/photos through the existing bot or Mini App flow.
2. Review questions, correct answers, accepted answers/rubrics, shared passages
   and optional voice explanations, then publish the test as usual.
3. An account listed in `ADMIN_IDS` opens its test in **O‘qituvchi kabineti**,
   expands **Mavzulashtirilgan**, and enables **Basirat mashqlarida ko‘rsatish**.

Only brand-admin-owned, reviewed document tests can be curated. Normal teachers
cannot publish to the brand bank; their normal public/unlisted exams continue
to work. Adding to practice is explicit and does not happen automatically.
Curators must intentionally release answers for practice, including when an
exam session is still active. The publication control explains that solutions,
open-answer criteria and voice explanations become accessible after checking.

One frozen source per `(bank, template)` avoids duplicating a paper when a new
exam session reuses its template. Republishing that template re-enables its
existing practice items. Unpublishing hides its questions and media immediately
for subsequent requests while retaining private drafts/check history.
Corrections should currently be imported and reviewed as a new paper/version;
editing an exam does not silently change an already-curated practice snapshot.

`practice_banks` has brand/teacher kind and optional owner fields to support
future teacher collections. Only the single `basirat` bank is currently exposed;
there is no student collection selector or teacher-bank API yet.

## Student behavior

- One question at a time; Previous/Next stay within the selected original exam
  number. Paper title and publisher full name identify each question's source.
- Shared passage text/images come from that specific paper, even when passage
  identifiers match across different papers.
- No timer, final submission, Rasch score, leaderboard, or exam attempt is created.
  Questions may be skipped, revisited and repeated indefinitely.
- Drafts auto-save with revisions; navigation awaits saving. Each number remembers
  the last opened item. Grid progress is based on completed checks; correctness
  is the latest completed result for that student/item, not aggregate student data.
- **Javobni tekshirish** submits just the current answer. Multiple parts must be
  complete. Choice and exact accepted answers are checked locally. Other open
  answers use the existing DeepSeek/Gemini rubric evaluator and bounded durable
  background workers. Pending/error states never become false incorrect grades.
- Checking reveals the correct option, accepted answers or open-answer rubric,
  plus optional recorded izoh. Feedback is immediate for local checks; AI checks
  poll until completion and offer retry after background retry exhaustion.
- **Qayta ishlash** clears the draft/current result pointer, so restarting and
  reopening continue the new attempt rather than showing an older check.

## Safety and persistence

Migration 8 adds bank/source/item snapshots, per-user drafts, immutable checks,
and per-number resume positions. Regular exam data remains untouched. Checks
use per-user request keys for retry idempotency; draft writes use optimistic
revisions inside `BEGIN IMMEDIATE` transactions. Duplicate HTTP requests cannot
create duplicate grading jobs. Check requests are limited to 30 per user/minute.

The API requires the existing signed session and same-origin write protection.
Solutions are omitted before that student's current check. Dedicated asset
routes serve only referenced crops, and voice only after that student has checked
that item. Knowing another student's check or an asset ID grants no access.
Original PDFs/source pages are never served through practice endpoints. Turning
off a source also revokes its practice media routes. Existing content-protection
deterrents/custom audio player are reused; browsers cannot guarantee screenshot
or download prevention.

`practice_grade` jobs use the current claim/retry/recovery machinery. Failed
checks can be requeued by their owner without adding another check or altering
normal exam grades. Completed checks survive restart; no paid provider calls
are made when opening the grid or a question.

Tests cover curation permissions, template deduplication, per-paper passages,
resume, repeat persistence, reveal/media gates, cross-user isolation, stale
drafts, idempotency, exact-answer grading, AI outage/recovery, HTTP CSRF, source
revocation, and 100 simultaneous students checking the same practice question.
