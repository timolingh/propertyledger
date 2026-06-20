from __future__ import annotations

import os
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from ledgeros.models import (
    LedgerOSConnectionSettings,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
)


class BootstrapLedgerOSConnectionSettingsCommandTests(TestCase):
    @patch.dict(
        os.environ,
        {
            "LEDGEROS_BASE_URL": "http://ledgeros-web:8000",
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

        call_command("bootstrap_ledgeros_account_mappings")
        self.assertEqual(
            PropertyLedgerAccountMapping.objects.filter(setup=setup).count(),
            len(PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS)
            + len(PropertyLedgerSetup.OPTIONAL_ACCOUNT_MAPPING_KEYS),
        )
