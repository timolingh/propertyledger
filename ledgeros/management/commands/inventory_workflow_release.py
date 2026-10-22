import json

from django.core.management.base import BaseCommand
from django.db.models import Q

from ledgeros.models import LedgerOSSyncRecord
from payments.models import SecurityDepositEvent, TenantPayment, VendorBill, VendorPayment


class Command(BaseCommand):
    help = "Read-only inventory of legacy and in-flight rows before a workflow release or rollback."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        inventory = {
            "vendor_bills_without_recorded_approval": VendorBill.objects.filter(
                approval_status__in=(VendorBill.ApprovalStatus.DRAFT, VendorBill.ApprovalStatus.SUBMITTED)
            ).exclude(status=VendorBill.Status.VOIDED).count(),
            "attempted_vendor_payments": VendorPayment.objects.filter(
                sync_record__attempt_count__gt=0
            ).exclude(sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED).count(),
            "legacy_deposit_events_without_journal": SecurityDepositEvent.objects.filter(
                sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED
            ).filter(Q(sync_record__ledgeros_journal_entry_id="") | Q(sync_record__ledgeros_journal_entry_id__isnull=True)).count(),
            "legacy_parent_only_receipts": TenantPayment.objects.filter(
                sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
                applications__isnull=True,
                deposit_allocation__isnull=True,
            ).distinct().count(),
        }
        if options["as_json"]:
            self.stdout.write(json.dumps(inventory, sort_keys=True))
            return
        self.stdout.write("PropertyLedger workflow release inventory (read only)")
        for label, count in inventory.items():
            self.stdout.write(f"{label}: {count}")
