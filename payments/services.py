from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from ledgeros.idempotency import build_idempotency_key
from ledgeros.models import (
    LedgerOSConnectionSettings,
    LedgerOSSyncRecord,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    TenantCharge,
    Lease,
)
from ledgeros.signing import sign_api_request
from payments.models import (
    DebtServicePayment,
    PaymentWorkflowSettings,
    SecurityDepositEvent,
    TenantPayment,
    TenantPaymentApplication,
    Vendor,
    VendorBill,
    VendorPayment,
    _operating_bank_account_name,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    status_code: int
    payload: dict[str, Any]


def _response_journal_entry_id(payload: dict[str, Any]) -> str | None:
    journal_entry_payload = payload.get("journal_entry")
    if isinstance(journal_entry_payload, dict):
        journal_entry_id = str(journal_entry_payload.get("id") or "").strip()
        if journal_entry_id:
            return journal_entry_id
    journal_entry_id = str(payload.get("journal_entry_id") or "").strip()
    return journal_entry_id or None


class LedgerOSSyncEventService:
    SYNC_EVENT_PATH = "/api/v1/sync-events/"

    @staticmethod
    def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")

    @staticmethod
    def _format_http_error(exc: HTTPError, *, path: str) -> str:
        try:
            raw_body = exc.read()
        except Exception:
            raw_body = b""
        parsed_body: dict[str, Any] | None = None
        if raw_body:
            try:
                body = raw_body.decode("utf-8").strip()
            except Exception:
                body = raw_body.decode("utf-8", errors="replace").strip()
            if body:
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    parsed_body = parsed
                    detail = parsed.get("detail") or parsed.get("error") or parsed.get("message")
                    if detail:
                        message = f"LedgerOS returned HTTP {exc.code}: {detail}"
                    else:
                        message = f"LedgerOS returned HTTP {exc.code}: {body}"
                else:
                    message = f"LedgerOS returned HTTP {exc.code}: {body}"

                if exc.code == 403:
                    if path == LedgerOSSyncEventService.SYNC_EVENT_PATH:
                        permission_hint = (
                            f"LedgerOS denied POST {path} for this client. "
                            "Check the LedgerOS API client permissions for sync-event writes."
                        )
                    else:
                        permission_hint = (
                            f"LedgerOS denied POST {path} for this client. "
                            "Check the LedgerOS API client permissions for this request."
                        )
                    if parsed_body and parsed_body.get("detail") and parsed_body["detail"] != body:
                        return f"{message} {permission_hint}"
                    return f"{message} {permission_hint}"
                return message
        return f"LedgerOS returned HTTP {exc.code}: {exc.reason}"

    @staticmethod
    def _connection_values() -> tuple[str, str, str, str, int, str]:
        connection_settings = LedgerOSConnectionSettings.load()
        base_url = connection_settings.base_url
        host_header = connection_settings.host_header.strip()
        client_id = connection_settings.client_id
        secret_env_var = connection_settings.hmac_secret_env_var or "LEDGEROS_HMAC_SECRET"
        secret = os.environ.get(secret_env_var, "")
        api_key = os.environ.get(connection_settings.api_key_env_var or "LEDGEROS_API_KEY", "")
        timeout = connection_settings.timeout_seconds
        missing = []
        if not base_url:
            missing.append("base_url")
        if not client_id:
            missing.append("client_id")
        if not secret:
            missing.append(secret_env_var)
        if missing:
            raise ValidationError({"ledgeros": f"Missing LedgerOS configuration: {', '.join(missing)}"})
        return base_url, host_header, client_id, secret, timeout, api_key

    @staticmethod
    def _submit(*, method: str, path: str, payload: dict[str, Any], idempotency_key: str) -> SyncResult:
        base_url, host_header, client_id, secret, timeout, api_key = LedgerOSSyncEventService._connection_values()
        body = LedgerOSSyncEventService._canonical_json_bytes(payload)
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        signed = sign_api_request(
            method=method,
            path=path,
            body=body,
            timestamp=timestamp,
            nonce=nonce,
            client_id=client_id,
            secret=secret,
        )
        headers = {
            "Content-Type": "application/json",
            "X-LedgerOS-Client-Id": client_id,
            "X-LedgerOS-Timestamp": timestamp,
            "X-LedgerOS-Nonce": nonce,
            "X-LedgerOS-Signature": signed.signature,
            "Idempotency-Key": idempotency_key,
        }
        if host_header:
            headers["Host"] = host_header
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request = Request(f"{base_url.rstrip('/')}{path}", data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                response_raw = response.read().decode("utf-8").strip()
                if response.status not in {200, 201}:
                    raise RuntimeError(f"LedgerOS returned HTTP {response.status}: {response_raw}")
                try:
                    response_payload = json.loads(response_raw) if response_raw else {}
                except json.JSONDecodeError as exc:
                    raise RuntimeError("LedgerOS response was not valid JSON.") from exc
                if not isinstance(response_payload, dict):
                    raise RuntimeError("LedgerOS response must be a JSON object.")
                return SyncResult(status_code=response.status, payload=response_payload)
        except HTTPError as exc:
            raise RuntimeError(LedgerOSSyncEventService._format_http_error(exc, path=path)) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc


class LedgerOSPaymentService:
    PAYMENT_PATH = "/api/v1/payments/"

    @staticmethod
    def _build_payment_payload(application: TenantPaymentApplication) -> dict[str, Any]:
        charge_sync_record = application.charge.sync_record
        if charge_sync_record is None or not charge_sync_record.external_id:
            raise ValidationError(
                {"charge": "The invoice must be synced to LedgerOS before the payment can be posted."}
            )

        return {
            "source_type": "invoice",
            "source_reference": charge_sync_record.external_id,
            "payment_date": application.payment.payment_date.isoformat(),
            "amount": str(application.amount_applied.quantize(Decimal("0.01"))),
        }

    @staticmethod
    def submit_payment_application(*, application: TenantPaymentApplication, idempotency_key: str) -> SyncResult:
        payload = LedgerOSPaymentService._build_payment_payload(application)
        return LedgerOSSyncEventService._submit(
            method="POST",
            path=LedgerOSPaymentService.PAYMENT_PATH,
            payload=payload,
            idempotency_key=idempotency_key,
        )


class LedgerOSVendorBillService:
    BILL_PATH = "/api/v1/bills/"

    @staticmethod
    def _vendor_code(vendor: Vendor) -> str:
        return f"vendor-{vendor.pk}"

    @staticmethod
    def _external_bill_number(bill: VendorBill) -> str:
        return f"vendor-bill:{bill.pk}"

    @staticmethod
    def _build_bill_payload(bill: VendorBill) -> dict[str, Any]:
        expense_account_code = Epic5AccountingService._account_code(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.REPAIRS_AND_MAINTENANCE_EXPENSE,
            field_name="expense_category",
        )
        description_parts = [bill.get_expense_category_display()]
        if bill.maintenance_category_id and bill.maintenance_category:
            description_parts.append(bill.maintenance_category.name)
        note = bill.repair_notes.strip() or bill.notes.strip()
        if note:
            description_parts.append(note)
        elif bill.tenant_chargeable:
            description_parts.append("tenant chargeable")

        return {
            "vendor_code": LedgerOSVendorBillService._vendor_code(bill.vendor),
            "external_bill_number": LedgerOSVendorBillService._external_bill_number(bill),
            "bill_date": bill.bill_date.isoformat(),
            "due_date": (bill.due_date or bill.bill_date).isoformat(),
            "total_amount": str(bill.amount.quantize(Decimal("0.01"))),
            "lines": [
                {
                    "account_code": expense_account_code,
                    "line_description": " - ".join(description_parts),
                    "amount": str(bill.amount.quantize(Decimal("0.01"))),
                }
            ],
        }

    @staticmethod
    def submit_bill(*, bill: VendorBill, idempotency_key: str) -> SyncResult:
        payload = LedgerOSVendorBillService._build_bill_payload(bill)
        return LedgerOSSyncEventService._submit(
            method="POST",
            path=LedgerOSVendorBillService.BILL_PATH,
            payload=payload,
            idempotency_key=idempotency_key,
        )


class LedgerOSVendorPaymentService:
    PAYMENT_PATH = "/api/v1/payments/"

    @staticmethod
    def _build_payment_payload(payment: VendorPayment) -> dict[str, Any]:
        bill_sync_record = payment.vendor_bill.sync_record
        if bill_sync_record is None or not bill_sync_record.external_id:
            raise ValidationError(
                {"vendor_bill": "The vendor bill must be synced before the payment can be posted."}
            )

        return {
            "source_type": "bill",
            "source_reference": bill_sync_record.external_id,
            "payment_date": payment.payment_date.isoformat(),
            "amount": str(payment.amount.quantize(Decimal("0.01"))),
        }

    @staticmethod
    def submit_payment(*, payment: VendorPayment, idempotency_key: str) -> SyncResult:
        payload = LedgerOSVendorPaymentService._build_payment_payload(payment)
        return LedgerOSSyncEventService._submit(
            method="POST",
            path=LedgerOSVendorPaymentService.PAYMENT_PATH,
            payload=payload,
            idempotency_key=idempotency_key,
        )


class LedgerOSVendorSyncService:
    VENDOR_PATH = "/api/v1/vendors/"

    @staticmethod
    def _vendor_code(vendor: Vendor) -> str:
        return f"vendor-{vendor.pk}"

    @staticmethod
    def _default_ap_account_code() -> str:
        setup = PropertyLedgerSetup.load()
        mapping = setup.account_mappings.filter(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_PAYABLE
        ).first()
        if mapping is None or not mapping.is_valid_for_completion:
            raise ValidationError(
                {
                    "accounts_payable": (
                        "The accounts payable mapping is required and must be valid before this record can sync."
                    )
                }
            )
        return mapping.ledgeros_account_id.strip()

    @staticmethod
    def _build_vendor_payload(vendor: Vendor) -> dict[str, Any]:
        return {
            "vendor_code": LedgerOSVendorSyncService._vendor_code(vendor),
            "name": vendor.name,
            "status": "active" if vendor.is_active else "inactive",
            "default_ap_account_code": LedgerOSVendorSyncService._default_ap_account_code(),
        }

    @staticmethod
    def create_vendor(*, vendor: Vendor) -> SyncResult:
        payload = LedgerOSVendorSyncService._build_vendor_payload(vendor)
        return LedgerOSSyncEventService._submit(
            method="POST",
            path=LedgerOSVendorSyncService.VENDOR_PATH,
            payload=payload,
            idempotency_key=build_idempotency_key(
                local_object_type="vendor",
                local_object_id=str(vendor.pk),
                source_event_type="vendor.upsert_requested",
                external_id=LedgerOSVendorSyncService._vendor_code(vendor),
                request_body=payload,
            ),
        )


class VendorService:
    @staticmethod
    def _sync_blockers() -> list[str]:
        blockers: list[str] = []
        try:
            LedgerOSVendorSyncService._default_ap_account_code()
        except ValidationError as exc:
            blockers.extend(exc.messages)
        return blockers

    @staticmethod
    def _vendor_request_hash(vendor: Vendor) -> str:
        return TenantPaymentService._sync_record_payload(LedgerOSVendorSyncService._build_vendor_payload(vendor))

    @staticmethod
    @transaction.atomic
    def save_and_sync_vendor(vendor: Vendor) -> Vendor:
        vendor.full_clean()
        vendor.save()
        try:
            request_hash = VendorService._vendor_request_hash(vendor)
        except ValidationError:
            request_hash = None
        if (
            request_hash is not None
            and vendor.sync_record
            and vendor.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
            and vendor.sync_record.request_hash == request_hash
        ):
            return vendor
        if VendorService._sync_blockers():
            return vendor
        return VendorService.sync_vendor(vendor)

    @staticmethod
    @transaction.atomic
    def sync_vendor(vendor: Vendor) -> Vendor:
        request_payload = LedgerOSVendorSyncService._build_vendor_payload(vendor)
        sync_record = Epic5AccountingService._build_sync_record(
            local_object_type="vendor",
            local_object_id=str(vendor.pk),
            source_event_type="vendor.upsert_requested",
            external_id=LedgerOSVendorSyncService._vendor_code(vendor),
            request_payload=request_payload,
            ledgeros_resource_type="vendor",
        )
        vendor.sync_record = sync_record
        vendor.save(update_fields=["sync_record", "updated_at"])

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])

        try:
            result = LedgerOSVendorSyncService.create_vendor(vendor=vendor)
        except Exception as exc:
            logger.warning("Vendor sync failed", extra={"vendor_id": vendor.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return vendor

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("vendor", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "response_payload", "last_synced_at", "updated_at"])
        return vendor


class TenantPaymentService:
    @staticmethod
    def _payment_event_details(payment: TenantPayment) -> dict[str, Any]:
        return {
            "property_id": payment.property_id,
            "tenant_id": payment.tenant_id,
            "payment_date": payment.payment_date.isoformat(),
            "total_amount": str(payment.amount.quantize(Decimal("0.01"))),
            "applied_amount": str(payment.allocated_amount.quantize(Decimal("0.01"))),
            "unapplied_amount": str(payment.unapplied_amount.quantize(Decimal("0.01"))),
            "payment_method": payment.payment_method,
            "reference": payment.reference,
            "notes": payment.notes,
            "applications": [
                {
                    "payment_application_id": application.pk,
                    "charge_id": application.charge_id,
                    "amount": str(application.amount_applied.quantize(Decimal("0.01"))),
                }
                for application in payment.applications.select_related("charge").order_by("charge__due_date", "charge__charge_date", "id")
            ],
        }

    @staticmethod
    def _payment_application_event_details(application: TenantPaymentApplication) -> dict[str, Any]:
        return {
            "payment_id": application.payment_id,
            "charge_id": application.charge_id,
            "applied_amount": str(application.amount_applied.quantize(Decimal("0.01"))),
            "payment": {
                "payment_date": application.payment.payment_date.isoformat(),
                "payment_method": application.payment.payment_method,
                "reference": application.payment.reference,
                "amount": str(application.payment.amount.quantize(Decimal("0.01"))),
            },
            "charge": {
                "charge_type": application.charge.charge_type,
                "charge_date": application.charge.charge_date.isoformat(),
                "due_date": application.charge.due_date.isoformat(),
                "amount": str(application.charge.amount.quantize(Decimal("0.01"))),
                "description": application.charge.description,
            },
        }

    @staticmethod
    def _security_deposit_event_details(event: SecurityDepositEvent) -> dict[str, Any]:
        return {
            "property_id": event.property_id,
            "unit_id": event.unit_id,
            "tenant_id": event.tenant_id,
            "lease_id": event.lease_id,
            "event_type": event.event_type,
            "event_date": event.event_date.isoformat(),
            "total_amount": str(event.amount.quantize(Decimal("0.01"))),
            "description": event.description,
            "notes": event.notes,
        }

    @staticmethod
    def _build_sync_event_payload(
        *,
        source_system: str,
        domain_event_type: str,
        external_id: str,
        source_object_type: str,
        source_object_id: str,
        occurred_at: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "source_system": source_system,
            "domain_event_type": domain_event_type,
            "external_id": external_id,
            "source_object_type": source_object_type,
            "source_object_id": source_object_id,
            "occurred_at": occurred_at,
            "payload": payload,
        }

    @staticmethod
    def _sync_record_payload(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _build_sync_record(
        *,
        local_object_type: str,
        local_object_id: str,
        source_event_type: str,
        external_id: str,
        request_payload: dict[str, Any],
        ledgeros_resource_type: str = "sync_event",
    ) -> LedgerOSSyncRecord:
        sync_record, _ = LedgerOSSyncRecord.objects.get_or_create(
            local_object_type=local_object_type,
            local_object_id=local_object_id,
            source_event_type=source_event_type,
            defaults={
                "ledgeros_resource_type": ledgeros_resource_type,
                "external_id": external_id,
                "idempotency_key": build_idempotency_key(
                    local_object_type=local_object_type,
                    local_object_id=local_object_id,
                    source_event_type=source_event_type,
                    external_id=external_id,
                    request_body=request_payload,
                ),
                "request_hash": TenantPaymentService._sync_record_payload(request_payload),
                "status": LedgerOSSyncRecord.Status.PENDING,
            },
        )
        sync_record.ledgeros_resource_type = ledgeros_resource_type
        sync_record.external_id = external_id
        sync_record.idempotency_key = build_idempotency_key(
            local_object_type=local_object_type,
            local_object_id=local_object_id,
            source_event_type=source_event_type,
            external_id=external_id,
            request_body=request_payload,
        )
        sync_record.request_hash = TenantPaymentService._sync_record_payload(request_payload)
        sync_record.save()
        return sync_record

    @staticmethod
    def _charge_sort_key(charge: TenantCharge, priority_index: dict[str, int]) -> tuple[int, date, date, int]:
        return (
            priority_index.get(charge.charge_type, len(priority_index)),
            charge.due_date or charge.charge_date,
            charge.charge_date,
            charge.pk or 0,
        )

    @staticmethod
    def _preferred_charge_sort_key(
        charge: TenantCharge,
        priority_index: dict[str, int],
        preferred_charge_index: dict[int, int],
    ) -> tuple[int, int, date, date, int]:
        preferred_rank = preferred_charge_index.get(charge.pk or 0, len(preferred_charge_index))
        return (
            preferred_rank,
            priority_index.get(charge.charge_type, len(priority_index)),
            charge.due_date or charge.charge_date,
            charge.charge_date,
            charge.pk or 0,
        )

    @staticmethod
    def allocate_payment(payment: TenantPayment, preferred_charge_ids: list[int] | None = None) -> TenantPayment:
        if payment.sync_record and payment.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
            raise ValidationError({"payment": "Posted payments cannot be reallocated."})
        if payment.status == TenantPayment.Status.VOIDED:
            raise ValidationError({"payment": "Voided payments cannot be reallocated."})

        settings = PaymentWorkflowSettings.load()
        priority = list(settings.charge_type_priority or [
            TenantCharge.ChargeType.BASE_RENT,
            TenantCharge.ChargeType.UTILITY_REIMBURSEMENT,
            TenantCharge.ChargeType.LATE_FEE_MANUAL,
            TenantCharge.ChargeType.OTHER_MANUAL,
        ])
        priority_index = {charge_type: index for index, charge_type in enumerate(priority)}

        open_charges = list(
            TenantCharge.objects.filter(
                property=payment.property,
                tenant=payment.tenant,
            ).exclude(status=TenantCharge.Status.VOIDED)
        )
        preferred_charge_index = {
            charge_id: index for index, charge_id in enumerate(preferred_charge_ids or [])
        }
        open_charges.sort(
            key=lambda charge: TenantPaymentService._preferred_charge_sort_key(
                charge,
                priority_index,
                preferred_charge_index,
            )
        )

        existing_allocations = list(payment.applications.select_related("sync_record", "charge"))
        if any(
            allocation.sync_record
            and allocation.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
            for allocation in existing_allocations
        ):
            raise ValidationError({"payment": "Synced allocations cannot be reallocated."})
        for allocation in existing_allocations:
            allocation.delete()

        remaining = payment.amount.quantize(Decimal("0.01"))
        new_allocations: list[TenantPaymentApplication] = []
        any_failed = False
        for charge in open_charges:
            if remaining <= Decimal("0.00"):
                break
            already_applied = (
                charge.payment_applications.aggregate(total=models.Sum("amount_applied"))["total"]
                or Decimal("0.00")
            )
            charge_remaining = (charge.amount - already_applied).quantize(Decimal("0.01"))
            if charge_remaining <= Decimal("0.00"):
                continue
            amount_applied = min(remaining, charge_remaining)
            allocation = TenantPaymentApplication.objects.create(
                payment=payment,
                charge=charge,
                amount_applied=amount_applied,
            )
            new_allocations.append(allocation)
            TenantPaymentService.sync_payment_application(allocation)
            allocation.refresh_from_db()
            if not allocation.sync_record or allocation.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED:
                any_failed = True
            remaining = (remaining - amount_applied).quantize(Decimal("0.01"))

        payment.refresh_from_db()
        all_allocations_synced = all(
            allocation.sync_record
            and allocation.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
            for allocation in payment.applications.all()
        )
        if not new_allocations:
            payment.status = TenantPayment.Status.DRAFT
        elif any_failed:
            payment.status = TenantPayment.Status.ALLOCATED
        elif all_allocations_synced:
            payment.status = TenantPayment.Status.READY_TO_SYNC
        else:
            payment.status = TenantPayment.Status.ALLOCATED
        payment.save(update_fields=["status", "updated_at"])
        return payment

    @staticmethod
    @transaction.atomic
    def sync_payment_application(application: TenantPaymentApplication) -> TenantPaymentApplication:
        request_payload = LedgerOSPaymentService._build_payment_payload(application)
        sync_record = TenantPaymentService._build_sync_record(
            local_object_type="tenant_payment_application",
            local_object_id=str(application.pk),
            source_event_type="tenant_payment.application_applied",
            external_id=f"tenant-payment-application:{application.pk}",
            request_payload=request_payload,
            ledgeros_resource_type="payment",
        )
        application.sync_record = sync_record
        application.save(update_fields=["sync_record", "updated_at"])

        if (
            sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
            and sync_record.ledgeros_resource_type == "payment"
            and isinstance(sync_record.response_payload, dict)
            and isinstance(sync_record.response_payload.get("journal_entry"), dict)
        ):
            return application

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])

        try:
            result = LedgerOSPaymentService.submit_payment_application(application=application, idempotency_key=sync_record.idempotency_key)
        except Exception as exc:
            logger.warning("Tenant payment application sync failed", extra={"payment_application_id": application.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return application

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("payment", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.ledgeros_journal_entry_id = str(
            result.payload.get("journal_entry", {}).get("id")
            or result.payload.get("journal_entry_id")
            or ""
        ) or None
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "ledgeros_journal_entry_id", "response_payload", "last_synced_at", "updated_at"])
        return application

    @staticmethod
    @transaction.atomic
    def sync_payment(payment: TenantPayment) -> TenantPayment:
        if not payment.applications.exists():
            raise ValidationError({"payment": "Payment must be applied to at least one invoice before sync."})
        pending_applications = payment.applications.filter(
            models.Q(sync_record__isnull=True) | ~models.Q(sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED)
        )
        if pending_applications.exists():
            raise ValidationError({"payment": "All payment allocations must sync successfully before the payment can sync."})

        request_payload = TenantPaymentService._build_sync_event_payload(
            source_system="propertyledger",
            domain_event_type="tenant_payment.received",
            external_id=f"tenant-payment:{payment.pk}",
            source_object_type="tenant_payment",
            source_object_id=str(payment.pk),
            occurred_at=payment.created_at.isoformat(),
            payload=TenantPaymentService._payment_event_details(payment),
        )
        sync_record = TenantPaymentService._build_sync_record(
            local_object_type="tenant_payment",
            local_object_id=str(payment.pk),
            source_event_type="tenant_payment.received",
            external_id=f"tenant-payment:{payment.pk}",
            request_payload=request_payload,
        )
        payment.sync_record = sync_record
        payment.save(update_fields=["sync_record", "updated_at"])

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])
        payment.status = TenantPayment.Status.READY_TO_SYNC
        payment.save(update_fields=["status", "updated_at"])

        try:
            result = LedgerOSSyncEventService._submit(
                method="POST",
                path=LedgerOSSyncEventService.SYNC_EVENT_PATH,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Tenant payment sync failed", extra={"payment_id": payment.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return payment

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("sync_event", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.ledgeros_journal_entry_id = _response_journal_entry_id(result.payload)
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "ledgeros_journal_entry_id", "response_payload", "last_synced_at", "updated_at"])
        payment.status = TenantPayment.Status.POSTED
        payment.save(update_fields=["status", "updated_at"])
        return payment

    @staticmethod
    @transaction.atomic
    def sync_security_deposit_event(event: SecurityDepositEvent) -> SecurityDepositEvent:
        request_payload = TenantPaymentService._build_sync_event_payload(
            source_system="propertyledger",
            domain_event_type=f"security_deposit.{event.event_type}",
            external_id=f"security-deposit:{event.pk}",
            source_object_type="security_deposit_event",
            source_object_id=str(event.pk),
            occurred_at=event.created_at.isoformat(),
            payload=TenantPaymentService._security_deposit_event_details(event),
        )
        sync_record = TenantPaymentService._build_sync_record(
            local_object_type="security_deposit_event",
            local_object_id=str(event.pk),
            source_event_type=f"security_deposit.{event.event_type}",
            external_id=f"security-deposit:{event.pk}",
            request_payload=request_payload,
        )
        event.sync_record = sync_record
        event.save(update_fields=["sync_record", "updated_at"])

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])
        event.status = SecurityDepositEvent.Status.READY_TO_SYNC
        event.save(update_fields=["status", "updated_at"])

        try:
            result = LedgerOSSyncEventService._submit(
                method="POST",
                path=LedgerOSSyncEventService.SYNC_EVENT_PATH,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Security deposit event sync failed", extra={"security_deposit_event_id": event.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return event

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("sync_event", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.ledgeros_journal_entry_id = _response_journal_entry_id(result.payload)
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "ledgeros_journal_entry_id", "response_payload", "last_synced_at", "updated_at"])
        event.status = SecurityDepositEvent.Status.POSTED
        event.save(update_fields=["status", "updated_at"])
        return event

    @staticmethod
    def allocate_payment_and_sync_applications(payment: TenantPayment) -> TenantPayment:
        payment = TenantPaymentService.allocate_payment(payment)
        return payment

    @staticmethod
    @transaction.atomic
    def record_payment_for_charge(
        *,
        charge: TenantCharge,
        payment_date: date,
        amount: Decimal,
        payment_method: str,
        reference: str = "",
        notes: str = "",
    ) -> TenantPayment:
        payment = TenantPayment.objects.create(
            property=charge.property,
            tenant=charge.tenant,
            payment_date=payment_date,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            notes=notes,
            status=TenantPayment.Status.DRAFT,
        )
        TenantPaymentService.allocate_payment(payment, preferred_charge_ids=[charge.pk])
        return payment


