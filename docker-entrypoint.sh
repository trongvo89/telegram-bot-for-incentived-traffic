#!/bin/sh
set -e

# If a service-account JSON blob is provided via env (Fly/Railway secret),
# materialize it to disk and export the path expected by google-auth. We only
# export GOOGLE_APPLICATION_CREDENTIALS when the file is actually written so
# the bot can detect "Google not configured" gracefully instead of crashing
# on a missing file.
if [ -n "$GOOGLE_APPLICATION_CREDENTIALS_JSON" ]; then
  : "${GOOGLE_APPLICATION_CREDENTIALS:=/app/secrets/sa.json}"
  mkdir -p "$(dirname "$GOOGLE_APPLICATION_CREDENTIALS")"
  printf '%s' "$GOOGLE_APPLICATION_CREDENTIALS_JSON" > "$GOOGLE_APPLICATION_CREDENTIALS"
  chmod 600 "$GOOGLE_APPLICATION_CREDENTIALS"
  export GOOGLE_APPLICATION_CREDENTIALS
fi

exec "$@"
