from __future__ import annotations

import os
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from ledgeros.models import LedgerOSConnectionSettings


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
