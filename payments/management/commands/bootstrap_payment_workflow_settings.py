from __future__ import annotations

from django.core.management.base import BaseCommand

from payments.models import PaymentWorkflowSettings


class Command(BaseCommand):
    help = "Bootstrap the global payment workflow settings row."

    def handle(self, *args, **options):
        settings_obj = PaymentWorkflowSettings.load()
        if not settings_obj.charge_type_priority:
            settings_obj.charge_type_priority = PaymentWorkflowSettings._meta.get_field(
                "charge_type_priority"
            ).default()
            settings_obj.save()
        self.stdout.write(self.style.SUCCESS("Payment workflow settings bootstrapped."))
