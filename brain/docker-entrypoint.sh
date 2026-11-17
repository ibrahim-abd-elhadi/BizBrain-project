#!/bin/sh
# One image, two services (README Section 1):
#   serve  -> brain-worker: apply the Brain's migrations, then run the Cairo scheduler;
#   api    -> brain-api: the read endpoints for the Brain screens;
#   other  -> any brain-worker command (run <job>, reset, healthcheck).
set -eu

case "${1:-serve}" in
  serve)
    alembic upgrade head
    exec brain-worker "$@"
    ;;
  api)
    exec uvicorn brain.api.app:app --host 0.0.0.0 --port 8000
    ;;
  *)
    exec brain-worker "$@"
    ;;
esac
