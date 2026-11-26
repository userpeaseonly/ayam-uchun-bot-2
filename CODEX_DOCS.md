# Ayam Uchun Bot 2: Technical Specification & Codex Developer Guide

> **Target Audience:** Developers and AI Coding Assistants (ChatGPT, OpenAI Codex, Claude, GitHub Copilot) building upon or extending `ayam-uchun-bot-2`.

---

## 1. Project Overview & Business Domain

`ayam-uchun-bot-2` is an educational assessment platform running on Telegram. It is built in Python with **aiogram 3**, **aiosqlite**, and **aiohttp** (for DeepSeek/Gemini LLM calls).

### Core Problem Solved
Traditional Telegram quiz bots only handle closed multiple-choice questions with flat points (e.g. 1 point each). This bot:
1. **Dynamic 3-Tier Difficulty Scoring**: Automatically scales closed question points (1.1, 1.7, 2.5 points) after all students submit, based on the real success rate across the cohort. Easiest questions earn 1.1 pts; hardest questions earn 2.5 pts.
2. **AI-Graded Open Questions**: Allows up to 9 open-ended text questions evaluated in Uzbek by DeepSeek / Gemini AI according to a custom teacher rubric.
3. **Student-Friendly Submissions**: Parses answers flexibly from a single message (e.g. `1:A, 2:B, 3:D, 4: qizil ishton keldi...`).
4. **Two-Stage Reveal**: Students get immediate ✅/❌ feedback upon submission, but exact points and leaderboard rankings remain hidden until the teacher officially finishes the test.

---

## 2. System Architecture & Flow

```mermaid
flowchart TD
    Admin[Teacher / Admin] -->|/newtest or Excel Upload| Bot[Telegram Bot Engine]
    Bot -->|Generates Code e.g. T-7620| DB[(SQLite Database)]
    
    Student[Student] -->|1. Enters T-7620| Bot
    Student -->|2. Submits answers in 1 message| Bot
    Bot -->|3. Regex lenient parser + Preview| Student
    Student -->|4. Confirms submission| Bot
    Bot -->|5. Closed: instant key check\nOpen: aiohttp -> DeepSeek AI| AIService[AI Evaluation Service]
    Bot -->|6. Immediate Right/Wrong feedback| Student
    
    Admin -->|7. Clicks 'Testni yakunlash'| Scoring[Dynamic Scoring Engine]
    Scoring -->|8. Sorts closed questions into tertiles\n1.1, 1.7, 2.5 pts| DB
    Scoring -->|9. Computes student totals & ranks| DB
    Scoring -->|10. Generates 3-sheet Excel .xlsx| Excel[Excel Service]
    Bot -->|11. Sends Excel report & summary| Admin
    Bot -->|12. Broadcasts final rank & score| Student
```

---

## 3. Database Schema & Architecture (`scripts/database/`)

### Database Engine
- **Engine:** SQLite with WAL mode (`PRAGMA journal_mode = WAL;`) and Foreign Key enforcement (`PRAGMA foreign_keys = ON;`).
- **Connection Timeout:** 60.0s with `PRAGMA busy_timeout = 60000;`.
- **Async Driver:** `aiosqlite`.

```mermaid
erDiagram
    TESTS ||--o{ QUESTIONS : contains
    TESTS ||--o{ SUBMISSIONS : has
    SUBMISSIONS ||--o{ ANSWERS : includes
    QUESTIONS ||--o{ ANSWERS : evaluated_by

    TESTS {
        int id PK
        string code UK "e.g. T-7620"
        string title
        int created_by "Admin Telegram ID"
        int total_questions "5 to 44"
        int open_questions_count "0 to 9"
        string status "'active' or 'finished'"
        timestamp created_at
        timestamp finished_at
    }

    QUESTIONS {
        int id PK
        int test_id FK
        int question_num "1 to total_questions"
        string question_type "'closed' or 'open'"
        string correct_answer "A, B, C, D (for closed)"
        string ai_instructions "Teacher rubric (for open)"
        string assigned_tier "'easy', 'medium', 'hard', 'open'"
        real assigned_points "1.1, 1.7, 2.5 or 2.5 (open)"
        int correct_count "Number of students who solved it"
    }

    SUBMISSIONS {
        int id PK
        int test_id FK
        int user_id "Student Telegram ID"
        string first_name
        string last_name
        string username
        int total_correct
        real total_score
        int rank
        timestamp submitted_at
    }

    ANSWERS {
        int id PK
        int submission_id FK
        int question_id FK
        string user_answer
        int is_correct "1 = correct, 0 = wrong"
        real points_awarded
        string ai_feedback "AI explanation in Uzbek"
    }
```

