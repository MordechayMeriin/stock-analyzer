#!/bin/sh
# Runs at container start (nginx image entrypoint hook): write /config.js from API_BASE_URL.
set -eu

target=/usr/share/nginx/html/config.js
value="${API_BASE_URL:-}"

# JSON-escape the value (backslash and double quote) so any URL is safe to embed.
escaped=$(printf '%s' "$value" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')

printf 'window.__APP_CONFIG__ = { "apiBaseUrl": "%s" }\n' "$escaped" > "$target"
echo "config.js: apiBaseUrl=${value:-<same origin>}"
