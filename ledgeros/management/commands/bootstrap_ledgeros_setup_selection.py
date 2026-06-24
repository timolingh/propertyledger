from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError

from ledgeros.models import PropertyLedgerSetup


class Command(BaseCommand):
    help = "Persist the selected LedgerOS entity and accounting period from bootstrap data."

    def handle(self, *args, **options):
        raw_selection = os.getenv("LEDGEROS_BOOTSTRAP_SELECTION_JSON", "").strip()
        if not raw_selection:
            raise CommandError(
                "Missing LEDGEROS_BOOTSTRAP_SELECTION_JSON. "
                "Set it to a JSON object with entity and accounting period details."
            )

        try:
            selection = json.loads(raw_selection)
        except json.JSONDecodeError as exc:
            raise CommandError(
                "LEDGEROS_BOOTSTRAP_SELECTION_JSON must be valid JSON."
            ) from exc

        try:
            entity_id = str(selection["entity_id"]).strip()
            entity_name = str(selection["entity_name"]).strip()
            accounting_period_id = str(selection["accounting_period_id"]).strip()
            accounting_period_name = str(selection["accounting_period_name"]).strip()
        except KeyError as exc:
            raise CommandError(
                "LEDGEROS_BOOTSTRAP_SELECTION_JSON must include "
                "entity_id, entity_name, accounting_period_id, and accounting_period_name."
            ) from exc

        if not entity_id or not entity_name:
            raise CommandError("LedgerOS entity id and name must be non-empty.")
        if not accounting_period_id or not accounting_period_name:
            raise CommandError("Accounting period id and name must be non-empty.")

        setup = PropertyLedgerSetup.load()
        setup.ledgeros_entity_id = entity_id
        setup.ledgeros_entity_name = entity_name
        setup.ledgeros_accounting_period_id = accounting_period_id
        setup.ledgeros_accounting_period_name = accounting_period_name
        setup.save()

        self.stdout.write(
            self.style.SUCCESS(
                "LedgerOS setup selection bootstrapped: "
                f"entity={entity_id} ({entity_name}), "
                f"period={accounting_period_id} ({accounting_period_name})"
            )
        )
