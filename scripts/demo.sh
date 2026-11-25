#!/usr/bin/env bash
# Reset and launch an isolated, local-only demonstration of both applications.
set -euo pipefail
umask 077
export LC_ALL=C

usage() {
  cat <<'HELP'
Usage: ./scripts/demo.sh [--non-interactive]

Recreates ONLY the propertyledger-demo Docker Compose project and its databases.
Starts PropertyLedger at http://localhost:8100 and LedgerOS at http://localhost:8101.
Prompts to create the LedgerOS superuser; prints generated PropertyLedger logins.
Seeds 3 maintenance, 2 tenant invoicing, and 2 bill payment walkthroughs.

Requirements: Docker with Compose, bash, tar, openssl, and sibling ../ledgeros_v2.
Override the sibling path with DEMO_LEDGEROS_REPO; change ports with
DEMO_PROPERTYLEDGER_PORT and DEMO_LEDGEROS_PORT. Production .env files are ignored.

For automation, --non-interactive requires DJANGO_SUPERUSER_USERNAME,
DJANGO_SUPERUSER_EMAIL, and DJANGO_SUPERUSER_PASSWORD in the environment.
Every invocation resets the demo. Connection details are saved under .demo/.
HELP
}

non_interactive=0
case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --non-interactive) non_interactive=1 ;;
  "") ;;
  *) usage >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then usage >&2; exit 2; fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ledgeros_root="${DEMO_LEDGEROS_REPO:-$repo_root/../ledgeros_v2}"
state_dir="$repo_root/.demo"
pl_port="${DEMO_PROPERTYLEDGER_PORT:-8100}"
lo_port="${DEMO_LEDGEROS_PORT:-8101}"

for executable in docker tar openssl; do
  command -v "$executable" >/dev/null || { echo "Missing $executable." >&2; exit 1; }
done
docker compose version >/dev/null
docker info >/dev/null
if [[ ! -f "$ledgeros_root/manage.py" || ! -f "$ledgeros_root/api_clients.yml" ]]; then
  echo "LedgerOS v2 repository not found: $ledgeros_root" >&2
  exit 1
