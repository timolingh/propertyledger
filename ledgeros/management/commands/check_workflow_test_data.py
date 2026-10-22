from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ledgeros.models import Property, TenantCharge
from ledgeros.roles import get_user_role_label
from payments.models import MaintenanceRequest, TenantPayment, VendorBill, WorkflowAuthorization


class Command(BaseCommand):
    help = "Verify that the guided workflow-test fixture pack is present and report its current state."

    def handle(self, *args, **options):
        failures = []
        users = {
            user.username: user
            for user in get_user_model().objects.filter(username__startswith="beta-")
        }
        expected_users = {
            "beta-admin": "Admin",
            "beta-manager": "Property manager",
            "beta-bookkeeper": "Bookkeeper",
            "beta-owner-viewer": "Owner viewer",
            "beta-read-only": "Read-only viewer",
        }
        missing_users = sorted(expected_users.keys() - users.keys())
        if missing_users:
            failures.append(f"missing users: {', '.join(missing_users)}")
        for username, role_label in expected_users.items():
            if username in users and get_user_role_label(users[username]) != role_label:
                failures.append(f"{username} does not have role {role_label}")

        expected_grants = {
            "beta-admin": (True, True),
            "beta-manager": (True, False),
            "beta-bookkeeper": (False, True),
        }
        for username, (can_approve, can_pay) in expected_grants.items():
            if username not in users:
                continue
            grant = WorkflowAuthorization.objects.filter(user=users[username]).first()
            if grant is None or (grant.can_approve_vendor_bills, grant.can_pay_vendor_bills) != (can_approve, can_pay):
                failures.append(f"{username} workflow grants do not match the guided scenario")

        property_obj = Property.objects.filter(name="Cedar Grove Apartments").first()
        if property_obj is None:
            failures.append("missing Cedar Grove Apartments")

        receipt = TenantPayment.objects.filter(reference="BETA-MIXED-RECEIPT").select_related(
            "deposit_allocation"
        ).first()
        if receipt is None:
            failures.append("missing BETA-MIXED-RECEIPT")
        elif not hasattr(receipt, "deposit_allocation") or receipt.deposit_allocation.amount != Decimal("500.00"):
            failures.append("BETA-MIXED-RECEIPT does not have the expected 500.00 deposit component")

        maintenance = {
            request.source_reference: request
            for request in MaintenanceRequest.objects.filter(source_reference__startswith="BETA-MAINT-")
        }
        expected_maintenance = {
            "BETA-MAINT-OPEN": MaintenanceRequest.Status.OPEN,
            "BETA-MAINT-HOLD": MaintenanceRequest.Status.ON_HOLD,
            "BETA-MAINT-INVOICE-PENDING": MaintenanceRequest.Status.CLOSED,
        }
        for reference, initial_status in expected_maintenance.items():
            request = maintenance.get(reference)
            if request is None:
                failures.append(f"missing {reference}")
            elif request.status != initial_status:
                self.stdout.write(
                    self.style.WARNING(
                        f"{reference}: current status={request.status}; initial seeded status={initial_status} (scenario may have been exercised)"
                    )
                )

        if property_obj is not None and not TenantCharge.objects.filter(property=property_obj).exists():
            failures.append("missing tenant charges")
        if property_obj is not None and VendorBill.objects.filter(property=property_obj).count() < 3:
            failures.append("fewer than three vendor-bill scenarios")

        if failures:
            raise CommandError("Workflow test data is incomplete: " + "; ".join(failures))

        self.stdout.write(self.style.SUCCESS("Workflow test data is present."))
        self.stdout.write("Users: " + ", ".join(sorted(expected_users)))
        self.stdout.write(
            f"Mixed receipt: BETA-MIXED-RECEIPT status={receipt.status} amount={receipt.amount} deposit={receipt.deposit_allocation.amount}"
        )
        self.stdout.write(
            "Maintenance: "
            + ", ".join(
                f"{reference}={maintenance[reference].status}"
                for reference in sorted(expected_maintenance)
            )
        )
        self.stdout.write(
            "Vendor bills: "
            + ", ".join(
                f"{bill.vendor.name}={bill.approval_status}/{bill.status}"
                for bill in VendorBill.objects.filter(property=property_obj).select_related("vendor").order_by("vendor__name")
            )
        )
