# Ayam Uchun Telegram Bot 2 (AI-Powered Assessment Bot)

Telegram bot built with **aiogram 3**, **aiosqlite**, and **DeepSeek / Gemini** API for dynamic test assessment and scoring.

## Asosiy Imkoniyatlar (Key Features)

1. **Savollar boshqaruvi (5–44 ta)**:
   - Har bir testda kamida 5 ta, ko'pi bilan 44 ta savol bo'lishi mumkin.
   - 9 tagacha **ochiq savol** (open questions) qo'llab-quvvatlanadi.
   - Ochiq savollar uchun o'qituvchi maxsus ko'rsatma (rubric) kiritadi va ular **DeepSeek AI** (yoki Gemini) yordamida o'zbek tilida xolis baholanadi.

2. **Dinamik 3-bosqichli ballar tizimi (1.1, 1.7, 2.5 ball)**:
   - Barcha o'quvchilar javoblari qabul qilingach, o'qituvchi "Testni yakunlash" tugmasini bosadi.
   - Tizim yopiq savollarni muvaffaqiyat darajasiga ko'ra 3 ta guruhga (tertile) ajratadi:
     - 🟢 **1.1 ball**: Ko'pchilik o'quvchilar to'g'ri topgan oson savollar.
     - 🟡 **1.7 ball**: O'rtacha miqdordagi o'quvchilar to'g'ri topgan savollar.
     - 🔴 **2.5 ball**: Kamchilik o'quvchilar to'g'ri topgan qiyin savollar.
   - Ochiq savollar: AI ma'qullaganda belgilangan ball (standart: 2.5 ball).

3. **O'quvchilar uchun qulay va ishonchli javob yuborish**:
   - O'quvchilar javoblarni bitta xabarda qulay formatda yuboradilar:
     - Yangi qatorda:
       ```text
       1. A
       2. B
       3. Gulchexra suv ichdi
       4. D
       5. Olmaning tagi oltin
       ```
     - Yoki vergul bilan:
       ```text
       1:A, 2:B, 3:Gulchexra suv ichdi, 4:D, 5:Olmaning tagi oltin
       ```
   - Bot kiritilgan javoblarni tekshirib, tasdiqlash uchun ko'rsatadi (qolib ketgan savollarni ogohlantiradi).
   - O'quvchi tasdiqlagach, bot **darhol** qaysi savol to'g'ri yoki noto'g'ri ekanligini ko'rsatadi, lekin ballarni test yakunlangunga qadar sir saqlaydi.

4. **O'qituvchi / Admin Paneli va Excel hisobot**:
   - Testlarni Telegram xabari yoki `.xlsx` Excel shabloni orqali kiritish.
   - "Testni yakunlash" bosilganda:
     - Telegramda qisqa hisobot va savollar ballari.
     - 3 ta varaqdan iborat chiroyli formatlangan **Excel (.xlsx)** fayl (Reyting, Savollar tahlili, Har bir o'quvchining to'liq javoblar matritsasi).
     - Barcha o'quvchilarga ularning yakuniy balli va o'rni avtomatik yuboriladi.

---

## O'rnatish va Ishga Tushirish

### 1. Muhitni sozlash
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### 2. `.env` faylini sozlash
`.env.example` nusxasini `.env` qilib oling:
```bash
cp .env.example .env
```
Faylni ochib quyidagi qiymatlarni kiriting:
```env
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_IDS=123456789

# AI sozlamalari
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_IMPORT_MODEL=deepseek-flash

# Google Gemini (ixtiyoriy)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-1.5-flash
```

### 3. Testlarni ishga tushirish (Verification)
```bash
.venv/bin/pytest tests/ -v
```

### 4. Botni ishga tushirish
```bash
.venv/bin/python main.py
```

## Agreed deployment architecture

The production target is one Hetzner Linux server running Docker Engine and the
Compose plugin. GitHub Actions tests the source, builds the container, tests the
container, and publishes a release to Docker Hub. Production pulls the selected
image digest. Local development builds from source with `compose.dev.yaml`.

There is one polling bot process per Telegram bot token. The application remains
one deployable Python application, with handlers, application services, scoring,
database access, and external API clients as internal boundaries. Accepted
answers, grading progress, finalization, and delivery progress are durable SQLite
state. Submission acceptance and final scoring are atomic. A bounded worker pool
resumes interrupted jobs on startup; run exactly one application instance.

