#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${PROPERTYLEDGER_ENV_FILE:-$repo_root/.env}"
ledgeros_source_env_file="${LEDGEROS_SOURCE_ENV_FILE:-$repo_root/../ledgeros_v2/.env}"
ledgeros_repo_root=""
ledgeros_bootstrap_selection_json=""
declare -A value_sources=()

source_env_file() {
  local file_path="$1"
  if [[ -f "$file_path" ]]; then
    # shellcheck disable=SC1090
    set -a
    . "$file_path"
    set +a
  fi
}

record_value_sources() {
  local file_path="$1"
  local source_label="$2"
  local key
  for key in LEDGEROS_BASE_URL LEDGEROS_CLIENT_ID LEDGEROS_HMAC_SECRET LEDGEROS_API_KEY; do
    if [[ -f "$file_path" ]] && grep -qE "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file_path"; then
      value_sources["$key"]="$source_label"
    fi
  done
}

source_env_file "$env_file"
record_value_sources "$env_file" "$env_file"

if [[ -f "$ledgeros_source_env_file" ]]; then
  # Source the LedgerOS env file if it exists so the required integration values
  # can be copied into PropertyLedger without inventing any secrets locally.
  source_env_file "$ledgeros_source_env_file"
  record_value_sources "$ledgeros_source_env_file" "$ledgeros_source_env_file"
  ledgeros_repo_root="$(cd "$(dirname "$ledgeros_source_env_file")" && pwd)"
fi

value_source_for() {
  local key="$1"
  if [[ -n "${value_sources[$key]:-}" ]]; then
    echo "${value_sources[$key]}"
  else
    echo "current shell"
  fi
}

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

require_value LEDGEROS_BASE_URL
require_value LEDGEROS_CLIENT_ID
require_value LEDGEROS_HMAC_SECRET

echo "Resolved LedgerOS connection values:"
echo "  LEDGEROS_BASE_URL from $(value_source_for LEDGEROS_BASE_URL)"
echo "  LEDGEROS_CLIENT_ID from $(value_source_for LEDGEROS_CLIENT_ID)"
echo "  LEDGEROS_HMAC_SECRET from $(value_source_for LEDGEROS_HMAC_SECRET)"

echo "Using environment values in-process only; $env_file is not modified."
echo "Source of truth:"
echo "  LEDGEROS_BASE_URL: the running LedgerOS URL"
echo "  LEDGEROS_CLIENT_ID: the client id from LedgerOS api_clients.yml"
echo "  LEDGEROS_HMAC_SECRET: the matching LedgerOS secret value for that client"

if [[ -n "$ledgeros_repo_root" ]]; then
  echo "Bootstrapping LedgerOS sample setup from $ledgeros_repo_root"
  pushd "$ledgeros_repo_root" >/dev/null
  docker compose -f docker-compose.yml up -d --build
  docker compose -f docker-compose.yml run --rm web python manage.py import_coa config/sample_chart_of_accounts.yml
  ledgeros_shell_command="$(cat <<'PY'
import json
from datetime import date

from apps.accounting.models import AccountingPeriod, Entity
from apps.accounting.services import create_accounting_period

entity = Entity.get_default()
open_period_exists = AccountingPeriod.objects.filter(
    entity=entity,
    status=AccountingPeriod.Status.OPEN,
).order_by("start_date", "id").first()

if open_period_exists is None:
    year = date.today().year
    while AccountingPeriod.objects.filter(
        entity=entity,
        start_date__lte=date(year, 12, 31),
        end_date__gte=date(year, 1, 1),
    ).exists():
        year += 1
    period = create_accounting_period(
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        name=f"Bootstrap FY{year}",
    )
else:
    period = open_period_exists

print(
    json.dumps(
        {
            "entity_id": str(entity.id),
            "entity_name": entity.name,
            "accounting_period_id": str(period.id),
            "accounting_period_name": period.name
            or f"{period.start_date.isoformat()} to {period.end_date.isoformat()}",
        }
    )
)
PY
)"
  ledgeros_bootstrap_selection_json="$(
    docker compose -f docker-compose.yml run --rm web python manage.py shell --no-imports -c "$ledgeros_shell_command"
  )"
  popd >/dev/null
  if [[ -z "$ledgeros_bootstrap_selection_json" ]]; then
    echo "LedgerOS bootstrap did not return entity and accounting period selection." >&2
    exit 1
  fi
  echo "Bootstrapping PropertyLedger setup selection from LedgerOS bootstrap data"
  docker compose -f docker-compose.yml run --rm \
    -e LEDGEROS_BOOTSTRAP_SELECTION_JSON="$ledgeros_bootstrap_selection_json" \
    propertyledger-web python manage.py bootstrap_ledgeros_setup_selection
else
  echo "LedgerOS repo not found; skipping LedgerOS sample bootstrap."
fi

cd "$repo_root"
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py migrate
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_connection_settings
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_account_mappings

echo "PropertyLedger setup bootstrapped."
echo "Next manual steps:"
echo "  1. Open PropertyLedger."
echo "  2. Finish any remaining PropertyLedger-specific setup."
echo "  3. Create your first property, unit, tenant, and lease."
