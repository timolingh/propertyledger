from __future__ import annotations

import os
from dataclasses import dataclass
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from ledgeros.models import LedgerOSConnectionSettings
from ledgeros.services import LedgerOSHealthCheckService, LocalHealthCheckService


class LocalHealthCheckTests(TestCase):
    def test_local_health_check_is_healthy_when_database_is_available(self):
        result = LocalHealthCheckService.check()

        self.assertTrue(result.healthy)
        self.assertEqual(result.source, "local")
        self.assertEqual(result.details["database"], "healthy")


@dataclass
class _FakeResponse:
    status: int
    payload: bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class LedgerOSHealthCheckTests(TestCase):
    def setUp(self):
        self.settings_obj = LedgerOSConnectionSettings.load()
        self.settings_obj.base_url = "http://ledgeros.example"
        self.settings_obj.client_id = "propertyledger"
        self.settings_obj.hmac_secret_env_var = "TEST_LEDGEROS_HMAC_SECRET"
        self.settings_obj.health_path = "/health/"
        self.settings_obj.timeout_seconds = 5
        self.settings_obj.save()

    def test_missing_secret_configuration_is_unhealthy(self):
        with patch.dict(os.environ, {"UNSET_LEDGEROS_HMAC_SECRET": ""}, clear=False):
            self.settings_obj.hmac_secret_env_var = "UNSET_LEDGEROS_HMAC_SECRET"
            self.settings_obj.save()

            result = LedgerOSHealthCheckService.check()

        self.assertFalse(result.healthy)
        self.assertEqual(result.details["error"], "missing_configuration")

    @patch.dict(os.environ, {"TEST_LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("ledgeros.services.urlopen")
    def test_successful_health_response_is_healthy(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            status=200,
            payload=b'{"status":"ok"}',
        )

        result = LedgerOSHealthCheckService.check()

        self.assertTrue(result.healthy)
        self.assertEqual(result.source, "ledgeros")
        self.assertEqual(result.details["http_status"], 200)
        self.assertEqual(result.details["payload"], {"status": "ok"})

    @patch.dict(os.environ, {"TEST_LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("ledgeros.services.urlopen")
    def test_non_2xx_health_response_is_unhealthy(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            status=503,
            payload=b'{"status":"down"}',
        )

        result = LedgerOSHealthCheckService.check()

        self.assertFalse(result.healthy)
        self.assertEqual(result.details["http_status"], 503)
