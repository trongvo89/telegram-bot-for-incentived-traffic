#!/bin/sh
set -e

# If a service-account JSON blob is provided via env (Fly secret), materialize
# it to the path expected by google-auth. This lets us ship credentials as a
# single secret instead of mounting a file.
if [ -n "$GOOGLE_APPLICATION_CREDENTIALS_JSON" ] && [ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
  mkdir -p "$(dirname "$GOOGLE_APPLICATION_CREDENTIALS")"
  printf '%s' "$GOOGLE_APPLICATION_CREDENTIALS_JSON" > "$GOOGLE_APPLICATION_CREDENTIALS"
  chmod 600 "$GOOGLE_APPLICATION_CREDENTIALS"
fi

exec "$@"
