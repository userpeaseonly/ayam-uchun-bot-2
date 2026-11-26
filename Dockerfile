# Deploy releases by the resulting image digest; rebuild deliberately for base updates.
ARG PYTHON_IMAGE=python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f
FROM node:22-slim AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOG_FILE="" \
    WEB_HOST=0.0.0.0 \
    MEDIA_PATH=/data/media \
    DB_PATH=/data/bot_database.sqlite3

WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 bot \
    && useradd --uid 10001 --gid bot --no-create-home bot \
    && mkdir /data /backups /app/reports \
    && chown bot:bot /data /backups /app/reports

COPY config.py main.py states.py ./
COPY handlers/ ./handlers/
COPY keyboards/ ./keyboards/
COPY services/ ./services/
COPY utils/ ./utils/
# Includes the database package now located at scripts/database/.
COPY scripts/ ./scripts/
COPY --from=frontend /web/dist ./web/dist/

USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "scripts.run_bot"]

FROM runtime AS test
COPY requirements-dev.txt ./
USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY pytest.ini ./
COPY tests/ ./tests/
USER 10001:10001
CMD ["python", "-m", "pytest", "tests/", "-v", "-p", "no:cacheprovider"]

FROM runtime AS production
