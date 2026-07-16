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
docker compose -f docker-compose.yml run --rm -T web python manage.py shell <<'PY'
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

print(period.id, period.name, period.start_date, period.end_date, period.status)
PY
popd >/dev/null

docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py migrate
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_connection_settings
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_ledgeros_account_mappings
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py bootstrap_payment_workflow_settings
docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py seed_beta_demo_data
