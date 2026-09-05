#!/bin/sh

set -eu

run_db_migrations="${RUN_DB_MIGRATIONS:-${RENDER:-false}}"

if [ "$run_db_migrations" = "true" ]; then
    migration_attempt=1
    migration_max_attempts="${MIGRATION_MAX_ATTEMPTS:-12}"

    while ! alembic upgrade head; do
        if [ "$migration_attempt" -ge "$migration_max_attempts" ]; then
            printf '%s\n' "Database migrations failed after ${migration_attempt} attempts."
            exit 1
        fi

        printf '%s\n' "Database migration attempt ${migration_attempt} failed; retrying in 5 seconds."
        migration_attempt=$((migration_attempt + 1))
        sleep 5
    done
fi

exec gunicorn \
    --workers "${WEB_CONCURRENCY:-1}" \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout "${GUNICORN_TIMEOUT_SECONDS:-120}" \
    --bind "0.0.0.0:${PORT:-10000}" \
    app.main:app
