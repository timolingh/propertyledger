"""Export UI acceptance fixtures in an isolated test DB; run via manage.py shell.

docker compose -f docker-compose.yml run --rm propertyledger-web python manage.py shell -c \
    "exec(open('scripts/export-workflow-preview.py').read())"
"""
from datetime import date
from pathlib import Path
from shutil import copyfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, override_settings
from django.test.runner import DiscoverRunner

from ledgeros.models import Owner, Property, PropertyLedgerAccountMapping, PropertyLedgerSetup, Tenant
from ledgeros.roles import ROLE_ADMIN, ROLE_READ_ONLY_VIEWER, assign_user_role
from ledgeros.services import HealthCheckResult
from payments.models import TenantPayment


runner = DiscoverRunner(verbosity=0, interactive=False)
connection.settings_dict["TEST"]["NAME"] = "test_propertyledger_workflow_preview"
old_config = runner.setup_databases()
try:
    output = Path("docs/qa/wp1")
    output.mkdir(parents=True, exist_ok=True)
    admin = get_user_model().objects.create_user(username="demo-admin", is_staff=True)
    viewer = get_user_model().objects.create_user(username="demo-viewer")
    assign_user_role(admin, ROLE_ADMIN)
    assign_user_role(viewer, ROLE_READ_ONLY_VIEWER)
    setup = PropertyLedgerSetup.objects.create(setup_status="complete", ledgeros_entity_id="demo", ledgeros_entity_name="Demo books", ledgeros_accounting_period_id="demo-period", ledgeros_accounting_period_name="Demo open period", last_ledgeros_health_check_healthy=True, last_setup_smoke_healthy=True)
    for key in setup.REQUIRED_ACCOUNT_MAPPING_KEYS:
        PropertyLedgerAccountMapping.objects.create(setup=setup, mapping_key=key, ledgeros_account_id=key, ledgeros_account_name=key, ledgeros_account_type=sorted(PropertyLedgerAccountMapping.ACCOUNT_TYPE_HINTS[key])[0])
    owner = Owner.objects.create(name="Cedar Grove Holdings LLC")
    property_obj = Property.objects.create(name="Cedar Grove Apartments", primary_owner=owner)
    tenant = Tenant.objects.create(name="Avery Jordan")
    TenantPayment.objects.create(property=property_obj, tenant=tenant, payment_date=date(2026, 10, 21), amount="1450.00", payment_method="check", reference="October rent · check 1042", status="allocated")
    client = Client()
    with override_settings(ALLOWED_HOSTS=["testserver"]), patch("ledgeros.services.LedgerOSHealthCheckService.check") as health:
        health.return_value = HealthCheckResult(healthy=True, source="ledgeros", details={})
        client.force_login(admin)
        for name, url in (("home.html", "/home/"), ("records.html", "/properties/")):
            response = client.get(url)
            assert response.status_code == 200, (url, response.status_code)
            (output / name).write_bytes(response.content)
        client.force_login(viewer)
        (output / "viewer.html").write_bytes(client.get("/home/").content)
        health.return_value = HealthCheckResult(healthy=False, source="ledgeros", details={"error": "connection failed"})
        (output / "outage.html").write_bytes(client.get("/home/").content)
    for name in ("workflows.css", "navigation.js"):
        copyfile(Path("ledgeros/static/ledgeros") / name, output / name)
    print("Exported fictional UI fixtures to docs/qa/wp1; no real LedgerOS request was sent.")
finally:
    runner.teardown_databases(old_config)
