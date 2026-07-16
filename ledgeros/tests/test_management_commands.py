from __future__ import annotations

import os
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from ledgeros.models import (
    LedgerOSConnectionSettings,
    Owner,
    Property,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    Tenant,
    TenantCharge,
    Unit,
)
from ledgeros.roles import get_user_role_label
from payments.models import MaintenanceCategory, SecurityDepositEvent, Vendor, VendorBill, VendorPayment


class BootstrapLedgerOSConnectionSettingsCommandTests(TestCase):
    @patch.dict(
        os.environ,
        {
            "LEDGEROS_BASE_URL": "http://ledgeros-web:8000",
            "LEDGEROS_HOST_HEADER": "localhost:8001",
            "LEDGEROS_CLIENT_ID": "propertyledger",
            "LEDGEROS_HEALTH_PATH": "/api/v1/health/",
            "LEDGEROS_TIMEOUT_SECONDS": "5",
        },
        clear=False,
    )
    def test_command_persists_connection_settings_from_environment(self):
        call_command("bootstrap_ledgeros_connection_settings")

        settings_obj = LedgerOSConnectionSettings.load()
        self.assertEqual(settings_obj.base_url, "http://ledgeros-web:8000")
        self.assertEqual(settings_obj.host_header, "localhost:8001")
        self.assertEqual(settings_obj.client_id, "propertyledger")
        self.assertEqual(settings_obj.hmac_secret_env_var, "LEDGEROS_HMAC_SECRET")
        self.assertEqual(settings_obj.api_key_env_var, "LEDGEROS_API_KEY")
        self.assertEqual(settings_obj.health_path, "/api/v1/health/")
        self.assertEqual(settings_obj.timeout_seconds, 5)


class BootstrapLedgerOSAccountMappingsCommandTests(TestCase):
    def test_command_creates_required_and_optional_mapping_rows(self):
        call_command("bootstrap_ledgeros_account_mappings")

        setup = PropertyLedgerSetup.load()
        mappings = setup.account_mappings.order_by("mapping_key")

        self.assertEqual(
            mappings.count(),
            len(PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS)
            + len(PropertyLedgerSetup.OPTIONAL_ACCOUNT_MAPPING_KEYS),
        )

        for mapping in mappings:
            if mapping.mapping_key in PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS:
                self.assertTrue(mapping.is_required)
                self.assertTrue(mapping.is_enabled)
            else:
                self.assertFalse(mapping.is_required)
                self.assertFalse(mapping.is_enabled)

        rental_income = mappings.get(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.RENTAL_INCOME
        )
        self.assertEqual(rental_income.ledgeros_account_id, "4000")
        self.assertEqual(rental_income.ledgeros_account_name, "Rental Income")
        self.assertEqual(rental_income.ledgeros_account_type, "revenue")

        repairs_expense = mappings.get(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.REPAIRS_AND_MAINTENANCE_EXPENSE
        )
        self.assertEqual(repairs_expense.ledgeros_account_id, "5000")
        self.assertEqual(repairs_expense.ledgeros_account_name, "Operating Expense")
        self.assertEqual(repairs_expense.ledgeros_account_type, "expense")

        call_command("bootstrap_ledgeros_account_mappings")
        self.assertEqual(
            PropertyLedgerAccountMapping.objects.filter(setup=setup).count(),
            len(PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS)
            + len(PropertyLedgerSetup.OPTIONAL_ACCOUNT_MAPPING_KEYS),
        )

        repairs_expense.ledgeros_account_id = "6100"
        repairs_expense.ledgeros_account_name = "Repairs and Maintenance Expense"
        repairs_expense.ledgeros_account_type = "expense"
        repairs_expense.save()

        call_command("bootstrap_ledgeros_account_mappings")
        repairs_expense.refresh_from_db()
        self.assertEqual(repairs_expense.ledgeros_account_id, "5000")
        self.assertEqual(repairs_expense.ledgeros_account_name, "Operating Expense")


class BootstrapLedgerOSSetupSelectionCommandTests(TestCase):
    @patch.dict(
        os.environ,
        {
            "LEDGEROS_BOOTSTRAP_SELECTION_JSON": json.dumps(
                {
                    "entity_id": "entity_1",
                    "entity_name": "Default Entity",
                    "accounting_period_id": "period_1",
                    "accounting_period_name": "Bootstrap FY2026",
                }
            )
        },
        clear=False,
    )
    def test_command_persists_selected_entity_and_period(self):
        call_command("bootstrap_ledgeros_setup_selection")

        setup = PropertyLedgerSetup.load()
        self.assertEqual(setup.ledgeros_entity_id, "entity_1")
        self.assertEqual(setup.ledgeros_entity_name, "Default Entity")
        self.assertEqual(setup.ledgeros_accounting_period_id, "period_1")
        self.assertEqual(setup.ledgeros_accounting_period_name, "Bootstrap FY2026")


class BetaDemoDataCommandTests(TestCase):
    def test_command_seeds_beta_demo_data_and_demo_users(self):
        call_command("seed_beta_demo_data", password="BetaTest123!")

        self.assertEqual(Owner.objects.filter(name="Cedar Grove Holdings LLC").count(), 1)
        property_obj = Property.objects.get(name="Cedar Grove Apartments")
        self.assertEqual(property_obj.primary_owner.name, "Cedar Grove Holdings LLC")
        self.assertEqual(Unit.objects.filter(property=property_obj).count(), 3)
        self.assertEqual(Tenant.objects.count(), 3)
        self.assertEqual(TenantCharge.objects.filter(charge_type=TenantCharge.ChargeType.BASE_RENT).count(), 3)
        self.assertEqual(TenantCharge.objects.filter(charge_type=TenantCharge.ChargeType.OTHER_MANUAL).count(), 1)
        self.assertEqual(Vendor.objects.count(), 3)
        self.assertEqual(MaintenanceCategory.objects.count(), 3)
        self.assertEqual(VendorBill.objects.count(), 3)
        self.assertEqual(VendorPayment.objects.count(), 1)
        self.assertEqual(SecurityDepositEvent.objects.count(), 3)

        User = get_user_model()
        admin_user = User.objects.get(username="beta-admin")
        manager_user = User.objects.get(username="beta-manager")
        bookkeeper_user = User.objects.get(username="beta-bookkeeper")

        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)
        self.assertEqual(get_user_role_label(admin_user), "Admin")
        self.assertEqual(get_user_role_label(manager_user), "Property manager")
        self.assertEqual(get_user_role_label(bookkeeper_user), "Bookkeeper")
