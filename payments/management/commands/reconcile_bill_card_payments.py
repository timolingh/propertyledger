from django.core.management.base import BaseCommand, CommandError

from payments.models import VendorPayment
from payments.services import VendorPaymentService


class Command(BaseCommand):
    help = "Preview or link legacy credit-card journals to bills without reposting their accounting entries."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Link verified existing journals; default is preview only.")
        parser.add_argument("--payment-id", type=int)

    def handle(self, *args, **options):
        payments = VendorPayment.objects.filter(
            payment_method=VendorPayment.PaymentMethod.CREDIT_CARD, is_credit_card_payoff=False,
        ).exclude(status=VendorPayment.Status.VOIDED).select_related("sync_record", "vendor_bill__sync_record", "vendor")
        if options["payment_id"] is not None:
            payments = payments.filter(pk=options["payment_id"])
        candidates = 0
        failures = 0
        for payment in payments:
            if payment.sync_record and payment.sync_record.ledgeros_resource_type == "payment" and payment.sync_record.status == "succeeded":
                continue
            if VendorPaymentService.legacy_card_record(payment) is None:
                continue
            candidates += 1
            self.stdout.write(f"Payment {payment.pk}: bill {payment.vendor_bill_id}, amount {payment.amount}")
            if options["apply"]:
                try:
                    result = VendorPaymentService.sync_payment(payment)
                    if not result.sync_record or result.sync_record.status != "succeeded":
                        raise CommandError("LedgerOS could not verify the existing journal; inspect the payment sync error.")
                except Exception as exc:
                    failures += 1
                    self.stderr.write(f"Payment {payment.pk}: {exc}")
        self.stdout.write(f"{'Processed' if options['apply'] else 'Previewed'} {candidates} legacy card payments.")
        if failures:
            raise CommandError(f"{failures} payments require reconciliation. No replacement journal was requested.")