fi
ledgeros_root="$(cd "$ledgeros_root" && pwd)"
for port in "$pl_port" "$lo_port"; do
  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( ${#port} > 5 )) || (( 10#$port < 1024 || 10#$port > 65535 )); then
    echo "Demo ports must be numbers between 1024 and 65535." >&2
    exit 1
  fi
done
if (( 10#$pl_port == 10#$lo_port )); then
  echo "The two demo ports must differ." >&2
  exit 1
fi
if (( non_interactive )); then
  : "${DJANGO_SUPERUSER_USERNAME:?Set DJANGO_SUPERUSER_USERNAME for automation}"
  : "${DJANGO_SUPERUSER_EMAIL:?Set DJANGO_SUPERUSER_EMAIL for automation}"
  : "${DJANGO_SUPERUSER_PASSWORD:?Set DJANGO_SUPERUSER_PASSWORD for automation}"
elif [[ ! -t 0 || ! -t 1 ]]; then
  echo "Run in a terminal for the LedgerOS superuser prompt, or use --non-interactive (see --help)." >&2
  exit 1
fi

mkdir -p "$state_dir"
chmod 700 "$state_dir"
# An atomic directory lock prevents two launches from resetting each other's data.
if ! mkdir "$state_dir/launch.lock" 2>/dev/null; then
  echo "A demo launch is already in progress. If it was killed, remove .demo/launch.lock and rerun." >&2
  exit 1
fi
build_dir=""
complete=0
cleanup() {
  local result=$?
  if [[ -n "$build_dir" ]]; then rm -rf -- "$build_dir"; fi
  rmdir "$state_dir/launch.lock"
  if (( ! complete )); then
    echo "Demo setup did not finish. Fix the reported error and rerun this script; it will reset the demo again." >&2
    echo "Inspect with: docker compose -p propertyledger-demo --env-file .demo/demo.env -f .demo/compose.yml logs --tail=100" >&2
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/propertyledger-demo.XXXXXX")"
mkdir "$build_dir/propertyledger" "$build_dir/ledgeros"
copy_source() {
  # Never bake workstation credentials, databases, or an earlier demo into images.
  tar -C "$1" --exclude=.git --exclude=.demo --exclude=.env --exclude='.env.*' \
    --exclude=.venv --exclude=venv --exclude=node_modules --exclude=__pycache__ \
    --exclude=db.sqlite3 --exclude=staticfiles --exclude=media --exclude=postgres_data \
    --exclude='*.dump' --exclude='*.sql' --exclude=.aws --exclude=.codex \
    -cf - . | tar -C "$2" -xf -
}
echo "Preparing clean demo image sources without workstation environment files."
copy_source "$repo_root" "$build_dir/propertyledger"
copy_source "$ledgeros_root" "$build_dir/ledgeros"

# All interpolation names are demo-specific. Existing application environment
# variables and .env files cannot redirect this stack to another database/API.
unset DEMO_PL_CONTEXT DEMO_LO_CONTEXT DEMO_PL_PORT DEMO_LO_PORT \
  DEMO_DATABASE_PASSWORD DEMO_PL_SECRET DEMO_LO_SECRET DEMO_HMAC_SECRET DEMO_USER_PASSWORD
cat > "$state_dir/demo.env" <<ENV
DEMO_PL_CONTEXT=$build_dir/propertyledger
DEMO_LO_CONTEXT=$build_dir/ledgeros
DEMO_PL_PORT=$pl_port
DEMO_LO_PORT=$lo_port
DEMO_DATABASE_PASSWORD=$(openssl rand -hex 24)
DEMO_PL_SECRET=$(openssl rand -hex 32)
DEMO_LO_SECRET=$(openssl rand -hex 32)
DEMO_HMAC_SECRET=$(openssl rand -hex 32)
DEMO_USER_PASSWORD=$(openssl rand -hex 12)
ENV
cat > "$state_dir/compose.yml" <<'YAML'
services:
  ledgeros-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ledgeros_demo
      POSTGRES_USER: ledgeros_demo
      POSTGRES_PASSWORD: ${DEMO_DATABASE_PASSWORD:?}
    volumes:
      - ledgeros_demo_data:/var/lib/postgresql/data
    healthcheck:
      test: [CMD-SHELL, 'pg_isready -U ledgeros_demo -d ledgeros_demo']
      interval: 2s
      timeout: 5s
      retries: 30
  propertyledger-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: propertyledger_demo
      POSTGRES_USER: propertyledger_demo
      POSTGRES_PASSWORD: ${DEMO_DATABASE_PASSWORD:?}
    volumes:
      - propertyledger_demo_data:/var/lib/postgresql/data
    healthcheck:
      test: [CMD-SHELL, 'pg_isready -U propertyledger_demo -d propertyledger_demo']
      interval: 2s
      timeout: 5s
      retries: 30
  ledgeros-web:
    image: propertyledger-demo-ledgeros:local
    build: ${DEMO_LO_CONTEXT:?}
    command: python manage.py runserver 0.0.0.0:8000 --noreload
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.local
      DJANGO_SECRET_KEY: ${DEMO_LO_SECRET:?}
      DJANGO_DEBUG: "1"
      DJANGO_ALLOWED_HOSTS: localhost,127.0.0.1,ledgeros-web
      LEDGEROS_API_CLIENTS_CONFIG: /app/api_clients.yml
      LEDGEROS_API_CLIENT_FULL_SECRET: ${DEMO_HMAC_SECRET:?}
      POSTGRES_DB: ledgeros_demo
      POSTGRES_USER: ledgeros_demo
      POSTGRES_PASSWORD: ${DEMO_DATABASE_PASSWORD:?}
      POSTGRES_HOST: ledgeros-db
      POSTGRES_PORT: "5432"
    ports:
      - "127.0.0.1:${DEMO_LO_PORT:?}:8000"
    depends_on:
      ledgeros-db:
        condition: service_healthy
  propertyledger-web:
    image: propertyledger-demo-propertyledger:local
    build: ${DEMO_PL_CONTEXT:?}
    command: python manage.py runserver 0.0.0.0:8000 --noreload
    environment:
      DJANGO_SETTINGS_MODULE: propertyledger.settings
      DJANGO_SECRET_KEY: ${DEMO_PL_SECRET:?}
      DJANGO_DEBUG: "1"
      DJANGO_ALLOWED_HOSTS: localhost,127.0.0.1,propertyledger-web
      DATABASE_ENGINE: django.db.backends.postgresql
      DATABASE_NAME: propertyledger_demo
      DATABASE_USER: propertyledger_demo
      DATABASE_PASSWORD: ${DEMO_DATABASE_PASSWORD:?}
      DATABASE_HOST: propertyledger-db
      DATABASE_PORT: "5432"
      LEDGEROS_BASE_URL: http://ledgeros-web:8000
      LEDGEROS_HOST_HEADER: ""
      LEDGEROS_CLIENT_ID: api_full
      LEDGEROS_HMAC_SECRET: ${DEMO_HMAC_SECRET:?}
      LEDGEROS_API_KEY: ""
      LEDGEROS_HEALTH_PATH: /api/v1/health/
      LEDGEROS_TIMEOUT_SECONDS: "5"
      DEMO_USER_PASSWORD: ${DEMO_USER_PASSWORD:?}
      DEMO_BROWSER_URL: http://localhost:${DEMO_PL_PORT:?}
    ports:
      - "127.0.0.1:${DEMO_PL_PORT:?}:8000"
    depends_on:
      propertyledger-db:
        condition: service_healthy
volumes:
  ledgeros_demo_data:
  propertyledger_demo_data:
YAML

demo() {
  docker compose --ansi never --project-name propertyledger-demo --env-file "$state_dir/demo.env" \
    -f "$state_dir/compose.yml" "$@"
}
demo config --quiet
echo "Resetting ONLY project propertyledger-demo and its two demo database volumes."
demo down --volumes --remove-orphans
printf 'Demo reset in progress; credentials will be written after successful seeding.\n' > "$state_dir/summary.txt"
demo build
demo up -d ledgeros-db propertyledger-db
demo run --rm ledgeros-web python manage.py migrate --noinput
demo run --rm propertyledger-web python manage.py migrate --noinput

echo "Create the LedgerOS demo superuser (username, email, and password):"
if (( non_interactive )); then
  demo run --rm -T -e DJANGO_SUPERUSER_USERNAME -e DJANGO_SUPERUSER_EMAIL \
    -e DJANGO_SUPERUSER_PASSWORD ledgeros-web python manage.py createsuperuser --noinput
else
  demo run --rm ledgeros-web python manage.py createsuperuser
fi
demo run --rm ledgeros-web python manage.py import_coa config/sample_chart_of_accounts.yml
demo up -d ledgeros-web

wait_for_http() {
  demo exec -T "$1" python - "$2" <<'PY'
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

for attempt in range(60):
    try:
        with urlopen(sys.argv[1], timeout=2) as response:
            if response.status == 200:
                break
    except (HTTPError, URLError, TimeoutError):
        pass
    time.sleep(1)
else:
    raise SystemExit(f"Timed out waiting for {sys.argv[1]}")
PY
}
wait_for_http ledgeros-web http://localhost:8000/api/v1/health/

ledgeros_output="$(demo exec -T ledgeros-web python manage.py shell <<'PY'
import json
from datetime import date
from apps.accounting.models import Account
from apps.accounting.services import create_accounting_period, get_default_entity, save_account

entity = get_default_entity()
for code, name in (("2200", "Tenant Security Deposits"), ("3010", "Owner Distributions Equity")):
    save_account(entity=entity, account_code=code, name=name,
                 type="liability" if code == "2200" else "equity", normal_balance="credit")
year = date.today().year
period = create_accounting_period(start_date=date(year, 1, 1), end_date=date(year, 12, 31), name=f"Demo FY{year}")
selection = {
    "entity_id": str(entity.pk), "entity_name": entity.name,
    "accounting_period_id": str(period.pk), "accounting_period_name": period.name,
    "accounts": {a.account_code: {"name": a.name, "type": a.type}
                 for a in Account.objects.filter(entity=entity)},
}
print("DEMO_SELECTION=" + json.dumps(selection))
PY
)"
selection="$(printf '%s\n' "$ledgeros_output" | sed -n 's/^DEMO_SELECTION=//p')"
if [[ -z "$selection" ]]; then echo "LedgerOS did not return demo accounting setup." >&2; exit 1; fi
demo run --rm -T -e LEDGEROS_BOOTSTRAP_SELECTION_JSON="$selection" \
  propertyledger-web python manage.py bootstrap_ledgeros_setup_selection
demo run --rm propertyledger-web python manage.py bootstrap_ledgeros_connection_settings
demo run --rm propertyledger-web python manage.py bootstrap_ledgeros_account_mappings
demo run --rm propertyledger-web python manage.py bootstrap_payment_workflow_settings
demo up -d propertyledger-web
wait_for_http propertyledger-web http://localhost:8000/api/health/local/

demo exec -T -e DEMO_SELECTION_JSON="$selection" propertyledger-web python manage.py shell <<'PY' | tee "$state_dir/summary.txt"
import json
import os
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from ledgeros.models import Lease, Owner, Property, PropertyLedgerSetup, Tenant, TenantCharge, Unit
from ledgeros.roles import ROLE_ADMIN, ROLE_BOOKKEEPER, ROLE_PROPERTY_MANAGER, assign_user_role
from ledgeros.services import LedgerOSCustomerSyncService, TenantChargeService
from payments.approval_services import VendorBillApprovalService, WorkflowAuthorizationService
from payments.maintenance_services import MaintenanceRequestService
from payments.models import MaintenanceCategory, MaintenanceRequest, TenantPayment, Vendor, VendorBill, VendorPayment
from payments.services import BillPaymentStatusService, VendorBillService, VendorService

today = date.today()
month_start, month_end = TenantChargeService.month_bounds(today)
selection = json.loads(os.environ["DEMO_SELECTION_JSON"])
setup = PropertyLedgerSetup.load()
for mapping in setup.account_mappings.filter(is_enabled=True):
    account = selection["accounts"][mapping.ledgeros_account_id]
    mapping.ledgeros_account_name = account["name"]
    mapping.ledgeros_account_type = account["type"]
    mapping.full_clean()
    mapping.save()
call_command("run_setup_smoke")

password = os.environ["DEMO_USER_PASSWORD"]
users = {}
for username, role in (("demo-admin", ROLE_ADMIN), ("demo-manager", ROLE_PROPERTY_MANAGER), ("demo-bookkeeper", ROLE_BOOKKEEPER)):
    user = get_user_model().objects.create_user(username=username, password=password, is_staff=role == ROLE_ADMIN)
    assign_user_role(user, role)
    users[role] = user
admin, manager, bookkeeper = users[ROLE_ADMIN], users[ROLE_PROPERTY_MANAGER], users[ROLE_BOOKKEEPER]
WorkflowAuthorizationService.set_grants(target=manager, actor=admin, can_approve_vendor_bills=True, can_pay_vendor_bills=False)
WorkflowAuthorizationService.set_grants(target=bookkeeper, actor=admin, can_approve_vendor_bills=False, can_pay_vendor_bills=True)

owner = Owner.objects.create(name="Demo Property Holdings", email="owner@example.test")
property_obj = Property.objects.create(name="Maple Court Demo", primary_owner=owner)
leases = []
for number, name, rent in (("101", "Alex Morgan", "1500.00"), ("102", "Jamie Chen", "1250.00")):
    unit = Unit.objects.create(property=property_obj, name=number)
    tenant = Tenant.objects.create(name=name, email=f"tenant{number}@example.test")
    lease = Lease.objects.create(unit=unit, tenant=tenant, lease_start_date=month_start,
                                 base_monthly_rent_amount=Decimal(rent), deposit_required_amount=Decimal("0.00"),
                                 status=Lease.Status.ACTIVE)
    LedgerOSCustomerSyncService.provision_tenant(tenant=tenant, actor=manager,
        reviewed_payload=LedgerOSCustomerSyncService.tenant_provisioning_payload(tenant))
    leases.append(lease)

categories = [MaintenanceCategory.objects.create(name=name) for name in ("Plumbing", "Electrical", "General")]
vendors = []
for name in ("Demo Plumbing", "Demo Electric"):
    vendor = VendorService.save_and_sync_vendor(Vendor(name=name, payment_terms=Vendor.PaymentTerms.NET_30))
    if not vendor.sync_record or vendor.sync_record.status != "succeeded":
        raise RuntimeError(f"Vendor provisioning failed: {vendor.sync_record.last_error if vendor.sync_record else name}")
    vendors.append(vendor)

maintenance = []
for index, (description, actions, cost) in enumerate((
    ("Kitchen faucet drips in unit 101", (), "120.00"),
    ("Hallway light is out in unit 102", ("triage", "assign"), "180.00"),
    ("Tighten the loose courtyard gate latch", ("triage", "assign", "start"), "60.00"),
)):
    lease = leases[index] if index < 2 else None
    request = MaintenanceRequestService.create(actor=manager, property=property_obj,
        unit=lease.unit if lease else None, tenant=lease.tenant if lease else None,
        category=categories[index], description=description, estimated_cost=Decimal(cost),
        target_completion_date=today + timedelta(days=3), source_reference=f"DEMO-M{index+1}")
    for action in actions:
        request = MaintenanceRequestService.transition(request=request, action=action, actor=manager,
            expected_version=request.version, assigned_vendor=vendors[index % 2] if action == "assign" else None)
    maintenance.append(request)

invoices = []
for index, lease in enumerate(leases):
    charge = TenantCharge(property=property_obj, unit=lease.unit, tenant=lease.tenant, lease=lease,
        charge_type=TenantCharge.ChargeType.BASE_RENT, billing_period_start=month_start,
        billing_period_end=month_end, charge_date=today, due_date=today,
        amount=lease.base_monthly_rent_amount, description=f"Demo rent for unit {lease.unit.name}")
    charge.full_clean()
    charge.save()
    if index == 1:
        charge = TenantChargeService.approve_charge(charge)
        if charge.status != TenantCharge.Status.SYNCED:
            raise RuntimeError(f"Invoice posting failed: {charge.sync_record.last_error}")
    invoices.append(charge)

bills = []
for index, amount in enumerate(("240.00", "180.00")):
    bill = VendorBillApprovalService.save_draft(VendorBill(vendor=vendors[index], property=property_obj,
        vendor_invoice_number=f"DEMO-B{index+1}", bill_date=today, due_date=today,
        amount=Decimal(amount), expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
        maintenance_category=categories[index], repair_notes=("Replace sink trap", "Replace light fixture")[index]), actor=bookkeeper)
    bill = VendorBillApprovalService.submit(bill, actor=bookkeeper)
    bill = VendorBillApprovalService.approve(bill, actor=manager)
    bill = VendorBillService.sync_bill(bill, actor=bookkeeper)
    if bill.status != VendorBill.Status.POSTED:
        raise RuntimeError(f"Bill posting failed: {bill.sync_record.last_error}")
    bills.append(bill)

# Fail the launcher rather than reporting a partially populated demo as ready.
assert MaintenanceRequest.objects.count() == 3
assert [r.status for r in maintenance] == ["open", "assigned", "in_progress"]
assert TenantCharge.objects.count() == 2
assert [i.status for i in invoices] == ["draft", "synced"]
assert VendorBill.objects.count() == 2
assert all(b.status == "posted" and b.approval_status == "approved" for b in bills)
assert TenantPayment.objects.count() == VendorPayment.objects.count() == 0
payment_statuses = BillPaymentStatusService.statuses(bills)
assert all(payment_statuses[b.pk]["status"] == "unpaid" and payment_statuses[b.pk]["balance"] == b.amount for b in bills), payment_statuses

url = os.environ["DEMO_BROWSER_URL"]
print("\nDemo walkthroughs\n")
for number, (request, action) in enumerate(zip(maintenance, (
    "Triage, assign a vendor, and start the faucet repair.",
    "Start the assigned light repair, then verify and close it.",
    "Verify the gate repair and close with Vendor invoice pending.",
)), 1):
    print(f"M{number}: {request.description} [{request.get_status_display()}]")
    print(f"    {url}{reverse('maintenance-request-detail', args=[request.pk])}\n    {action}")
for number, (invoice, action) in enumerate(zip(invoices, (
    "Review and post the $1,500 draft invoice, then record its receipt.",
    "Review the posted $1,250 invoice and record its receipt.",
)), 1):
    print(f"I{number}: Unit {invoice.unit.name} [{invoice.get_status_display()}]")
    print(f"    {url}{reverse('charge-detail', args=[invoice.pk])}\n    {action}")
for number, (bill, action) in enumerate(zip(bills, (
    "Record a full $240 payment; expect zero balance due.",
    "Record a $90 partial payment; expect $90 remaining.",
)), 1):
    print(f"B{number}: {bill.vendor.name}, ${bill.amount} [Approved, posted, unpaid]")
    print(f"    {url}{reverse('vendor-bill-detail', args=[bill.pk])}\n    {action}")
print("\nPropertyLedger demo accounts (same generated password for all three):")
print("  demo-admin: setup and administration")
print("  demo-manager: maintenance and bill approval")
print("  demo-bookkeeper: invoicing, receipts, and bill payments")
print(f"  Password: {password}")
print("\nAll records and accounting postings belong to the isolated demo databases.")
PY

demo exec -T ledgeros-web python manage.py shell <<'PY'
from apps.accounting.models import Bill, Customer, Invoice, JournalEntry, Payment, Vendor

assert Customer.objects.count() == 2
assert Vendor.objects.count() == 2
assert Invoice.objects.count() == 1  # The other invoice remains a local draft.
assert Bill.objects.count() == 2
assert Payment.objects.count() == 0
entries = list(JournalEntry.objects.filter(status=JournalEntry.Status.POSTED))
assert len(entries) == 3
assert all(entry.total_debits == entry.total_credits and entry.total_debits > 0 for entry in entries)
print("LedgerOS verified: two customers, two vendors, one invoice, two unpaid bills, and three balanced postings.")
PY

demo exec -T propertyledger-web python manage.py check
demo exec -T propertyledger-web python manage.py makemigrations --check --dry-run
demo exec -T ledgeros-web python manage.py check
wait_for_http propertyledger-web http://localhost:8000/api/health/ledgeros/
complete=1
echo
echo "Demo ready: PropertyLedger http://localhost:$pl_port/ | LedgerOS http://localhost:$lo_port/admin/"
echo "Use the LedgerOS superuser you created at the prompt."
echo "PropertyLedger walkthroughs and passwords: .demo/summary.txt (keep private)."
echo "Rerun ./scripts/demo.sh to reset only this demo and restore all seven scenarios."