class SecurityDepositLedgerService:
    @staticmethod
    def balance_for_lease(lease: Lease) -> Decimal:
        events = SecurityDepositEvent.objects.filter(lease=lease)
        total = Decimal("0.00")
        for event in events:
            if event.event_type == SecurityDepositEvent.EventType.RECEIVED:
                total += event.amount
            elif event.event_type in {
                SecurityDepositEvent.EventType.DEDUCTED,
                SecurityDepositEvent.EventType.REFUNDED,
            }:
                total -= event.amount
        return total.quantize(Decimal("0.01"))

    @staticmethod
    def required_amount_for_lease(lease: Lease) -> Decimal:
        events = SecurityDepositEvent.objects.filter(
            lease=lease,
            event_type=SecurityDepositEvent.EventType.REQUIRED,
        )
        total = sum((event.amount for event in events), Decimal("0.00"))
        return total.quantize(Decimal("0.01"))


class Epic5AccountingService:
    @staticmethod
    def _account_code(*, mapping_key: str, field_name: str) -> str:
        setup = PropertyLedgerSetup.load()
        mapping = setup.account_mappings.filter(mapping_key=mapping_key).first()
        if mapping is None or not mapping.is_valid_for_completion:
            raise ValidationError(
                {
                    field_name: (
                        f"The {mapping_key.replace('_', ' ')} mapping is required and must be valid before this record can sync."
                    )
                }
            )
        return mapping.ledgeros_account_id.strip()

    @staticmethod
    def _build_event_payload(
        *,
        source_system: str,
        domain_event_type: str,
        external_id: str,
        source_object_type: str,
        source_object_id: str,
        occurred_at: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return TenantPaymentService._build_sync_event_payload(
            source_system=source_system,
            domain_event_type=domain_event_type,
            external_id=external_id,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            occurred_at=occurred_at,
            payload=payload,
        )

    @staticmethod
    def _build_sync_record(
        *,
        local_object_type: str,
        local_object_id: str,
        source_event_type: str,
        external_id: str,
        request_payload: dict[str, Any],
        ledgeros_resource_type: str = "sync_event",
    ) -> LedgerOSSyncRecord:
        return TenantPaymentService._build_sync_record(
            local_object_type=local_object_type,
            local_object_id=local_object_id,
            source_event_type=source_event_type,
            external_id=external_id,
            request_payload=request_payload,
            ledgeros_resource_type=ledgeros_resource_type,
        )

    @staticmethod
    def _sync_record_payload(payload: dict[str, Any]) -> str:
        return TenantPaymentService._sync_record_payload(payload)


class VendorBillService(Epic5AccountingService):
    @staticmethod
    def _sync_blockers(bill: VendorBill) -> list[str]:
        blockers: list[str] = []
        if bill.vendor.sync_record is None or bill.vendor.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED:
            blockers.append("The vendor must be synced to LedgerOS before this bill can post.")
        try:
            Epic5AccountingService._account_code(
                mapping_key=PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_PAYABLE,
                field_name="vendor",
            )
            Epic5AccountingService._account_code(
                mapping_key=PropertyLedgerAccountMapping.MappingKey.REPAIRS_AND_MAINTENANCE_EXPENSE,
                field_name="expense_category",
            )
        except ValidationError as exc:
            blockers.extend(exc.messages)
        return blockers

    @staticmethod
    @transaction.atomic
    def save_and_sync_bill(bill: VendorBill) -> VendorBill:
        bill.full_clean()
        bill.save()
        if bill.status == VendorBill.Status.VOIDED:
            return bill
        if bill.sync_record and bill.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
            return bill
        if VendorBillService._sync_blockers(bill):
            if bill.status != VendorBill.Status.POSTED:
                bill.status = VendorBill.Status.DRAFT
                bill.save(update_fields=["status", "updated_at"])
            return bill
        return VendorBillService.sync_bill(bill)

    @staticmethod
    @transaction.atomic
    def sync_bill(bill: VendorBill) -> VendorBill:
        blockers = VendorBillService._sync_blockers(bill)
        if blockers:
            raise ValidationError(blockers)
        request_payload = LedgerOSVendorBillService._build_bill_payload(bill)
        sync_record = VendorBillService._build_sync_record(
            local_object_type="vendor_bill",
            local_object_id=str(bill.pk),
            source_event_type="vendor_bill.created",
            external_id=LedgerOSVendorBillService._external_bill_number(bill),
            request_payload=request_payload,
            ledgeros_resource_type="bill",
        )
        bill.sync_record = sync_record
        bill.save(update_fields=["sync_record", "updated_at"])

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])
        bill.status = VendorBill.Status.READY_TO_SYNC
        bill.save(update_fields=["status", "updated_at"])

        try:
            result = LedgerOSSyncEventService._submit(
                method="POST",
                path=LedgerOSVendorBillService.BILL_PATH,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Vendor bill sync failed", extra={"vendor_bill_id": bill.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return bill

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("bill", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.ledgeros_journal_entry_id = str(
            result.payload.get("journal_entry", {}).get("id")
            or result.payload.get("journal_entry_id")
            or ""
        ) or None
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "ledgeros_journal_entry_id", "response_payload", "last_synced_at", "updated_at"])
        bill.status = VendorBill.Status.POSTED
        bill.save(update_fields=["status", "updated_at"])
        return bill


