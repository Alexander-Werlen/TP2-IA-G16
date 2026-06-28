#!/bin/sh
# Entry script del backend.
# - Si el comando empieza con "alembic" o "uvicorn", aplica migraciones antes.
# - Cualquier otro comando se ejecuta tal cual (útil para `eval`, `pytest`, etc).

set -e

if [ "$1" = "uvicorn" ] || [ "$1" = "alembic" ]; then
  echo "[entrypoint] Aplicando migraciones Alembic..."
  alembic upgrade head
fi

exec "$@"
