from __future__ import annotations

from django.core.management.base import BaseCommand

from ledgeros.models import PropertyLedgerAccountMapping, PropertyLedgerSetup


class Command(BaseCommand):
    help = "Bootstrap the LedgerOS account mapping rows required by setup."

    DEMO_MAPPINGS = {
        PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS[0]: {
            "ledgeros_account_id": "1000",
            "ledgeros_account_name": "Operating Bank",
            "ledgeros_account_type": "asset",
            "is_required": True,
            "is_enabled": True,
        },
        PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS[1]: {
            "ledgeros_account_id": "1010",
            "ledgeros_account_name": "Undeposited Funds",
            "ledgeros_account_type": "asset",
            "is_required": True,
            "is_enabled": True,
        },
        PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS[2]: {
            "ledgeros_account_id": "1100",
            "ledgeros_account_name": "Accounts Receivable",
            "ledgeros_account_type": "asset",
            "is_required": True,
            "is_enabled": True,
        },
        PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS[3]: {
            "ledgeros_account_id": "2000",
            "ledgeros_account_name": "Accounts Payable",
            "ledgeros_account_type": "liability",
            "is_required": True,
            "is_enabled": True,
        },
        PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS[4]: {
            "ledgeros_account_id": "4000",
            "ledgeros_account_name": "Rental Income",
            "ledgeros_account_type": "revenue",
            "is_required": True,
            "is_enabled": True,
        },
        PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS[5]: {
            "ledgeros_account_id": "6100",
            "ledgeros_account_name": "Repairs and Maintenance Expense",
            "ledgeros_account_type": "expense",
            "is_required": True,
            "is_enabled": True,
        },
        PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS[6]: {
            "ledgeros_account_id": "2200",
            "ledgeros_account_name": "Tenant Security Deposits",
            "ledgeros_account_type": "liability",
            "is_required": True,
            "is_enabled": True,
        },
        PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS[7]: {
            "ledgeros_account_id": "3000",
            "ledgeros_account_name": "Owner Contributions Equity",
            "ledgeros_account_type": "equity",
            "is_required": True,
            "is_enabled": True,
        },
        PropertyLedgerSetup.REQUIRED_ACCOUNT_MAPPING_KEYS[8]: {
            "ledgeros_account_id": "3010",
            "ledgeros_account_name": "Owner Distributions Equity",
            "ledgeros_account_type": "equity",
            "is_required": True,
            "is_enabled": True,
        },
        PropertyLedgerSetup.OPTIONAL_ACCOUNT_MAPPING_KEYS[0]: {
            "ledgeros_account_id": "2100",
            "ledgeros_account_name": "Credit Card Liability",
            "ledgeros_account_type": "liability",
            "is_required": False,
            "is_enabled": False,
        },
        PropertyLedgerSetup.OPTIONAL_ACCOUNT_MAPPING_KEYS[1]: {
            "ledgeros_account_id": "2500",
            "ledgeros_account_name": "Mortgage or Loan Payable",
            "ledgeros_account_type": "liability",
            "is_required": False,
            "is_enabled": False,
        },
        PropertyLedgerSetup.OPTIONAL_ACCOUNT_MAPPING_KEYS[2]: {
            "ledgeros_account_id": "6200",
            "ledgeros_account_name": "Interest Expense",
            "ledgeros_account_type": "expense",
            "is_required": False,
            "is_enabled": False,
        },
        PropertyLedgerSetup.OPTIONAL_ACCOUNT_MAPPING_KEYS[3]: {
            "ledgeros_account_id": "2510",
            "ledgeros_account_name": "Principal Payment Mapping",
            "ledgeros_account_type": "liability",
            "is_required": False,
            "is_enabled": False,
        },
    }

    def handle(self, *args, **options):
        setup = PropertyLedgerSetup.load()
        created = 0
        updated = 0

        for mapping_key, defaults in self.DEMO_MAPPINGS.items():
            mapping, was_created = PropertyLedgerAccountMapping.objects.get_or_create(
                setup=setup,
                mapping_key=mapping_key,
                defaults={**defaults, "notes": ""},
            )
            if was_created:
                created += 1
                continue

            if (
                not mapping.ledgeros_account_id
                or not mapping.ledgeros_account_name
                or not mapping.ledgeros_account_type
            ):
                mapping.ledgeros_account_id = defaults["ledgeros_account_id"]
                mapping.ledgeros_account_name = defaults["ledgeros_account_name"]
                mapping.ledgeros_account_type = defaults["ledgeros_account_type"]
                mapping.is_required = defaults["is_required"]
                mapping.is_enabled = defaults["is_enabled"]
                mapping.save()
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                "LedgerOS account mappings bootstrapped. "
                f"Created {created} rows, updated {updated} rows."
            )
        )