class VendorPaymentService(Epic5AccountingService):
    @staticmethod
    def _normalize_payment_account(payment: VendorPayment) -> None:
        if payment.is_credit_card_payoff or payment.payment_method != VendorPayment.PaymentMethod.CREDIT_CARD:
            if not payment.bank_account_name.strip():
                payment.bank_account_name = _operating_bank_account_name()

    @staticmethod
    def _sync_blockers(payment: VendorPayment) -> list[str]:
        blockers: list[str] = []
        if payment.vendor_bill_id is None:
            blockers.append("A vendor bill is required before this payment can sync.")
            return blockers
        if payment.vendor_bill.sync_record is None or payment.vendor_bill.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED:
            blockers.append("The related vendor bill must sync successfully before the payment can sync.")
        if payment.is_credit_card_payoff:
            try:
                Epic5AccountingService._account_code(
                    mapping_key=PropertyLedgerAccountMapping.MappingKey.CREDIT_CARD_LIABILITY,
                    field_name="credit_card_account_name",
                )
                Epic5AccountingService._account_code(
                    mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
                    field_name="bank_account_name",
                )
            except ValidationError as exc:
                blockers.extend(exc.messages)
        elif payment.payment_method == VendorPayment.PaymentMethod.CREDIT_CARD:
            try:
                Epic5AccountingService._account_code(
                    mapping_key=PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_PAYABLE,
                    field_name="vendor_bill",
                )
                Epic5AccountingService._account_code(
                    mapping_key=PropertyLedgerAccountMapping.MappingKey.CREDIT_CARD_LIABILITY,
                    field_name="credit_card_account_name",
                )
            except ValidationError as exc:
                blockers.extend(exc.messages)
        else:
            try:
                Epic5AccountingService._account_code(
                    mapping_key=PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_PAYABLE,
                    field_name="vendor_bill",
                )
                Epic5AccountingService._account_code(
                    mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
                    field_name="bank_account_name",
                )
            except ValidationError as exc:
                blockers.extend(exc.messages)
        return blockers

    @staticmethod
    def _payment_event_details(payment: VendorPayment) -> dict[str, Any]:
        if payment.is_credit_card_payoff:
            event_type = "credit_card.payoff"
            accounting_entries = [
                {
                    "account_code": Epic5AccountingService._account_code(
                        mapping_key=PropertyLedgerAccountMapping.MappingKey.CREDIT_CARD_LIABILITY,
                        field_name="credit_card_account_name",
                    ),
                    "direction": "debit",
                    "amount": str(payment.amount.quantize(Decimal("0.01"))),
                },
                {
                    "account_code": Epic5AccountingService._account_code(
                        mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
                        field_name="bank_account_name",
                    ),
                    "direction": "credit",
                    "amount": str(payment.amount.quantize(Decimal("0.01"))),
                },
            ]
        elif payment.payment_method == VendorPayment.PaymentMethod.CREDIT_CARD:
            event_type = "vendor_payment.credit_card"
            accounting_entries = [
                {
                    "account_code": Epic5AccountingService._account_code(
                        mapping_key=PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_PAYABLE,
                        field_name="vendor_bill",
                    ),
                    "direction": "debit",
                    "amount": str(payment.amount.quantize(Decimal("0.01"))),
                },
                {
                    "account_code": Epic5AccountingService._account_code(
                        mapping_key=PropertyLedgerAccountMapping.MappingKey.CREDIT_CARD_LIABILITY,
                        field_name="credit_card_account_name",
                    ),
                    "direction": "credit",
                    "amount": str(payment.amount.quantize(Decimal("0.01"))),
                },
            ]
        else:
            event_type = "vendor_payment.sent"
            accounting_entries = [
                {
                    "account_code": Epic5AccountingService._account_code(
                        mapping_key=PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_PAYABLE,
                        field_name="vendor_bill",
                    ),
                    "direction": "debit",
                    "amount": str(payment.amount.quantize(Decimal("0.01"))),
                },
                {
                    "account_code": Epic5AccountingService._account_code(
                        mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
                        field_name="bank_account_name",
                    ),
                    "direction": "credit",
                    "amount": str(payment.amount.quantize(Decimal("0.01"))),
                },
            ]

        return {
            "vendor_id": payment.vendor_id,
            "vendor_bill_id": payment.vendor_bill_id,
            "payment_date": payment.payment_date.isoformat(),
            "amount": str(payment.amount.quantize(Decimal("0.01"))),
            "payment_method": payment.payment_method,
            "bank_account_name": payment.bank_account_name,
            "credit_card_account_name": payment.credit_card_account_name,
            "memo": payment.memo,
            "check_number": payment.check_number,
            "check_status": payment.check_status,
            "is_credit_card_payoff": payment.is_credit_card_payoff,
            "notes": payment.notes,
            "accounting_entries": accounting_entries,
        }

    @staticmethod
    def _request_payload(payment: VendorPayment) -> tuple[dict[str, Any], str]:
        if payment.is_credit_card_payoff:
            domain_event_type = "credit_card.payoff"
            source_event_type = "credit_card.payoff"
        elif payment.payment_method == VendorPayment.PaymentMethod.CREDIT_CARD:
            domain_event_type = "vendor_payment.credit_card"
            source_event_type = "vendor_payment.credit_card"
        else:
            domain_event_type = "vendor_payment.sent"
            source_event_type = "vendor_payment.sent"

        return VendorPaymentService._build_event_payload(
            source_system="propertyledger",
            domain_event_type=domain_event_type,
            external_id=f"vendor-payment:{payment.pk}",
            source_object_type="vendor_payment",
            source_object_id=str(payment.pk),
            occurred_at=payment.created_at.isoformat(),
            payload=VendorPaymentService._payment_event_details(payment),
        ), source_event_type

    @staticmethod
    @transaction.atomic
    def save_and_sync_payment(payment: VendorPayment) -> VendorPayment:
        VendorPaymentService._normalize_payment_account(payment)
        payment.full_clean()
        payment.save()
        if payment.status == VendorPayment.Status.VOIDED:
            return payment
        if payment.sync_record and payment.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
            return payment
        if VendorPaymentService._sync_blockers(payment):
            if payment.status != VendorPayment.Status.POSTED:
                payment.status = VendorPayment.Status.DRAFT
                payment.save(update_fields=["status", "updated_at"])
            return payment
        return VendorPaymentService.sync_payment(payment)

    @staticmethod
    @transaction.atomic
    def sync_payment(payment: VendorPayment) -> VendorPayment:
        use_payment_endpoint = not payment.is_credit_card_payoff and payment.payment_method != VendorPayment.PaymentMethod.CREDIT_CARD
        if use_payment_endpoint:
            request_payload = LedgerOSVendorPaymentService._build_payment_payload(payment)
            source_event_type = "vendor_payment.sent"
            ledgeros_resource_type = "payment"
            ledgeros_path = LedgerOSVendorPaymentService.PAYMENT_PATH
            response_id_key = "payment"
            response_journal_key = "journal_entry"
        else:
            request_payload, source_event_type = VendorPaymentService._request_payload(payment)
            ledgeros_resource_type = "sync_event"
            ledgeros_path = LedgerOSSyncEventService.SYNC_EVENT_PATH
            response_id_key = "sync_event"
            response_journal_key = ""
        sync_record = VendorPaymentService._build_sync_record(
            local_object_type="vendor_payment",
            local_object_id=str(payment.pk),
            source_event_type=source_event_type,
            external_id=f"vendor-payment:{payment.pk}",
            request_payload=request_payload,
            ledgeros_resource_type=ledgeros_resource_type,
        )
        payment.sync_record = sync_record
        payment.save(update_fields=["sync_record", "updated_at"])

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])
        payment.status = VendorPayment.Status.READY_TO_SYNC
        payment.save(update_fields=["status", "updated_at"])

        try:
            result = LedgerOSSyncEventService._submit(
                method="POST",
                path=ledgeros_path,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Vendor payment sync failed", extra={"vendor_payment_id": payment.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return payment

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get(response_id_key, {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        journal_entry_id = _response_journal_entry_id(result.payload)
        if journal_entry_id:
            sync_record.ledgeros_journal_entry_id = journal_entry_id
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        update_fields = ["status", "ledgeros_resource_id", "response_payload", "last_synced_at", "updated_at"]
        if journal_entry_id:
            update_fields.insert(2, "ledgeros_journal_entry_id")
        sync_record.save(update_fields=update_fields)
        payment.status = VendorPayment.Status.POSTED
        payment.save(update_fields=["status", "updated_at"])
        return payment


class DebtServicePaymentService(Epic5AccountingService):
    @staticmethod
    def _normalize_payment_account(payment: DebtServicePayment) -> None:
        if not payment.payment_account_name.strip():
            payment.payment_account_name = _operating_bank_account_name()

    @staticmethod
    def _sync_blockers(payment: DebtServicePayment) -> list[str]:
        blockers: list[str] = []
        try:
            Epic5AccountingService._account_code(
                mapping_key=PropertyLedgerAccountMapping.MappingKey.MORTGAGE_OR_LOAN_LIABILITY,
                field_name="loan_liability_account_name",
            )
            Epic5AccountingService._account_code(
                mapping_key=PropertyLedgerAccountMapping.MappingKey.INTEREST_EXPENSE,
                field_name="interest_expense_account_name",
            )
            Epic5AccountingService._account_code(
                mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
                field_name="payment_account_name",
            )
        except ValidationError as exc:
            blockers.extend(exc.messages)
        return blockers

    @staticmethod
    def _payment_event_details(payment: DebtServicePayment) -> dict[str, Any]:
        return {
            "property_id": payment.property_id,
            "lender_id": payment.lender_id,
            "payment_date": payment.payment_date.isoformat(),
            "total_amount": str(payment.total_amount.quantize(Decimal("0.01"))),
            "principal_amount": str(payment.principal_amount.quantize(Decimal("0.01"))),
            "interest_amount": str(payment.interest_amount.quantize(Decimal("0.01"))),
            "payment_account_name": payment.payment_account_name,
            "loan_liability_account_name": payment.loan_liability_account_name,
            "interest_expense_account_name": payment.interest_expense_account_name,
            "memo": payment.memo,
            "accounting_entries": [
                {
                    "account_code": Epic5AccountingService._account_code(
                        mapping_key=PropertyLedgerAccountMapping.MappingKey.MORTGAGE_OR_LOAN_LIABILITY,
                        field_name="loan_liability_account_name",
                    ),
                    "direction": "debit",
                    "amount": str(payment.principal_amount.quantize(Decimal("0.01"))),
                },
                {
                    "account_code": Epic5AccountingService._account_code(
                        mapping_key=PropertyLedgerAccountMapping.MappingKey.INTEREST_EXPENSE,
                        field_name="interest_expense_account_name",
                    ),
                    "direction": "debit",
                    "amount": str(payment.interest_amount.quantize(Decimal("0.01"))),
                },
                {
                    "account_code": Epic5AccountingService._account_code(
                        mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
                        field_name="payment_account_name",
                    ),
                    "direction": "credit",
                    "amount": str(payment.total_amount.quantize(Decimal("0.01"))),
                },
            ],
        }

    @staticmethod
    def _request_payload(payment: DebtServicePayment) -> dict[str, Any]:
        return DebtServicePaymentService._build_event_payload(
            source_system="propertyledger",
            domain_event_type="debt_service.payment_recorded",
            external_id=f"debt-service-payment:{payment.pk}",
            source_object_type="debt_service_payment",
            source_object_id=str(payment.pk),
            occurred_at=payment.created_at.isoformat(),
            payload=DebtServicePaymentService._payment_event_details(payment),
        )

    @staticmethod
    @transaction.atomic
    def save_and_sync_payment(payment: DebtServicePayment) -> DebtServicePayment:
        DebtServicePaymentService._normalize_payment_account(payment)
        payment.full_clean()
        payment.save()
        if payment.status == DebtServicePayment.Status.VOIDED:
            return payment
        if payment.sync_record and payment.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
            return payment
        if DebtServicePaymentService._sync_blockers(payment):
            if payment.status != DebtServicePayment.Status.POSTED:
                payment.status = DebtServicePayment.Status.DRAFT
                payment.save(update_fields=["status", "updated_at"])
            return payment
        return DebtServicePaymentService.sync_payment(payment)

    @staticmethod
    @transaction.atomic
    def sync_payment(payment: DebtServicePayment) -> DebtServicePayment:
        request_payload = DebtServicePaymentService._request_payload(payment)
        sync_record = DebtServicePaymentService._build_sync_record(
            local_object_type="debt_service_payment",
            local_object_id=str(payment.pk),
            source_event_type="debt_service.payment_recorded",
            external_id=f"debt-service-payment:{payment.pk}",
            request_payload=request_payload,
        )
        payment.sync_record = sync_record
        payment.save(update_fields=["sync_record", "updated_at"])

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])
        payment.status = DebtServicePayment.Status.READY_TO_SYNC
        payment.save(update_fields=["status", "updated_at"])

        try:
            result = LedgerOSSyncEventService._submit(
                method="POST",
                path=LedgerOSSyncEventService.SYNC_EVENT_PATH,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Debt service payment sync failed", extra={"debt_service_payment_id": payment.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return payment

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("sync_event", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.ledgeros_journal_entry_id = _response_journal_entry_id(result.payload)
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "ledgeros_journal_entry_id", "response_payload", "last_synced_at", "updated_at"])
        payment.status = DebtServicePayment.Status.POSTED
        payment.save(update_fields=["status", "updated_at"])
        return payment


class MaintenanceExpenseSummaryService:
    @staticmethod
    def summary_rows() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        query = (
            VendorBill.objects.filter(sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED)
            .select_related("maintenance_category", "property", "unit", "vendor")
            .values("expense_category", "maintenance_category__name")
            .annotate(total_amount=models.Sum("amount"), bill_count=models.Count("id"))
            .order_by("expense_category", "maintenance_category__name")
        )
        for row in query:
            rows.append(
                {
                    "expense_category": row["expense_category"],
                    "expense_category_label": dict(VendorBill.ExpenseCategory.choices).get(
                        row["expense_category"], row["expense_category"]
                    ),
                    "maintenance_category_name": row["maintenance_category__name"] or "-",
                    "total_amount": (row["total_amount"] or Decimal("0.00")).quantize(Decimal("0.01")),
                    "bill_count": row["bill_count"] or 0,
                }
            )
        return rows
