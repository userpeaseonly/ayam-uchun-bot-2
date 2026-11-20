#!/usr/bin/env bash
# Run on the server from the deployment bundle, with one release digest argument.
set -Eeuo pipefail
umask 077

deploy_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$deploy_root"

if [[ $# -ne 1 || ! "$1" =~ ^[a-z0-9][a-z0-9./_-]*@sha256:[a-f0-9]{64}$ ]]; then
    echo "Usage: bash scripts/deploy.sh namespace/repository@sha256:<64 hex characters>" >&2
    exit 2
fi
export BOT_IMAGE="$1"

exec 9>.deploy.lock
flock -n 9 || { echo "Another deployment is running." >&2; exit 1; }

for directory in data reports backups; do
    [[ -d "$directory" ]] || { echo "Missing $directory directory; follow README setup." >&2; exit 1; }
done

touch .env.release
compose=(docker compose --env-file "$deploy_root/.env.release" -f "$deploy_root/compose.yaml")
"${compose[@]}" config --quiet
"${compose[@]}" pull bot
# Validate required settings before stopping the existing service.
"${compose[@]}" run --rm --no-deps -T --entrypoint python bot \
    -c 'from scripts.run_bot import validate_configuration; validate_configuration()'

previous_container=$("${compose[@]}" ps --all --quiet bot)
previous_image=""
previous_running=false
if [[ -n "$previous_container" ]]; then
    previous_image=$(docker inspect --format '{{.Config.Image}}' "$previous_container")
    previous_running=$(docker inspect --format '{{.State.Running}}' "$previous_container")
fi

# Current handlers do not yet drain reliably. Until recovery work lands, deploy
# only when no assessment/grading is active; stop_grace_period alone is not enough.
"${compose[@]}" stop bot
backup_name="predeploy-$(date -u +%Y%m%dT%H%M%SZ)-$$.sqlite3"
backup_args=(-m scripts.backup_db --output "/backups/$backup_name")
if [[ -z "$previous_container" ]]; then
    backup_args+=(--if-exists)
fi
if ! "${compose[@]}" run --rm --no-deps -T --entrypoint python bot \
    "${backup_args[@]}"; then
    echo "Backup failed; restoring the previous container's running state." >&2
    if [[ "$previous_running" == true ]]; then
        "${compose[@]}" start bot
    fi
    exit 1
fi

# Schema migrations must be integrated here before deploying schema changes.
if [[ -n "$previous_image" ]]; then
    printf '%s\n' "$previous_image" > .previous-image
fi
"${compose[@]}" up --detach --no-build --no-deps --force-recreate bot
container=$("${compose[@]}" ps --all --quiet bot)
sleep 10
if [[ -z "$container" ]] || \
    [[ $(docker inspect --format '{{.State.Running}}:{{.RestartCount}}' "$container") != "true:0" ]]; then
    echo "Container startup check failed. Inspect docker compose logs; no automatic rollback performed." >&2
    if [[ -n "$previous_image" ]]; then
        echo "Previous image: $previous_image" >&2
    fi
    exit 1
fi

printf 'BOT_IMAGE=%s\n' "$BOT_IMAGE" > .env.release.tmp
mv .env.release.tmp .env.release
echo "Container is running. Verify /start and a test flow in Telegram; functional health is not automated yet."
