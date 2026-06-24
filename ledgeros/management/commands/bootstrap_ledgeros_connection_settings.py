from __future__ import annotations

import os

from django.core.management.base import BaseCommand

from ledgeros.models import LedgerOSConnectionSettings


class Command(BaseCommand):
    help = "Bootstrap the LedgerOS connection settings row from environment values."

    def handle(self, *args, **options):
        settings_obj = LedgerOSConnectionSettings.load()
        settings_obj.base_url = os.getenv("LEDGEROS_BASE_URL", "http://ledgeros-web:8000")
        settings_obj.host_header = os.getenv("LEDGEROS_HOST_HEADER", "")
        settings_obj.client_id = os.getenv("LEDGEROS_CLIENT_ID", "propertyledger")
        settings_obj.hmac_secret_env_var = "LEDGEROS_HMAC_SECRET"
        settings_obj.api_key_env_var = "LEDGEROS_API_KEY"
        settings_obj.health_path = os.getenv("LEDGEROS_HEALTH_PATH", "/api/v1/health/")
        settings_obj.timeout_seconds = int(os.getenv("LEDGEROS_TIMEOUT_SECONDS", "5"))
        settings_obj.save()
        self.stdout.write(self.style.SUCCESS("LedgerOS connection settings bootstrapped."))
