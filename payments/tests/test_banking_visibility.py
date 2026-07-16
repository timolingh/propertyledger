from __future__ import annotations

import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import LedgerOSConnectionSettings
from ledgeros.roles import ROLE_BOOKKEEPER, assign_user_role
from payments.services import LedgerOSBankingReadService


class _FakeResponse:
    def __init__(self, *, status: int, payload: bytes):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def _configure_ledgeros_settings():
    settings_obj = LedgerOSConnectionSettings.load()
    settings_obj.base_url = "http://ledgeros-web:8000"
    settings_obj.client_id = "propertyledger"
    settings_obj.hmac_secret_env_var = "LEDGEROS_HMAC_SECRET"
    settings_obj.save()


class LedgerOSBankingReadServiceTests(TestCase):
    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_bank_account_listing_uses_ledgeros_banking_api(self, mock_urlopen):
        mock_urlopen.return_value = _FakeResponse(
            status=200,
            payload=json.dumps(
                [
                    {
                        "id": 1,
                        "name": "Operating Checking",
                        "bank_name": "First Bank",
                        "account_number": "1111",
                        "ledger_account_name": "Cash",
                        "ledger_account_code": "1000",
                        "status": "active",
                        "current_balance": "150.00",
                    }
                ]
            ).encode("utf-8"),
        )
        _configure_ledgeros_settings()

        bank_accounts = LedgerOSBankingReadService.list_bank_accounts()

        self.assertEqual(len(bank_accounts), 1)
        self.assertEqual(bank_accounts[0]["name"], "Operating Checking")
        self.assertEqual(mock_urlopen.call_count, 1)
        self.assertEqual(mock_urlopen.call_args.args[0].full_url, "http://ledgeros-web:8000/api/v1/bank-accounts/")


class BankingVisibilityViewTests(TestCase):
    def setUp(self):
        _configure_ledgeros_settings()
        self.user = get_user_model().objects.create_user(username="tester", password="password")
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.client.force_login(self.user)

    @patch.dict(os.environ, {"LEDGEROS_HMAC_SECRET": "secret"}, clear=False)
    @patch("payments.services.urlopen")
    def test_dashboard_renders_account_and_reconciliation_visibility(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _FakeResponse(
                status=200,
                payload=json.dumps(
                    [
                        {
                            "id": 1,
                            "name": "Operating Checking",
                            "bank_name": "First Bank",
                            "account_number": "1111",
                            "ledger_account_name": "Cash",
                            "ledger_account_code": "1000",
                            "status": "active",
                            "current_balance": "150.00",
                        }
                    ]
                ).encode("utf-8"),
            ),
            _FakeResponse(
                status=200,
                payload=json.dumps(
                    [
                        {
                            "id": 7,
                            "bank_account_name": "Operating Checking",
                            "start_date": "2026-05-01",
                            "end_date": "2026-05-31",
                            "status": "open",
                            "statement_ending_balance": "150.00",
                            "cleared_balance": "0.00",
                            "book_balance": "150.00",
                        }
                    ]
                ).encode("utf-8"),
            ),
        ]

        response = self.client.get(reverse("banking-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operating Checking")
        self.assertContains(response, "First Bank")
        self.assertContains(response, "2026-05-01 to 2026-05-31")
        self.assertContains(response, "150.00")
        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertEqual(mock_urlopen.call_args_list[0].args[0].full_url, "http://ledgeros-web:8000/api/v1/bank-accounts/")
        self.assertEqual(mock_urlopen.call_args_list[1].args[0].full_url, "http://ledgeros-web:8000/api/v1/bank-reconciliations/")
