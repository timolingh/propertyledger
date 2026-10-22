"""Read-only composition for workflow home; posting belongs to domain services."""
from django.urls import reverse

from ledgeros.models import LedgerOSConnectionSettings, LedgerOSSyncRecord, PropertyLedgerSetup
from ledgeros.permissions import BookkeepingRoleRequiredMixin, ReportingRoleRequiredMixin
from ledgeros.roles import user_has_any_role
from ledgeros.services import LedgerOSHealthCheckService
from payments.authorization import MAINTENANCE_EDITOR_ROLES, MAINTENANCE_VIEWER_ROLES, can_approve_vendor_bills, can_pay_vendor_bills
from payments.models import MaintenanceRequest, TenantPayment, VendorBill, VendorPayment


def _link(label, route, *, primary=False):
    return {"label": label, "url": reverse(route), "primary": primary}


def workflow_home_context(user):
    can_read = user_has_any_role(user, ReportingRoleRequiredMixin.allowed_roles)
    can_write = user_has_any_role(user, BookkeepingRoleRequiredMixin.allowed_roles)
    can_approve = can_approve_vendor_bills(user)
    can_pay = can_pay_vendor_bills(user)
    can_view_maintenance = user_has_any_role(user, MAINTENANCE_VIEWER_ROLES)
    can_change_maintenance = user_has_any_role(user, MAINTENANCE_EDITOR_ROLES)
    context = {"work_queues": [], "workflow_access": can_read, "workflow_cards": [], "home_setup_complete": False}
    rent_links, vendor_links, maintenance_links = [], [], []
    if can_read:
        setup = PropertyLedgerSetup.objects.prefetch_related("account_mappings").filter(pk=1).first()
        ready = bool(setup and setup.setup_status == PropertyLedgerSetup.Status.COMPLETE and not setup.setup_completion_errors())
        settings = LedgerOSConnectionSettings.objects.filter(pk=1).first() or LedgerOSConnectionSettings()
        # Pass an unsaved default when missing; never create singleton rows on GET.
        health = LedgerOSHealthCheckService.check(connection_settings=settings)
        error = health.details.get("error")
        if health.healthy:
            status, message = "available", "LedgerOS connected"
        elif error == "missing_configuration":
            status, message = "configuration", "LedgerOS configuration needed"
        elif health.details.get("http_status") in (401, 403):
            status, message = "permission", "LedgerOS access denied"
        else:
            status, message = "unavailable", "LedgerOS unavailable"
        context.update(home_setup_complete=ready, connection_status=status, connection_message=message)
        if can_write and ready:
            rent_links.extend((_link("Create charge / invoice", "charge-create", primary=True), _link("Record rent receipt", "tenant-payment-create")))
            # WP2 bill entry is local-first; explicit posting remains blocked by
            # LedgerOS validation after independent approval.
            vendor_links.append(_link("Record vendor bill", "vendor-bill-create", primary=True))
        rent_links.extend((_link("Open invoices", "invoice-list", primary=not rent_links), _link("View receipts", "tenant-payment-list"), _link("View deposits", "security-deposit-list")))
        vendor_links.extend((_link("View vendor bills", "vendor-bill-list", primary=not vendor_links), _link("View vendor payments", "vendor-payment-list")))
        if can_approve:
            vendor_links.append(_link("Review bill approvals", "vendor-bill-approval-queue"))
        if can_pay:
            vendor_links.append(_link("Pay approved bills", "vendor-bill-list"))
        if can_view_maintenance:
            maintenance_links.append(_link("Maintenance queue", "maintenance-request-list", primary=True))
            if can_change_maintenance:
                maintenance_links.insert(0, _link("New maintenance request", "maintenance-request-create", primary=True))
            active_maintenance = MaintenanceRequest.objects.exclude(
                status__in=(MaintenanceRequest.Status.CLOSED, MaintenanceRequest.Status.CANCELLED)
            ).select_related("property", "unit", "category")
            context["work_queues"].append(
                {
                    "key": "maintenance",
                    "title": "Active maintenance requests",
                    "count": active_maintenance.count(),
                    "items": [
                        {
                            "label": f"Request {row.pk} · {row.get_priority_display()}",
                            "detail": f"{row.property} · {row.category} · {row.get_status_display()}",
                            "url": reverse("maintenance-request-detail", args=[row.pk]),
                        }
                        for row in active_maintenance[:5]
                    ],
                    "url": reverse("maintenance-request-list"),
                    "can_act": can_change_maintenance,
                }
            )
        if can_read:
            maintenance_links.append(_link("View maintenance expenses", "maintenance-expense-summary-report"))

        receipts = TenantPayment.objects.exclude(status__in=(TenantPayment.Status.POSTED, TenantPayment.Status.VOIDED)).exclude(sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED)
        pending = VendorPayment.objects.filter(sync_record__attempt_count__gt=0).exclude(status__in=(VendorPayment.Status.POSTED, VendorPayment.Status.VOIDED)).exclude(sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED)
        queue_definitions = [
            ("receipts", "Receipts awaiting finalization", receipts, "tenant-payment-list", "tenant-payment-detail"),
            ("payments", "Vendor payments awaiting confirmation", pending, "vendor-payment-list", "vendor-payment-detail"),
        ]
        if can_approve:
            approvals = VendorBill.objects.filter(
                approval_status=VendorBill.ApprovalStatus.SUBMITTED
            ).exclude(submitted_by=user)
            queue_definitions.append(
                ("approvals", "Vendor bills awaiting approval", approvals, "vendor-bill-approval-queue", "vendor-bill-detail")
            )
        for key, title, records, list_route, detail_route in queue_definitions:
            count = records.count()
            if key == "receipts":
                records = records.select_related("tenant", "property")
                items = [{"label": row.reference or f"Receipt {row.pk}", "detail": f"{row.tenant} · {row.property} · {row.get_status_display()}", "url": reverse(detail_route, args=[row.pk])} for row in records.order_by("payment_date", "id")[:5]]
            elif key == "payments":
                records = records.select_related("vendor", "vendor_bill")
                items = [{"label": f"Payment {row.pk} · {row.vendor}", "detail": f"Bill {row.vendor_bill_id} · {row.get_status_display()}", "url": reverse(detail_route, args=[row.pk])} for row in records.order_by("payment_date", "id")[:5]]
            else:
                records = records.select_related("vendor", "property", "submitted_by")
                items = [{"label": f"Bill {row.pk} · {row.vendor}", "detail": f"{row.property} · {row.amount} · submitted by {row.submitted_by}", "url": reverse(detail_route, args=[row.pk])} for row in records.order_by("submitted_at", "id")[:5]]
            can_act = can_approve if key == "approvals" else (can_pay if key == "payments" else can_write)
            context["work_queues"].append({"key": key, "title": title, "count": count, "items": items, "url": reverse(list_route), "can_act": can_act})
    context["workflow_cards"] = [
        {"number": "01", "title": "Collect Rent / Deposit", "description": "Create invoices and record money received from tenants.", "links": rent_links, "gate": "Combined rent and deposit receipts are not available yet. Record them separately using the existing workflows."},
        {"number": "02", "title": "Get Billed & Pay Vendors", "description": "Submit vendor invoices for independent approval, then record authorized payments.", "links": vendor_links, "gate": "Approval, LedgerOS posting, and payable balance are shown as separate states."},
        {"number": "03", "title": "Log Maintenance Request", "description": "Track work through verified completion, independently of vendor billing.", "links": maintenance_links, "gate": "Photo uploads await private durable storage. Vendor bill handoff is delivered in WP4."},
    ]
    return context