### Database Connection Management Rules
> [!IMPORTANT]
> Always use `async with get_db_connection() as db:` from `scripts.database.db` in [`scripts/database/db.py`](scripts/database/db.py).  
> **NEVER** use `async with await aiosqlite.connect(...)` because in `aiosqlite`, calling `__aenter__` on an already-started connection triggers `RuntimeError: threads can only be started once`.  
> Always use `batch_update_...` methods with `executemany` when updating multiple rows.

---

## 4. Dynamic 3-Tier Scoring Algorithm (`services/scoring_service.py`)

### Tertile Distribution Formula
When an admin finishes a test (`finish_test:<test_id>`):
1. Count the number of correct student submissions for each closed question: $C_q$.
2. Sort closed questions in **descending order of $C_q$** (easiest questions with highest accuracy first). Tie-break by `question_num` ascending.
3. Divide the sorted closed questions ($N_{closed}$) into 3 tertiles:
   - `base_size = N_closed // 3`
   - `remainder = N_closed % 3`
   - `easy_count = base_size + (1 if remainder >= 1 else 0)`
   - `medium_count = base_size + (1 if remainder == 2 else 0)`
   - `hard_count = N_closed - easy_count - medium_count`
4. **Point Assignment**:
   - **Top 1/3 (Indices `0` to `easy_count - 1`):** `tier = 'easy'`, **1.1 points**
   - **Middle 1/3 (Indices `easy_count` to `easy_count + medium_count - 1`):** `tier = 'medium'`, **1.7 points**
   - **Bottom 1/3 (Remaining questions):** `tier = 'hard'`, **2.5 points**
5. **Open Questions**:
   - Open questions get fixed points (default `2.5` points, or admin-specified `assigned_points`) if `is_correct == 1`.
6. **Student Total & Ranks**:
   $$\text{total\_score} = \sum_{q \in \text{correct\_answers}} \text{assigned\_points}_q$$
   Submissions are ranked descending by `total_score`, then descending by `total_correct`.

---

## 5. Answer Parser Engine (`utils/parser.py`)

The bot accepts flexible formats from students to minimize typing friction:

### Accepted Student Formats
1. **Multiline Format**:
   ```text
   1. A
   2. B
   3. D
   4. qizil ishton keldi
   5. C
   ```
