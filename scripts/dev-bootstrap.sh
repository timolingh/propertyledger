#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${PROPERTYLEDGER_ENV_FILE:-$repo_root/.env}"
ledgeros_source_env_file="${LEDGEROS_SOURCE_ENV_FILE:-$repo_root/../ledgeros_v2/.env}"

if [[ ! -f "$env_file" ]]; then
  echo "PropertyLedger env file not found: $env_file" >&2
  exit 1
fi

if [[ -f "$ledgeros_source_env_file" ]]; then
  # shellcheck disable=SC1090
  set -a
  # Source the LedgerOS env file if it exists so the required integration values
  # can be copied into PropertyLedger without inventing any secrets locally.
  . "$ledgeros_source_env_file"
  set +a
fi

require_value() {
  local key="$1"
  local value="${!key:-}"
  if [[ -z "$value" ]]; then
    echo "Missing $key." >&2
    case "$key" in
      LEDGEROS_BASE_URL)
        echo "Set this to the URL where LedgerOS is already running, such as http://host.docker.internal:8001 or your deployed LedgerOS URL." >&2
        ;;
      LEDGEROS_CLIENT_ID)
        echo "Set this to the LedgerOS API client id configured in the LedgerOS repo's api_clients.yml, such as api_full." >&2
        ;;
      LEDGEROS_HMAC_SECRET)
        echo "Set this to the matching LedgerOS secret value for that client, such as the value of LEDGEROS_API_CLIENT_FULL_SECRET in the LedgerOS deployment env." >&2
        ;;
    esac
    exit 1
  fi
}

upsert_env() {
  local key="$1"
  local value="$2"
  local tmp_file
  tmp_file="$(mktemp)"
  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    $0 ~ "^[[:space:]]*#"
      { print; next }
    $0 ~ "^[[:space:]]*$"
      { print; next }
    {
      split($0, parts, "=")
      if (parts[1] == key) {
      print key "=" value
      found = 1
      next
      }
    }
    { print }
    END {
      if (!found) {
        print key "=" value
      }
    }
  ' "$env_file" > "$tmp_file"
  mv "$tmp_file" "$env_file"
}

require_value LEDGEROS_BASE_URL
require_value LEDGEROS_CLIENT_ID
require_value LEDGEROS_HMAC_SECRET

upsert_env LEDGEROS_BASE_URL "$LEDGEROS_BASE_URL"
upsert_env LEDGEROS_CLIENT_ID "$LEDGEROS_CLIENT_ID"
upsert_env LEDGEROS_HMAC_SECRET "$LEDGEROS_HMAC_SECRET"

if [[ -n "${LEDGEROS_API_KEY:-}" ]]; then
  upsert_env LEDGEROS_API_KEY "$LEDGEROS_API_KEY"
fi

echo "Updated $env_file with the LedgerOS connection values."
echo "Source of truth:"
echo "  LEDGEROS_BASE_URL: the running LedgerOS URL"
echo "  LEDGEROS_CLIENT_ID: the client id from LedgerOS api_clients.yml"
echo "  LEDGEROS_HMAC_SECRET: the matching LedgerOS secret value for that client"

cd "$repo_root"
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py migrate
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_connection_settings
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_account_mappings

echo "PropertyLedger setup bootstrapped."
echo "Next manual steps:"
echo "  1. Open PropertyLedger."
echo "  2. Select the LedgerOS entity."
echo "  3. Select the accounting period."
echo "  4. Create your first property, unit, tenant, and lease."
