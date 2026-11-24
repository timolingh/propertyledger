"""Reviewed invoice → deposit → other allocation of one existing receipt."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ledgeros.models import Lease, LedgerOSSyncRecord, PropertyLedgerAccountMapping, TenantCharge
from payments.deposit_limits import require_deposit_capacity
from payments.models import SecurityDepositEvent, TenantPayment, TenantPaymentApplication, TenantPaymentOtherAllocation
from payments.services import LedgerOSSyncEventService, TenantPaymentService


ZERO = Decimal("0.00")


def validate_other_account(account_code):
    if not account_code:
        raise ValidationError("Specify an account for Other.")
    if PropertyLedgerAccountMapping.objects.filter(
        setup_id=1, is_enabled=True, ledgeros_account_id=account_code,
        mapping_key__in=("operating_bank_account", "accounts_receivable", "tenant_security_deposits_liability"),
    ).exists():
        raise ValidationError("Use the invoice or deposit allocation for its control account. Other must use a different account from Cash, AR, and tenant deposits.")


def receipt_waterfall(*, property_id, tenant_id, payment=None):
    invoices = []
    charges = TenantCharge.objects.filter(
        property_id=property_id, tenant_id=tenant_id, status=TenantCharge.Status.SYNCED,
        sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
    ).order_by("due_date", "charge_date", "id")
    for charge in charges:
        applications = charge.payment_applications.exclude(payment__status=TenantPayment.Status.VOIDED)
        if payment:
            applications = applications.exclude(payment=payment)
        due = charge.amount - (applications.aggregate(total=Sum("amount_applied"))["total"] or ZERO)
        if due > 0:
            invoices.append({"id": charge.pk, "label": str(charge), "due": str(due)})
    leases = []
    for lease in Lease.objects.filter(tenant_id=tenant_id, unit__property_id=property_id).exclude(status="cancelled").select_related("unit"):
        sources = list(lease.tenant_payment_deposit_allocations.select_related("sync_record"))
        sources += list(SecurityDepositEvent.objects.filter(lease=lease, event_type="received").select_related("sync_record"))
        received, blocked = ZERO, False
        for source in sources:
            if payment and getattr(source, "payment_id", None) == payment.pk:
                continue
            record = source.sync_record
            if record and record.status == "succeeded" and record.ledgeros_journal_entry_id:
                received += source.amount
            elif (record and (record.attempt_count or record.status == "succeeded")) or getattr(source, "status", "") == "posted":
                blocked = True
        leases.append({"id": lease.pk, "label": str(lease),
                       "due": str(max(ZERO, lease.deposit_required_amount - received)), "blocked": blocked})
    return {"invoices": invoices, "invoice_due": str(sum((Decimal(row["due"]) for row in invoices), ZERO)), "leases": leases}


@transaction.atomic
def save_receipt_allocations(*, payment, invoice_amount, deposit_amount, lease, other_amount, account_code):
    payment = TenantPayment.objects.select_for_update().get(pk=payment.pk)
    if payment.status in ("posted", "voided") or (payment.sync_record and payment.sync_record.status == "succeeded"):
        raise ValidationError("Finalized or voided receipts cannot be reallocated.")
    if payment.amount <= 0:
        raise ValidationError("Amount received must be greater than zero.")
    amounts = (invoice_amount, deposit_amount, other_amount)
    if any(not value.is_finite() or value < 0 or value != value.quantize(Decimal("0.01")) for value in amounts):
        raise ValidationError("Enter nonnegative allocations with at most two decimal places.")
    if sum(amounts, ZERO) > payment.amount:
        raise ValidationError("Allocations cannot exceed the amount received.")
    account_code = account_code.strip()
    if other_amount:
        validate_other_account(account_code)
    # Serialize allocation changes across receipts sharing this tenant's invoices.
    list(TenantCharge.objects.select_for_update().filter(property=payment.property, tenant=payment.tenant).order_by("id"))
    attempted = list(payment.applications.filter(sync_record__attempt_count__gt=0).select_related("sync_record"))
    for application in attempted:
        if not (application.sync_record.status == "succeeded" and application.sync_record.ledgeros_journal_entry_id):
            raise ValidationError("Resolve the unconfirmed invoice posting before changing the split.")
    fixed = sum((row.amount_applied for row in attempted), ZERO)
    if invoice_amount < fixed:
        raise ValidationError("Confirmed invoice payments cannot be reduced.")
    for component in (getattr(payment, "deposit_allocation", None), getattr(payment, "other_allocation", None)):
        if component and component.sync_record and component.sync_record.attempt_count:
            raise ValidationError("An attempted receipt component cannot be reallocated. Retry the existing receipt.")
    payment.applications.exclude(pk__in=[row.pk for row in attempted]).delete()
    plan = receipt_waterfall(property_id=payment.property_id, tenant_id=payment.tenant_id, payment=payment)
    capacity = {row["id"]: Decimal(row["due"]) for row in plan["invoices"]}
    for application in attempted:
        capacity[application.charge_id] = capacity.get(application.charge_id, ZERO) - application.amount_applied
    remaining = invoice_amount - fixed
    for row in plan["invoices"]:
        if row["id"] in {application.charge_id for application in attempted}:
            continue
        applied = min(remaining, max(ZERO, capacity[row["id"]]))
        if applied > 0:
            TenantPaymentApplication.objects.create(payment=payment, charge_id=row["id"], amount_applied=applied)
            remaining -= applied
    if remaining:
        raise ValidationError("Invoice allocation exceeds eligible open invoices; review the current balances.")
    if deposit_amount:
        if lease is None or lease.tenant_id != payment.tenant_id or lease.unit.property_id != payment.property_id or lease.status == "cancelled":
            raise ValidationError("Choose a matching lease for the deposit.")
        require_deposit_capacity(lease_id=lease.pk, amount=deposit_amount, allocation=getattr(payment, "deposit_allocation", None))
    if attempted:
        if deposit_amount:
            TenantPaymentService.assign_unapplied_deposit(payment=payment, lease=lease, amount=deposit_amount)
        elif getattr(payment, "deposit_allocation", None):
            raise ValidationError("Review the existing deposit allocation before changing this split.")
    else:
        TenantPaymentService.set_deposit_allocation(payment=payment, lease=lease, amount=deposit_amount)
    if other_amount:
        TenantPaymentOtherAllocation.objects.update_or_create(payment=payment, defaults={"amount": other_amount, "account_code": account_code})
    else:
        TenantPaymentOtherAllocation.objects.filter(payment=payment).delete()
    payment.allocation_reviewed = True
    payment.status = TenantPayment.Status.ALLOCATED
    payment.save(update_fields=["allocation_reviewed", "status", "updated_at"])
    payment.refresh_from_db()
    return payment


@transaction.atomic
def save_receipt(form):
    payment = form.save(commit=False)
    if payment.pk:
        saved = TenantPayment.objects.select_for_update().get(pk=payment.pk)
        if not form.can_allocate or saved.status in ("posted", "voided") or (saved.sync_record and saved.sync_record.status == "succeeded"):
            saved.notes = payment.notes
            saved.save(update_fields=["notes", "updated_at"])
            return saved
        if not saved.is_editable_after_sync:
            # Recheck after acquiring the lock: another request may have posted
            # while this form was being validated. Never overwrite frozen data.
            saved.notes = payment.notes
            saved.save(update_fields=["notes", "updated_at"])
            payment = saved
        else:
            payment.save()
    else:
        payment.save()
    invoice_amount = form.cleaned_data.get("invoice_amount")
    if invoice_amount is None:
        # Old draft submissions retain their existing local-only behavior.
        TenantPaymentService.set_deposit_allocation(payment=payment, lease=form.cleaned_data.get("deposit_lease"),
                                                  amount=form.cleaned_data.get("deposit_amount") or ZERO)
        return payment
    return save_receipt_allocations(payment=payment, invoice_amount=invoice_amount,
        deposit_amount=form.cleaned_data.get("deposit_amount") or ZERO, lease=form.cleaned_data.get("deposit_lease"),
        other_amount=form.cleaned_data.get("other_amount") or ZERO, account_code=form.cleaned_data.get("other_account_code") or "")


def other_payload(allocation):
    payment = allocation.payment
    amount = str(allocation.amount.quantize(Decimal("0.01")))
    cash = TenantPaymentService._account_code(mapping_key="operating_bank_account", field_name="other_account_code", expected_type="asset")
    validate_other_account(allocation.account_code)
    return TenantPaymentService._build_sync_event_payload(
        source_system="propertyledger", domain_event_type="tenant_payment.other_received",
        external_id=f"tenant-payment:{payment.pk}:other", source_object_type="tenant_payment_other_allocation",
        source_object_id=str(allocation.pk), occurred_at=f"{payment.payment_date.isoformat()}T00:00:00Z",
        payload={"receipt_id": payment.pk, "property_id": payment.property_id, "tenant_id": payment.tenant_id,
                 "amount": amount, "account_code": allocation.account_code,
                 "accounting_entries": [{"account_code": cash, "direction": "debit", "amount": amount},
                                        {"account_code": allocation.account_code, "direction": "credit", "amount": amount}]})


@transaction.atomic
def sync_other_allocation(allocation):
    allocation = TenantPaymentOtherAllocation.objects.select_for_update(of=("self",)).select_related("payment", "sync_record").get(pk=allocation.pk)
    if allocation.payment.status == "voided":
        raise ValidationError("Voided receipts cannot be posted.")
    payload = other_payload(allocation)
    if allocation.frozen_request_payload is not None and allocation.frozen_request_payload != payload:
        raise ValidationError("An attempted Other allocation cannot be changed. Retry its original payload.")
    if allocation.frozen_request_payload is None:
        allocation.frozen_request_payload = payload
        allocation.save(update_fields=["frozen_request_payload", "updated_at"])
    record = allocation.sync_record
    if record:
        if record.request_hash != TenantPaymentService._sync_record_payload(payload):
            raise ValidationError("An attempted Other allocation cannot be changed.")
        if record.status == "succeeded" and TenantPaymentService._posted_sync_event_result(record.response_payload):
            return allocation
    else:
        record = TenantPaymentService._build_sync_record(local_object_type="tenant_payment_other_allocation",
            local_object_id=str(allocation.pk), source_event_type="tenant_payment.other_received",
            external_id=f"tenant-payment:{allocation.payment_id}:other", request_payload=payload)
        allocation.sync_record = record
        allocation.save(update_fields=["sync_record", "updated_at"])
    record.status, record.last_error = "in_progress", None
    record.attempt_count += 1
    record.save()
    try:
        result = LedgerOSSyncEventService._submit(method="POST", path=LedgerOSSyncEventService.SYNC_EVENT_PATH,
                                                payload=payload, idempotency_key=record.idempotency_key)
        if not TenantPaymentService._posted_sync_event_result(result.payload):
            raise RuntimeError("Other allocation did not return a posted journal. Retry the same receipt.")
    except Exception as exc:
        record.status, record.last_error = "failed", str(exc)
        record.response_payload = {"status": "failed", "error": str(exc)}
    else:
        record.status = "succeeded"
        record.ledgeros_resource_id = str(result.payload["sync_event"]["id"])
        record.ledgeros_journal_entry_id = str(result.payload["journal_entry"]["id"])
        record.response_payload, record.last_synced_at = result.payload, timezone.now()
    record.save()
    return allocation