2. **Delimited Single-Line (User's Favorite)**:
   ```text
   1:A, 2:B, 3:D, 4: qizil ishton keldi, 5: D, 6:A, 7:A, 8: daraxtdan darak tushdi.
   ```
3. **Punctuation Variations**:
   `1) A`, `1 - B`, `1.A`, `1: A`. Open-ended text answers can contain internal commas, dots, and Uzbek letters (`o'`, `g'`, `sh`, `ch`).

### Regex Pattern
```python
pattern = re.compile(
    r"(?:^|[\n,;])\s*(?:savol\s*)?(\d{1,2})\s*[\.:\)\-]\s*(.*?)(?=(?:[\n,;]\s*(?:savol\s*)?\d{1,2}\s*[\.:\)\-]|\Z))",
    re.IGNORECASE | re.DOTALL
)
```

### Admin Test Creation Parser
Admin creates tests via text:
```text
Matematika va Ona tili
1. A
2. B
3. C
4. [OPEN] O'quvchi fe'l so'z turkumiga 2 ta misol keltirishi shart.
5. D
```
- Total questions must be between **5 and 44**.
- Maximum **9 open questions** allowed.
- Must have contiguous numbering from `1` to `N`.

---

## 6. AI Evaluation Service (`services/ai_service.py`)

- **Protocol:** Direct REST call via `aiohttp.ClientSession` to `https://api.deepseek.com/v1/chat/completions` (or Google Gemini API fallback).
- **Why no `openai` SDK?** Avoids heavy binary dependencies (`jiter`, Rust wheels) that fail on older server environments (e.g. Python 3.8). `aiohttp` is already bundled with `aiogram`.
- **System Prompt**: Instructs the LLM in Uzbek to act as an impartial examiner. It accepts minor spelling mistakes if the core meaning matches the teacher's rubric.
- **Output Schema**:
  ```json
  {
    "is_correct": true,
    "explanation": "Qisqa izoh (o'zbek tilida)"
  }
  ```

---

## 7. Telegram FSM States & Routing

### State Machine (`states.py`)
```python
class AdminStates(StatesGroup):
    waiting_for_test_input = State()

class StudentStates(StatesGroup):
    waiting_for_test_code = State()
    waiting_for_answers = State()
    confirming_submission = State()
```

### Handler Responsibilities
| File | Main Responsibilities |
| :--- | :--- |
| [`handlers/common.py`](file:///home/dragonfire/Desktop/Projects/ayam-uchun-bot-2/handlers/common.py) | `/start`, `/help`, main menu reply keyboard, cancel handlers. |
| [`handlers/admin.py`](file:///home/dragonfire/Desktop/Projects/ayam-uchun-bot-2/handlers/admin.py) | `/newtest`, Excel template upload, `/tests` dashboard, `finish_test:<id>`, `download_excel:<id>`. |
| [`handlers/student.py`](file:///home/dragonfire/Desktop/Projects/ayam-uchun-bot-2/handlers/student.py) | `✍️ Test topshirish`, direct `T-XXXX` test code detection, answer intake, preview confirmation, immediate feedback. |

---

## 8. Critical Guidelines for Codex / AI Assistants

When extending or modifying this project, Codex / ChatGPT **must strictly follow these rules**:

1. **Python 3.12+ Regex Rule:**
   - **Never** place inline flags after `^` (e.g. `r"^(?i)abc"`). Python 3.12 raises `re.error: global flags not at the start of the expression`.
   - Use explicit character sets like `r"^([tT]-)?\d{4,6}$"` instead.
2. **Database Connection Pattern:**
   - Always:
     ```python
     async with get_db_connection() as db:
         await db.execute(...)
         await db.commit()
     ```
   - Do **NOT** use `async with await get_db_connection()`!
3. **No Heavy SDKs for AI:**
   - Keep `services/ai_service.py` using `aiohttp`. Do not re-add `import openai` or `pip install openai`.
4. **Preserve One-Submission-Per-Student Lock:**
   - Once a student confirms their answers, `get_submission(test_id, user_id)` must prevent duplicate submissions.
5. **Testing Verification:**
   - Any new feature must pass the pytest test suite:
     ```bash
     .venv/bin/pytest tests/ -v
     ```
   - Original test coverage: 22 automated tests covering parsing, scoring, Excel, AI evaluation, SQLite backups, container configuration, and deployment failure handling.

---

## 9. File Tree & Resource Map

```
/home/dragonfire/Desktop/Projects/ayam-uchun-bot-2/
├── .env.example              # Template for environment variables
├── requirements.txt          # Minimal, pinned dependencies
├── config.py                 # Centralized configuration & environment loader
├── states.py                 # FSM states (AdminStates, StudentStates)
├── main.py                   # Entry point, router inclusion & polling dispatcher
├── scripts/database/
│   ├── db.py                 # SQLite connection manager with WAL mode
│   └── models.py             # CRUD operations (tests, questions, submissions, answers)
├── services/
│   ├── ai_service.py         # Async REST evaluator for open questions (DeepSeek/Gemini)
│   ├── scoring_service.py    # Analytics & 3-tier tertile distribution (1.1, 1.7, 2.5 pts)
│   └── excel_service.py      # openpyxl 3-sheet report generator
├── handlers/
│   ├── common.py             # /start, /help, main navigation
│   ├── admin.py              # Test creation, management, scoring, and report export
│   └── student.py            # Test code intake, answer parser, preview, immediate scoring
├── keyboards/
│   ├── reply.py              # Main menu keyboards
│   └── inline.py             # Submission confirmation & admin control buttons
├── utils/
│   └── parser.py             # Regex parsers for student answers and admin input
└── tests/
    ├── test_parser.py        # Unit tests for text & punctuation parsing
    ├── test_scoring.py       # Unit tests for tertile scoring & DB integration
    ├── test_excel.py         # Verification for .xlsx generation
    └── test_ai_service.py    # Mock tests for AI evaluation
```

## 10. Deployment Decision

Deploy to one Hetzner Linux server with Docker Compose using prebuilt Docker Hub
images selected by digest. GitHub Actions builds and tests releases; production
does not build source. `compose.dev.yaml` is a separate local build definition.
The production runtime is Python 3.14 with constrained dependencies, a non-root
container user, persistent SQLite/report storage, and rotating container logs.

See the deployment section in [README.md](README.md) for registry configuration,
server setup, deployment, backups, rollback, and the remaining production
readiness work. Deployment scaffolding is implemented; reliable interruption
recovery, durable grading/delivery, and versioned migrations remain prerequisites
for production assessments.


## 11. Mini App architecture

The app now hosts an aiohttp API alongside aiogram polling, plus React/TypeScript
assets built by Vite. See `services/web_app.py` for routes,
`services/telegram_auth.py` for verified Telegram identity, and
`services/platform_service.py` for transactional publication/submission/draft
operations. `services/test_document.py` defines version 1 question content:
passages, A–F options, matching, open subparts, source pages and diagram regions.
Published test content is immutable. Teachers must approve each question and key.

DeepSeek extraction (`services/import_service.py`) renders PDFs through Poppler,
normalizes photos with Pillow, and uses `deepseek-flash` vision via aiohttp.
Extraction runs in page batches with persisted JSON checkpoints. Model responses
are schema validated; model-generated keys/rubrics are discarded. Context-page
questions are assigned to their source batch to prevent duplicates. Crops are
materialized locally at publication. Only owner teachers can access full sources.

`services/job_worker.py` runs one import worker and bounded grading/delivery
workers. `jobs`, `import_chunks`, and `answer_drafts` persist progress. Missing AI
keys and transport/JSON failures raise `AIUnavailable`; never convert an outage
into acceptance or a wrong answer. Teacher overrides take precedence over a late
AI response. All answers are saved atomically before AI is called. Finalization
checks pending/incomplete submissions and writes tiers, totals, ranks, status and
notification jobs in one transaction. Run exactly one application instance.

`scripts/database/migrations.py` applies versioned additive migrations on startup,
after the deployment backup. Legacy answer-key tests remain bot-compatible.
Production media is stored at `/data/media`, so back it up as well as SQLite.
Optional Caddy HTTPS is enabled with the Compose `web` profile and `.env.web`.
Full server and staging instructions are in README.

Multipart policy: all required subparts must match the approved whole-question
rubric to earn the parent’s fixed points. There is no partial credit. Separate
answer-key PDF extraction is not implemented; bulk paste and manual key/rubric
entry are supported. UI styling can be improved independently of these services.

## 12. Open publishing, discovery and session architecture

Implemented platform behavior:

- Teachers and students from any education center, as well as independent users,
  are welcome. Basirat is the platform brand; affiliation is not an access rule.
- Replace manual test-code entry as the primary student journey with a public
  test catalog and teacher-shared links that open the selected test.
- Support exactly two publication visibility options: `public` (discoverable in
  the catalog) and `unlisted` (available through its shared link). Restricted
  tests, approved class rosters, and group-membership access are out of scope.
- Every test listing and introduction must prominently show the publisher's
  full name. Require teachers to complete/confirm their full name in their
  profile before publication; a first name, Telegram username, or center name
  alone is insufficient. Keep ownership tied to the authenticated user ID, not
  to the displayed name. Do not describe self-entered names as verified.
- Separate teacher permissions over their own content/results from platform
  administration. Anyone can upload and publish; no approval or ADMIN_IDS
  membership is required. Confirm a full name before publishing.
- Keep assessment sessions and their submissions/scoring separate from reusable
  question content, so reuse does not mix cohorts or tertile rankings. Preserve
  the existing correctness-first, final-score-after-closing policy.

### Future access pricing

Paid test access is deferred. The standard future price is **5,000 UZS**
per test, persisted in `test_templates.price_uzs`. Charging is disabled and all
assessment access remains free. Digital purchases inside Telegram must use Stars;
the UZS field is not an XTR conversion. No Click SDK is added. The private Stars
integration pilot below does not create access grants.

- Visibility and pricing are independent: a public test may eventually require
  payment, and an unlisted test may be free.
- Use one server-side access decision for opening question content, saving
  answers, and submitting an attempt. A client button or knowledge of a shared
  link must not bypass a future paid-access rule.
- Allow access to come from configurable free allowances, a confirmed purchase,
  or a valid promo-code redemption. Keep those grants separate from test content
  and payment records, so grading does not depend on a payment
  provider.
- Future examples include one free test followed by paid access, and promo codes
  that grant free access. The scope/reset period of "one free test",
  promo limits/expiry, and whether purchases cover a test or a specific session
  are not decided yet; do not hard-code assumptions about them.
- Publisher IDs in `ADMIN_IDS` identify Basirat publishers for future special
  pricing rules only; those rules are not yet defined or implemented.

### Native Stars pilot (migration 5)

- `services/stars_payments.py` owns fixed 1-XTR integration orders, per-buyer
  idempotency keys, terms acceptance, pre-checkout validation, durable receipts,
  refund retry/backoff, and transaction-history reconciliation. Orders/receipts
  are scoped to bot ID and real Telegram test/live environment. Do not use a
  client checkout callback as evidence of payment or grant access here.
- `handlers/payments.py` is registered before legacy/FSM handlers. It answers
  pre-checkout within Telegram's ten-second deadline and records trusted success
  and refund messages before acknowledgement. `/terms` and `/paysupport` provide
  pilot terms and the configured operator contact.
- `main.py` binds the existing Bot to the authenticated same-origin payment
  API and runs one recovery worker. It selects aiogram's TEST API endpoint only
  when `TELEGRAM_TEST_ENVIRONMENT=true`. Telegram's test server needs its own
  account, bot token and isolated deployment; a Click test provider token cannot
  be used for Stars. Stars invoices always use `provider_token=''` and `XTR`.
- The Profile panel is visible only to enabled pilot admins or prior payers.
  Invoice creation/pre-checkout require `ADMIN_IDS`, enabled pilot flag, a valid
  support username, and either the actual test environment or explicit live-test
  opt-in. Defaults disable new purchases. Existing payer history/refunds persist
  after disabling. Live testing spends real Stars and is clearly labelled.
- Refunds are monotonic/idempotent even when a refund event arrives before its
  success event. Mismatched/extra charges are recorded and queued for refund.
  Full history scanning recovers missed updates and same-ID refunds for this
  small pilot; plan incremental reconciliation before general commercial use.
- `tests/test_stars_payments.py` uses fake Bot API calls, verifies retry/race,
  isolation/ownership, terms/flags, refund/restart, reconciliation, routing and
  API auth. Native invoice UI still requires a real Telegram test client.

### Direct Click/Payme browser pilot (migration 6)

- This is an admin-only 1,000 UZS integration pilot, not paid assessment access.
  It remains disabled by default. Hide the unused panel unless a provider is
  available; preserve access to existing order history after disabling checkout.
  `services/web_payments.py` owns fixed-price browser orders and hosted checkout
  links. Money is integer tiyin internally; convert to UZS decimal strings only
  for Click. Do not mix these tables with Stars orders or introduce access grants.
- `services/click_payments.py` handles signed Shop API Prepare/Complete.
  Validate the raw field order/signature, service, amount, order, prepare ID and
  external transaction binding. Negative Complete cancels pending reservations;
  it must never regress an already paid receipt. No Click reversal/status REST
  adapter is included in this pilot; refunds/reconciliation require the operator.
- `services/payme_payments.py` handles authenticated JSON-RPC CheckPerform,
  Create, Perform, Cancel, Check, GetStatement and SetFiscalData. Use separate
  test/live merchant credentials and routes; Basic username is Paycom. Commit
  timeout cancellation even when rejecting an operation. Cancellation/refund
  states are monotonic. GetStatement uses provider creation time inclusively.
- `provider_transactions` and `web_payment_orders` are scoped by bot ID,
  provider, environment and merchant. A partial unique index prevents two active
  payments per order. Retries and callbacks run under SQLite write transactions;
  no network requests occur inside them. Disabling creation does not disable
  authenticated completion/cancellation of existing orders.
- Browser checkout requires a signed browser-audience session. Ordinary Mini App
  sessions cannot call it; browser return query parameters cannot settle orders.
  New Mini App launches refresh their Telegram session and do not expose direct
  checkout. Never add these buttons to paid test screens inside Telegram.
- `services/browser_auth.py` uses five-minute, one-use browser challenges, a
  hashed private nonce in an HttpOnly cookie, and explicit private-chat approval
  with matching codes. `handlers/browser_auth.py` handles approvals before FSM
  catch-alls. Identity comes only from Telegram updates, not the polling client.
- Defaults disable web purchases. BROWSER_APP_URL enables browser login at a
  configured HTTPS origin; it may share the existing app hostname. Merchant
  accounts, provider sandbox verification, required fiscal/item configuration,
  and controlled live testing remain operator steps. Click test credentials must
  be a dedicated test service; merely labelling a live service 'test' does not
  prevent real charges. BotFather tokens are not used by either direct adapter.
- Tests use fake merchant keys, isolated SQLite and provider callbacks; no real
  provider charge, merchant account, secret or production environment is touched.

`services/catalog_service.py` owns profiles, safe catalog summaries, visibility
and session creation. `services/access_policy.py` is called before serving
question content/crops, writing drafts, or accepting submissions (including
legacy Telegram submissions). Future entitlements belong at that boundary,
independently of payment-provider callbacks and grading.

Migration 3 keeps existing IDs, questions, answers and results intact. Existing
tests become unlisted; question-bearing tests get a reusable immutable template.
Each `tests` row is one assessment session, with separate question statistics,
submissions, drafts, tiers, ranks and a stable opaque `public_id`. Session creation
uses an idempotency key so retrying a request cannot create extra cohorts.
`/api/teacher/*` enforces ownership for everyone, including platform admins;
`/api/admin/*` remains a compatibility alias with the same ownership checks.
Public discovery exposes only active public sessions; students retain their own
finished/unlisted results in personal history. Profiles are self-entered, not
verified identities. Shared Telegram `/start t_<public_id>` links work without
requiring BotFather Main Mini App configuration.


## 13. Persistent student timers

`tests.duration_minutes` and `imports.duration_minutes` store optional limits of
1–1440 whole minutes. Null retains untimed behavior. The duration is session
metadata and is copied when reusing questions; it cannot change after any start,
draft, or submission. Version 4 adds these columns, `timed_attempts` and the
submission `auto_submitted` marker, without timing or rewriting existing tests.

`POST /api/tests/{public_id}/start` checks access and atomically records the start
and deadline for the authenticated user. Repeats never change the original
clock. Timed question reads, crops, drafts and submissions require a started
attempt. Expired writes never accept new answers: they submit the last saved
draft using the same transactional grading code as a manual submission.

`services/timer_service.py` is the deadline authority. Start queues a persistent
`expire` job. A separate expiry worker cannot be starved by slow AI calls;
`recover_jobs()` recovers interrupted work and previously failed expiry jobs.
Expiry jobs retry with capped backoff until they succeed; unlike AI jobs, they
have no terminal retry limit. Student reads also settle an expired
attempt immediately. Teacher finalization first settles due timers, then blocks
while any timed attempt is still in progress or grading is pending. Timeout
submissions preserve correctness-first, points-after-finalization behavior.

`GET /api/tests/{public_id}/timer` returns server/deadline timestamps and any
submission. The frontend countdown uses monotonic elapsed time, resynchronizes
on focus/visibility/online changes and periodically, and locks inputs at zero.
The catalog distinguishes running timed attempts from untimed resumable drafts;
leaving a timed attempt warns that the original clock continues. Only untimed
tests offer saving and resuming later.
Only answers accepted by the server before the deadline count. Do not trust a
client timestamp, extend deadlines when refreshing, or use browser-only timers.


## 14. Student-first workspace

Default to student discovery. `Workspace` owns the Testlar / Natijalarim / Profil
navigation; teacher access remains open to everyone through the account menu,
profile shortcut and desktop sidebar. Do not restore the global role selector.
Teacher/import and student/test deep links take precedence on entry and are
consumed within that workspace lifetime, so switching tabs does not reopen an
old link unexpectedly. All workspace changes still await the registered save
guard; an unsuccessful save must keep the user on the current screen.

`StudentCatalog` combines public discovery with a separate, unfiltered resumable
section. Its pagination is independent of catalog search and results. Resume
opens the existing attempt with the idempotent start endpoint; it must never
reset the deadline. Resume cards read the authenticated timer endpoint and share
the server-synchronized countdown hook with the attempt screen. Expiry refreshes
both lists. Do not start an attempt just to render its catalog or resume card.

The compact catalog requests `limit=2` and uses a client cursor history for
previous/next pages; the API validates limits 1–24 and defaults to 24 for existing
clients. Search resets the page history. The personal prompt uses the user's name
and started-attempt state, with no AI call on page load. No subject filter or
free/subject badges appear in discovery. Amber indicates running time; muted
forest green marks final submission and accepted answers. Content entrance and
press transitions respect reduced-motion preferences. Header and global
navigation styles remain unchanged.

Student detail/assessment views hide global navigation. They retain explicit
back actions, Telegram BackButton support, autosave, progress, question map,
review, timer guards and correctness-first/delayed-final-score behavior.

`pages.css`, loaded after workspace styles, applies the compact design to main
content and dialogs without changing the header or global navigation. Shared
`PageHeading`, `usePagedList` and `PageControls` keep presentation consistent.
Student results show two cards; teacher lists show three rows; participants and
answer details show four; question analysis shows six; payment history shows
three. Teacher paging still loads further server batches when needed. Search
and tab changes reset the relevant pagination.

Teacher uploads are opened on demand. Drafts omit already-published imports;
the published assessment remains accessible in Testlar and Natijalar. Test
settings start collapsed behind the settings action. Publisher setup is optional
on the student profile and prompted for an unregistered teacher. Publication,
question format, AI feedback and receipt details use disclosures. Required review
checks, ownership, confirmations, timer warnings, payment amounts/consent and
correctness-first/delayed-final-score behavior remain explicit. These presentation
changes do not alter the database schema or payment settlement logic.

## 15. Optional question voice explanations

`Question.explanation_audio` is an optional private asset ID (default empty).
Teacher recordings upload to `POST /api/teacher/imports/{id}/explanations` only
while that teacher owns a review draft. `explanation_service.py` bounds raw
uploads, probes real audio, normalizes browser WebM/MP4/Ogg to MP3, and limits
encoding concurrency to two outside write transactions. FFmpeg and FFprobe are
required system dependencies in development, CI and the Docker runtime. Input
protocols are restricted and processing has a timeout. Failed uploads remove
temporary/output files. The per-import 64 MB quota includes replaced uploads.

Draft save and publication both reject audio from another import or another
asset kind. AI extraction clears recording references. Published question and
template snapshots retain audio IDs for reused sessions. No migration is added.
`student_document` must never include those IDs. Only `submission_result` adds
`explanation_audio_url`, including for automatic submissions and pending grades;
score/rank reveal remains unchanged.

`GET /api/tests/{code}/explanations/{asset_id}` checks the authenticated student's
own submission, exact session, document reference, source import and asset kind
on every request (including range requests). The generic asset endpoint remains
owner-only for explanations. Do not weaken this to test status, shared import,
admin status, another student's submission, or frontend visibility checks.

`VoiceCapture` owns the microphone lifecycle and releases tracks/timers on stop,
errors, cancellation or unmount, including late permission grants. The editor
blocks navigation/publishing while recording or uploading; failed uploads can
retry from the local blob. Backgrounding stops capture and uploads it. Players
use `preload="none"`, custom play/pause/seek controls and authenticated same-origin URLs;
CSP permits same-origin media plus local blob previews. Actual microphone
permissions and recording behavior require Android/iOS Telegram device checks.

## 16. Faster teacher review and content-saving deterrents

Bot onboarding lives in `services/bot_branding.py`. `welcome_text` only reads a
shared in-memory tip cache; a single managed worker refreshes it through the
existing DeepSeek REST client with an 8-second/900-token budget once per 24 hours.
Prepared tips cover cold starts, disabled AI and failures; failed refreshes retry
after 15 minutes. Names/IDs stay local, output is validated and HTML-escaped,
and last-good tips survive failed refreshes within the process. A separate
cancellable worker syncs default/Uzbek pre-Start and profile descriptions only
when changed and retries transient Telegram errors without blocking polling.

The preparation stepper stays in four aligned columns, including narrow phones.
Freshly acknowledged student submissions (manual or automatic) show a brief
brand-color confetti burst and checkmark entrance. Result polling and reopening
past submissions do not replay it. Decorations are noninteractive, removed after
3.4 seconds, and disabled for reduced-motion preferences; scores remain subject
to the normal teacher-finalization rules.

Saving a draft through `save_import` derives each `reviewed` flag from
`Question.readiness_errors`: complete question text, valid passage references,
choices/key or open-answer criteria. Client review flags cannot approve missing
content. AI extraction still clears answer keys/rubrics/review status; publishing
still checks every question and overall document structure. There is no extra
manual checkbox. `prepareReview` / `questionIssues` mirror readiness in the UI;
tests cover automatic approval, invalid keys and multipart criteria.

Questions initially use a compact preview with one-tap answer-key choices;
editing fields open on demand, with open-answer criteria initially expanded.
Previous/next and question-map navigation await draft saving before moving and
retain the current question on failure. Voice activity blocks navigation and
publishing. The global header and bottom navigation remain untouched.

`AudioPlayer` exposes only play/pause and seeking, pauses other players, and has
no native download/overflow/cast menu. `ProtectedTest` scopes copying, context
menu, drag and save/print deterrents to student attempts/results; typed-answer
editing remains available. Print CSS hides test content. These measures do NOT
prevent OS screenshots, screen recording, browser tools or extraction of already
delivered media. Do not describe them as DRM or guaranteed download protection,
or invent a Telegram screenshot-blocking API. Backend submission/ownership
checks remain mandatory regardless of frontend restrictions.
