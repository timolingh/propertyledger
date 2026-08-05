from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from ledgeros.services import SetupSmokeService


class Command(BaseCommand):
    help = "Run the setup smoke check and persist the result on PropertyLedgerSetup."

    def handle(self, *args, **options):
        result = SetupSmokeService.run_and_record()
        if result.healthy:
            self.stdout.write(self.style.SUCCESS("Setup smoke passed and was recorded."))
            return

        raise CommandError(
            "Setup smoke failed: "
            + json.dumps(result.details, sort_keys=True, ensure_ascii=False)
        )
