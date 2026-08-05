#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ledgeros_repo_root="$repo_root/../ledgeros_v2"

if [[ ! -d "$ledgeros_repo_root" ]]; then
  echo "Missing sibling repo at $ledgeros_repo_root." >&2
  echo "The beta seed needs the LedgerOS v2 repo so it can seed the shared accounting setup." >&2
  exit 1
fi

cd "$repo_root"
pushd "$ledgeros_repo_root" >/dev/null
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d db
docker compose -f docker-compose.yml run --rm web python manage.py migrate
docker compose -f docker-compose.yml run --rm web python manage.py import_coa config/sample_chart_of_accounts.yml
ledgeros_selection_shell_command="$(cat <<'PY'
import json
from datetime import date

from apps.accounting.models import AccountingPeriod
from apps.accounting.services import create_accounting_period
from apps.accounting.services.entities import get_default_entity

entity = get_default_entity()
period = AccountingPeriod.objects.filter(
    entity=entity,
    status=AccountingPeriod.Status.OPEN,
).order_by("start_date", "id").first()

if period is None:
    year = date.today().year
    period = create_accounting_period(
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        name=f"Beta FY{year}",
    )

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
  docker compose -f docker-compose.yml run --rm web python manage.py shell --no-imports -c "$ledgeros_selection_shell_command"
)"
if [[ -z "$ledgeros_bootstrap_selection_json" ]]; then
  echo "Failed to capture LedgerOS entity and accounting period selection." >&2
  exit 1
fi
popd >/dev/null

docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py migrate
docker compose -f docker-compose.yml run --rm \
  -e LEDGEROS_BOOTSTRAP_SELECTION_JSON="$ledgeros_bootstrap_selection_json" \
  propertyledger-web python manage.py bootstrap_ledgeros_setup_selection
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_connection_settings
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_account_mappings
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_payment_workflow_settings
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py seed_beta_demo_data
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py run_setup_smoke

echo "Beta seed complete."
echo "If the web services are not already running, start them now:"
echo "  PropertyLedger: make up"
echo "  LedgerOS v2: cd ../ledgeros_v2 && WEB_PORT=8001 make up"
echo "Open these URLs in your browser:"
echo "  PropertyLedger: http://localhost:8000/"
echo "  LedgerOS v2: http://localhost:8001/"
