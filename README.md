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
DEEPSEEK_MODEL=deepseek-chat

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
answers, grading progress, finalization, and delivery progress must become durable
database state before production use; these recovery changes are still pending.

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
separate aiogram, Pydantic, and multidict versions in the constraints file to
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
access to SSH; this polling deployment does not publish application ports.

Create a deployment directory owned by the account that runs Docker. Copy these
files from the same release into it: `compose.yaml`, `.env.example`, and
`scripts/deploy.sh`. The Python application and backup helper come from the
container image, so the server does not need the source checkout or Python.

From that deployment directory:

```bash
cp .env.example .env.runtime
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
| `data/` | `/data` | Live SQLite database and WAL files |
| `reports/` | `/app/reports` | Generated Excel reports |
| `backups/` | `/backups` | Verified SQLite backup snapshots |

Use `docker login` with a pull-capable token if the Docker Hub repository is
private. Registry credentials stay with Docker on the server; bot credentials
stay in `.env.runtime`. Never include either in the image.

### Deploy and inspect a release

Until durable grading and shutdown recovery are implemented, schedule deployments
when no assessments, grading, or result broadcasts are active. The configured
60-second stop grace period does not itself make the current handlers drain.

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

The application currently initializes tables with `CREATE TABLE IF NOT EXISTS`;
it does not have versioned schema migrations. Integrate an explicit migration
step between backup and startup before releasing any schema change. Favor
backward-compatible changes so that the previous image remains usable.

### Remaining production readiness work

- Atomically accept a submission and its complete answer set; persist and resume
  grading jobs without holding database transactions across AI requests.
- Close test intake before finalization, resolve accepted pending submissions,
  and commit scores/ranks and finished status consistently.
- Treat AI/API failures as pending/error states, separate from wrong answers;
  define retries, concurrency limits, provider fallback, and model availability.
- Persist student drafts and notification progress; retry Telegram rate limits
  and transient failures, and handle permanent delivery failures.
- Replace startup update dropping with intentional update processing, implement
  controlled shutdown/recovery, and enforce teacher ownership of test operations.
- Add schema versioning, functional health monitoring, scheduled off-server
  backups, and a verified restore procedure with chosen recovery targets.

References: [Compose in production](https://docs.docker.com/compose/how-tos/production/),
[SQLite backup API](https://www.sqlite.org/backup.html),
[Hetzner Volume backup scope](https://docs.hetzner.com/cloud/volumes/overview/).