The initial workload target is fewer than 100 student submissions per minute
across active tests. Start with SQLite WAL on persistent local storage and one
bot instance. Verify the target with a realistic load test before production;
keep write transactions short, batch answer inserts, and perform AI calls outside
write transactions. Reconsider PostgreSQL if measured write contention or a need
for multiple application instances justifies a database service. SQLite permits
concurrent readers but one writer per database file; student count alone is not
a capacity measurement. See [SQLite concurrency guidance](https://www.sqlite.org/whentouse.html).

The database Python package lives at `scripts/database/`; the actual SQLite file
lives under `/data` in the container. Docker copies the source package through
the `scripts/` directory, with its nested Python files included by `.dockerignore`.

### Build and release

`requirements.txt` installs runtime dependencies; `requirements-dev.txt` adds
pytest. `requirements.lock` constrains both to exact package versions. Production
uses Python 3.14. The CI matrix checks Python 3.10–3.14; Python 3.10 uses the
separate aiogram, Pydantic, Pillow, and multidict versions in the constraints file to
respect their Python and dependency requirements.

Configure the GitHub repository before enabling publishing:

- Repository variable `DOCKERHUB_IMAGE`: `your-namespace/ayam-uchun-bot-2`.
- Repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`: a Docker Hub user
  and a token with permission to push to that repository.

Create `DOCKERHUB_IMAGE` under repository **Settings → Secrets and variables →
Actions → Variables → New repository variable**. It is a repository variable,
not a secret or an environment variable. If CI reports an empty `IMAGE_NAME`,
this setting is missing or unavailable to the job; use the repository Variables
tab and set its value to the Docker Hub repository, without a tag or digest.

The workflow runs on pull requests, pushes to `main`, version tags, and manual
dispatch. Only push events publish images. Each published image is tagged
`sha-<full commit SHA>`; the workflow summary provides the deployment digest.
Images support `linux/amd64` and `linux/arm64`. Tests and runtime secrets are
excluded from the production image. No server deployment happens automatically.

To build and test locally without starting the bot:

```bash
docker build --target test -t ayam-bot-test:local .
docker run --rm -e DEEPSEEK_API_KEY=test-key ayam-bot-test:local
```

To start a development bot, configure `.env` with a separate development token:

```bash
docker compose -f compose.dev.yaml up --build
```

### Prepare the Hetzner server

Install Docker Engine, the Compose plugin, and `flock` from your Linux
distribution. Keep Docker enabled at boot. Use SSH key access and limit inbound
access to SSH and, for the Mini App HTTPS proxy, TCP ports 80/443. The Python
API port is published only on 127.0.0.1, not the public interface.

Create a deployment directory owned by the account that runs Docker. Copy these
files from the same release into it: `compose.yaml`, `Caddyfile`, `.env.example`, `.env.web.example`,
and the complete `scripts/` folder (preserve that folder layout). The Python application and backup helper come from the
container image, so the server does not need the source checkout or Python.

From that deployment directory:

```bash
test -f .env.runtime || cp .env.example .env.runtime
chmod 600 .env.runtime
sudo install -d -o 10001 -g 10001 -m 0700 data reports backups
```

Edit `.env.runtime` with the production token, admin IDs, selected provider, and
that provider's API key. The container validates those settings before startup.
Compose sets `DB_PATH=/data/bot_database.sqlite3` and stdout logging. Persistent
directories must be writable by container UID/GID `10001:10001`.

Storage is on the server filesystem, with these bind mounts:

| Host directory | Container path | Purpose |
| --- | --- | --- |
| `data/` | `/data` | Live SQLite database, WAL files, and `media/` document/image assets |
| `reports/` | `/app/reports` | Generated Excel reports |
| `backups/` | `/backups` | Verified SQLite backup snapshots |

Use `docker login` with a pull-capable token if the Docker Hub repository is
private. Registry credentials stay with Docker on the server; bot credentials
stay in `.env.runtime`. Never include either in the image.

### Deploy and inspect a release

Accepted submissions, import checkpoints, and grading jobs survive application
restarts. A deployment briefly interrupts HTTP requests; clients must retry.
Prefer quiet periods for deployments, and never run overlapping bot/worker replicas.

Copy the exact `namespace/repository@sha256:...` reference from the CI summary:

```bash
bash scripts/deploy.sh 'your-namespace/ayam-uchun-bot-2@sha256:REPLACE_WITH_64_HEX_DIGEST'
```

The script serializes deployments, pulls and validates configuration before
stopping the old bot, stops that bot, creates a verified database snapshot, and
starts the selected image. The first deployment skips backup if no database
exists. A backup failure restarts the previous container only if it was running.
It records the current image in `.env.release` after the new container stays
running for 10 seconds; `.previous-image` records the previous container image.

```bash
docker compose --env-file .env.release ps
docker compose --env-file .env.release logs --tail 100 bot
```

That startup check verifies process survival, not Telegram/API health. Verify
`/start`, test creation, submission, finalization, and report delivery in a
separate staging bot before allowing production assessments.

Docker rotates stdout/stderr logs. Persistent directories survive container
replacement. Never run a second polling instance using the production token.

### Backups, recovery, and schema changes

Create a live SQLite snapshot with the online backup API:

```bash
docker compose --env-file .env.release run --rm --no-deps -T --entrypoint python bot \
  -m scripts.backup_db --output /backups/manual-UNIQUE_NAME.sqlite3
```

The helper verifies the snapshot with `PRAGMA quick_check` and refuses to replace
an existing file or the live database. Schedule regular snapshots, copy completed
snapshots off the server, set retention based on your recovery requirements, and
practice restoring into an isolated staging deployment. Predeployment snapshots
alone do not cover data loss between releases. Hetzner server backups do not
include separately attached Hetzner Cloud Volumes.

To roll application code back, run `scripts/deploy.sh` with the previous image
digest, only after checking database compatibility. The script does not perform
automatic rollback or restore an older database: restoring an older snapshot
would discard newer submissions. For a database restore, stop the bot, preserve
the existing database and any WAL/SHM files together, place the verified snapshot
at `data/bot_database.sqlite3` with owner `10001:10001`, and start the compatible
image. Do not combine the restored snapshot with old WAL/SHM files.

Startup applies versioned, transactional, additive migrations from
`scripts/database/migrations.py` after the deployment script has taken its backup.
Existing answer-key-only tests are preserved. Check schema compatibility before
rolling back; an older image does not implement the Mini App job recovery.
Back up `data/media/` alongside database snapshots: a SQLite backup alone does
not contain uploaded PDFs, page previews, or approved diagram crops.

### Open publishing and the public catalog

Anyone with a Telegram account can use both student and teacher workspaces.
`ADMIN_IDS` is not a teacher allowlist. A publisher must save their full name in
**Profil** or the teacher setup form before publishing; ownership always uses their authenticated
Telegram ID. Names are self-entered, not verified.

The default student workspace has **Testlar**, **Natijalarim**, and **Profil**
navigation (bottom tabs on phones/tablets, sidebar on desktop). Students search
by test/teacher/subject and see the publisher's full name, question count and
duration on every card. Started tests appear above the catalog with saved state,
a live server-synchronized countdown where applicable, and one-tap **Davom
ettirish**. **Natijalarim** includes submitted tests and final results.

A test introduction explains timing and submission rules before starting. Test
screens hide the global header/sidebar/bottom tabs to keep questions, countdown,
autosave, question map and review controls in focus. Pending open-answer grading
and waiting for final session scores have separate messages.

Open **O‘qituvchi kabineti** from the account menu, **Profil**, or the desktop
sidebar. Teachers have **Testlar**, **Qoralamalar**, and **Natijalar** sections.
**Test yuklash** opens Telegram forwarding and local PDF/photo upload choices.
Published imports move out of drafts. Opening a test from **Testlar** expands
sharing controls; opening it from **Natijalar** prioritizes participants and
results. Visibility, subject, duration and new-session controls are grouped
under **Havola va test sozlamalari**. Existing teacher/import and student/test
deep links still open their intended destination directly.

Teachers choose **Ochiq** (Public, discoverable) or **Havola orqali** (Unlisted,
anyone with the link). Copy/share the session link from the results page. The
Telegram link opens the bot, which offers a button opening that exact test.
No class roster or approval is required. Teachers can manage only their own
sources, submissions, answer overrides, session closure and reports.

**Yangi sessiya** reuses approved immutable questions for a fresh group, with a
new link and separate submissions, difficulty statistics, scores and ranking.
Closing one session does not close another. Each student can submit once per
session. Immediate correctness and delayed final scoring are unchanged.

Migration 3 preserves existing test/result IDs and keeps previous tests unlisted.
Existing publishers should confirm their full name, then optionally change a
question-bearing session to Public. Legacy answer-key-only tests remain usable
through the bot. Back up SQLite and media before release as usual; older images
cannot read the newer schema without restoring a compatible backup.

The future standard price is **5,000 UZS per test**, stored separately from
visibility. **All tests remain free now.** Click payments, purchases, free
allowances, promo codes and special Basirat rules are deferred. Publisher IDs
in `ADMIN_IDS` are retained as the future brand distinction, without granting
access to another teacher's data. Future paid-access checks must extend
`services/access_policy.py`, which guards question reads, crops, drafts and
submissions, independently of grading and the eventual provider integration.

### Student time limits

In the teacher's draft editor, set **Vaqt chegarasi (daqiqa)** to 1–1440 whole
minutes. Leave it empty for an untimed test. The duration appears in the catalog
and before starting. Published sessions can change their duration through the
teacher settings only before anyone has started, saved answers or submitted.
Reused question sets inherit the source session's duration; a new session can
choose a different limit before students start.

**Testni boshlash** records one server deadline for that student. Refreshing,
closing Telegram, reopening, or using another device never restarts or pauses it.
The countdown uses server time and resynchronizes after reconnecting or returning
to the app. It warns in the last minute and locks inputs when time expires.

Expiry automatically submits the last answers received by the server, including
blank answers for unanswered questions. Unsaved/offline edits arriving after the
deadline are not accepted. A dedicated durable expiry worker handles students
who have closed the app, and resumes after a server restart. Manual submission
and expiry are idempotent, with the same grading and delayed-score policy.
Individual expiry does not finalize the whole test; the teacher still closes the
session once all timed attempts have submitted or expired and grading is done.

Migration 4 preserves existing tests as untimed and retains all results. Keep the
single-instance deployment and pre-release database/media backup procedure.

### Mini App and DeepSeek imports

The application serves a React/TypeScript Mini App and an authenticated aiohttp
API at port 8080. Node is used during the image build; production only runs
Python and the optional Caddy reverse proxy. DeepSeek requests use aiohttp REST.

Teacher flow: send/forward one PDF or ordered JPG/PNG/WebP photos to the bot's
private chat, wait for extraction,
review passages/questions/options/subparts and diagram crops, enter the official
answer keys and open-answer rubrics, then approve each question and publish.
PDFs/photos may total 20 MB and 30 pages. Imports are checkpointed in batches.
Original pages remain private to their owner; students receive only approved
crops referenced by the published test. Never crop answer keys or unrelated
questions into student diagrams. Teacher approval freezes published content.

**Uploading from Telegram:** send `/import`, or simply forward a PDF directly to
the bot. PDFs are queued immediately. For photos (including albums), send all
pages in order and then tap **Importni boshlash** or send `/done`. The collection
is persistent; restarting the application does not lose received pages. Telegram
message order determines page order even when downloads finish out of sequence.
Repeated updates do not duplicate imports. Teachers receive a Mini App button
that opens their exact draft, plus a notification when extraction finishes.
Uploads are accepted from any Telegram user in private chats, with a 20 MB
combined limit and no more than 30 photo pages. Telegram's hosted Bot API also
limits file downloads to 20 MB.

The Mini App's **Test yuklash** panel has **Telegram orqali yuborish** to return to
the chat. Browser uploads remain available under **Telefondan fayl tanlash**, with
separate PDF and image inputs. The browser picker depends on the Telegram client;
forwarding files to the bot works without it. Set `MINI_APP_URL` to the reachable
HTTPS origin so the bot can link back to the draft.

Question limits remain 5–44 numbered questions and at most nine open parents.
Matching questions can have A–F options. a)/b) fields stay inside one numbered
open question. **All subparts must be correct to earn the parent question's
points; partial credit is not implemented.** AI does not establish official keys.
Paste bulk closed keys (`1:A, 2:F`) or enter them in the editor; enter open rubrics
manually. Separate answer-key PDF extraction is not included in this release.

Student flow: browse the catalog or open a shared link, read the questions/passages, answer, save drafts,
review, and confirm once. Closed correctness is immediate. Open answers stay
pending during provider failures and retry automatically up to three times;
teachers can retry exhausted grading jobs or override grades before finalizing.
Finalization is blocked while any answer is pending. Points and rank appear only
after the teacher closes the test. Blank or incomplete multipart answers earn zero.

Configure these values in the server's `.env.runtime`:

```dotenv
AI_PROVIDER=deepseek
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_IMPORT_MODEL=deepseek-flash
MINI_APP_URL=https://app.basirat.uz
```

Point that domain's DNS A/AAAA records at the server, copy `Caddyfile` from this
release, and create `.env.web` beside `compose.yaml` (or copy `.env.web.example`):

```dotenv
MINI_APP_DOMAIN=app.basirat.uz
```

Deploy the image with the usual `bash scripts/deploy.sh 'namespace/image@sha256:…'`
command. Then start the optional HTTPS proxy:

```bash
docker compose --env-file .env.release --profile web up -d proxy
curl --fail --show-error --silent https://app.basirat.uz/ > /dev/null
```

Caddy obtains and renews HTTPS certificates. If you already have an HTTPS proxy,
route the domain to `127.0.0.1:8080` instead. Telegram requires HTTPS in production.
At startup the bot sets its menu button from `MINI_APP_URL`; `/start` also includes
an Open Mini App button. Configure the same URL in BotFather's Mini App settings.
Telegram identity signatures, expiry, role and test ownership are checked on the
server. There is no development authentication bypass.

For local development, install Poppler (`poppler-utils` on Debian/Ubuntu), then:

```bash
.venv/bin/python main.py
# In a second terminal, for frontend hot reload:
cd web
npm ci
npm run dev
```

Vite proxies `/api` to port 8080. For Telegram testing, use a development bot and
an HTTPS tunnel to the frontend; set `MINI_APP_URL` to that HTTPS URL. Browser
requests without a valid Telegram identity intentionally fail authentication.
To serve the built frontend directly, run `npm run build` in `web/` first.

Inspect a source document without contacting DeepSeek:

```bash
.venv/bin/python -m scripts.import_document /path/to/test.pdf --output-dir /tmp/ayam-import
```

Add `--run-ai` to use the configured DeepSeek key and write a draft JSON for
quality review. This incurs API usage, uses an isolated scratch database, and
never publishes a test. Extraction must be checked against the original; passing
unit tests does not establish provider accuracy on arbitrary PDFs or photographs.

### Verification and operational limits

Run `.venv/bin/python -m pytest tests/ -v`, plus `npm test` and `npm run build`
inside `web/`. CI checks both, Python 3.10–3.14, and the container test image.
Backend coverage includes 100 concurrent submissions, duplicate confirmation,
submission/finalization races, pending grading, teacher overrides during an AI
request, migration of legacy tables, crop access, and Telegram authentication.

The import worker handles one document at a time; eight workers process
individual grading/delivery jobs (adjust `GRADING_CONCURRENCY`, bounded to 1–16). Jobs retry with backoff and stop after three
failures; Telegram rate limits instead wait for the provider’s retry interval. Exhausted imports/grades expose a retry control. Telegram delivery is
at-least-once: an interruption after sending but before saving delivery state can
produce a duplicate message. Exhausted notification jobs need operator inspection;
the Mini App remains the source of truth for results.

Still validate on a separate staging bot before production assessments: the
actual model/account, representative PDF/photo accuracy, Telegram Android/iOS
behavior, off-server media/database backups, restore drills and ongoing monitoring.
The concurrent submission test does not measure AI throughput or API quotas.

References: [Compose in production](https://docs.docker.com/compose/how-tos/production/),
[SQLite backup API](https://www.sqlite.org/backup.html),
[Hetzner Volume backup scope](https://docs.hetzner.com/cloud/volumes/overview/).
