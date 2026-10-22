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
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from ledgeros.idempotency import build_idempotency_key
from ledgeros.audit import audit_failure, audit_success
from ledgeros.models import (
    LedgerOSConnectionSettings,
    LedgerOSSyncRecord,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    TenantCharge,
    Lease,
)
from ledgeros.signing import sign_api_request
from payments.approval_services import VendorBillApprovalService
from payments.authorization import require_bill_editor, require_vendor_payer
from payments.models import (
    DebtServicePayment,
    PaymentWorkflowSettings,
    SecurityDepositEvent,
    TenantPayment,
    TenantPaymentApplication,
    TenantPaymentDepositAllocation,
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


class LedgerOSBankingReadService:
    BANK_ACCOUNTS_PATH = "/api/v1/bank-accounts/"
    BANK_RECONCILIATIONS_PATH = "/api/v1/bank-reconciliations/"

    @staticmethod
    def _format_http_error(exc: HTTPError, *, path: str) -> str:
        try:
            raw_body = exc.read()
        except Exception:
            raw_body = b""

        if raw_body:
            try:
                body = raw_body.decode("utf-8").strip()
            except Exception:
                body = raw_body.decode("utf-8", errors="replace").strip()
            if body:
                return f"LedgerOS returned HTTP {exc.code} for GET {path}: {body}"

        return f"LedgerOS returned HTTP {exc.code} for GET {path}: {exc.reason}"

    @staticmethod
    def _canonical_json_bytes(payload: bytes = b"") -> bytes:
        return payload

    @staticmethod
    def _connection_values() -> tuple[str, str, str, str, int, str]:
        return LedgerOSSyncEventService._connection_values()

    @staticmethod
    def _request_json(*, path: str) -> Any:
        base_url, host_header, client_id, secret, timeout, api_key = LedgerOSBankingReadService._connection_values()
        if not base_url:
            raise ValidationError({"ledgeros": "Missing LedgerOS configuration: base_url"})

        body = LedgerOSBankingReadService._canonical_json_bytes()
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        signed = sign_api_request(
            method="GET",
            path=path.split("?", 1)[0],
            body=body,
            timestamp=timestamp,
            nonce=nonce,
            client_id=client_id,
            secret=secret,
        )
        headers = {
            "X-LedgerOS-Client-Id": client_id,
            "X-LedgerOS-Timestamp": timestamp,
            "X-LedgerOS-Nonce": nonce,
            "X-LedgerOS-Signature": signed.signature,
        }
        if host_header:
            headers["Host"] = host_header
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request = Request(f"{base_url.rstrip('/')}{path}", method="GET", headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                response_raw = response.read().decode("utf-8").strip()
                if response.status != 200:
                    raise RuntimeError(
                        f"LedgerOS returned HTTP {response.status} for GET {path}: {response_raw}"
                    )
                if not response_raw:
                    return []
                try:
                    response_payload = json.loads(response_raw)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("LedgerOS banking response was not valid JSON.") from exc
                return response_payload
        except HTTPError as exc:
            raise RuntimeError(LedgerOSBankingReadService._format_http_error(exc, path=path)) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    def _coerce_list_payload(payload: Any, *, path: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, list):
                return [item for item in results if isinstance(item, dict)]
        raise RuntimeError(f"LedgerOS returned an unexpected payload for GET {path}.")

    @staticmethod
    def list_bank_accounts() -> list[dict[str, Any]]:
        payload = LedgerOSBankingReadService._request_json(path=LedgerOSBankingReadService.BANK_ACCOUNTS_PATH)
        return LedgerOSBankingReadService._coerce_list_payload(
            payload,
            path=LedgerOSBankingReadService.BANK_ACCOUNTS_PATH,
        )

    @staticmethod
    def list_bank_reconciliations() -> list[dict[str, Any]]:
        payload = LedgerOSBankingReadService._request_json(
            path=LedgerOSBankingReadService.BANK_RECONCILIATIONS_PATH
        )
        return LedgerOSBankingReadService._coerce_list_payload(
            payload,
            path=LedgerOSBankingReadService.BANK_RECONCILIATIONS_PATH,
        )


class BillPaymentStatusService:
    LABELS = {
        "unpaid": "Unpaid", "partially_paid": "Partially paid", "paid": "Paid",
        "not_posted": "Not posted", "voided": "Voided", "needs_review": "Needs review",
        "unavailable": "Unavailable",
    }

    @staticmethod
    def statuses(bills):
        bills = list(bills)
        results = {}
        synced = []
        for bill in bills:
            status = "voided" if bill.status == VendorBill.Status.VOIDED else "not_posted"
            results[bill.pk] = {"status": status, "label": BillPaymentStatusService.LABELS[status],
                                "paid": None, "credited": None, "balance": None, "error": ""}
            if status != "voided" and bill.sync_record and bill.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
                synced.append(bill)
                results[bill.pk].update(status="unavailable", label="Unavailable")
        for start in range(0, len(synced), 100):
            batch = synced[start:start + 100]
            query = urlencode([("external_bill_number", f"vendor-bill:{bill.pk}") for bill in batch])
            try:
                payload = LedgerOSBankingReadService._request_json(path="/api/v1/bills/?" + query)
                if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                    raise RuntimeError("LedgerOS returned an invalid bill-status response.")
                rows = {}
                for row in payload["results"]:
                    if not isinstance(row, dict) or row.get("external_bill_number") in rows:
                        raise RuntimeError("LedgerOS returned invalid or duplicate bill-status rows.")
                    rows[row.get("external_bill_number")] = row
                for bill in batch:
                    row = rows.get(f"vendor-bill:{bill.pk}")
                    if row is None:
                        results[bill.pk]["error"] = "LedgerOS did not return this bill."
                        continue
                    state = row.get("payment_status")
                    if state not in BillPaymentStatusService.LABELS:
                        raise RuntimeError("LedgerOS returned an unknown bill payment status.")
                    total, paid, credited, balance = [Decimal(str(row[key])) for key in (
                        "total_amount", "amount_paid", "amount_credited", "outstanding_balance")]
                    if not all(value.is_finite() for value in (total, paid, credited, balance)):
                        raise RuntimeError("LedgerOS returned invalid bill amounts.")
                    error = ""
                    if total != bill.amount or total - paid - credited != balance or paid < 0 or credited < 0 or balance < 0:
                        state, error = "needs_review", "Bill amounts need reconciliation with LedgerOS."
                    results[bill.pk] = {"status": state, "label": BillPaymentStatusService.LABELS[state],
                                        "paid": paid, "credited": credited, "balance": balance, "error": error}
            except (ValidationError, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
                for bill in batch:
                    results[bill.pk] = {"status": "unavailable", "label": "Unavailable", "paid": None,
                                        "credited": None, "balance": None, "error": str(exc)}
        # Legacy generic journals have no bill application until explicitly linked.
        payments = VendorPayment.objects.filter(
            vendor_bill_id__in=[bill.pk for bill in synced], payment_method=VendorPayment.PaymentMethod.CREDIT_CARD,
            is_credit_card_payoff=False,
        ).select_related("sync_record")
        legacy_ids = set(LedgerOSSyncRecord.objects.filter(
            local_object_type="vendor_payment", ledgeros_resource_type="sync_event",
            source_event_type="vendor_payment.credit_card",
        ).values_list("local_object_id", flat=True))
        for payment in payments:
            record = payment.sync_record
            if record and record.ledgeros_resource_type == "payment" and record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
                continue
            if (record and record.ledgeros_resource_type == "sync_event") or str(payment.pk) in legacy_ids:
                results[payment.vendor_bill_id].update(status="needs_review", label="Needs review",
                    paid=None, credited=None, balance=None,
                    error="A legacy card payment needs its existing journal linked to this bill. Retry that payment to reconcile it.")
        return results


class LedgerOSPaymentService:
    PAYMENT_PATH = "/api/v1/payments/"

    @staticmethod
    def _build_payment_payload(application: TenantPaymentApplication) -> dict[str, Any]:
        charge_sync_record = application.charge.sync_record
        if (
            charge_sync_record is None
            or charge_sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED
            or not charge_sync_record.external_id
        ):
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
    def is_posted_result(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        payment = payload.get("payment")
        journal = payload.get("journal_entry")
        return bool(
            isinstance(payment, dict) and payment.get("id")
            and isinstance(journal, dict) and journal.get("id")
            and journal.get("status") == "posted"
        )

    @staticmethod
    def submit_payment_application(
        *,
        application: TenantPaymentApplication,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
    ) -> SyncResult:
        payload = payload or LedgerOSPaymentService._build_payment_payload(application)
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
        # General notes remain locally editable after approval and therefore
        # must not change the frozen LedgerOS posting payload.
        note = bill.repair_notes.strip()
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

        payload = {
            "source_type": "bill",
            "source_reference": bill_sync_record.external_id,
            "payment_date": payment.payment_date.isoformat(),
            "amount": str(payment.amount.quantize(Decimal("0.01"))),
        }
        if payment.payment_method == VendorPayment.PaymentMethod.CREDIT_CARD:
            payload["funding_account_code"] = Epic5AccountingService._account_code(
                mapping_key=PropertyLedgerAccountMapping.MappingKey.CREDIT_CARD_LIABILITY,
                field_name="credit_card_account_name",
            )
            legacy = VendorPaymentService.legacy_card_record(payment)
            if legacy is not None:
                event = (legacy.response_payload or {}).get("sync_event", {})
                try:
                    payload["existing_sync_event_id"] = int(event["id"])
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValidationError({"payment": "The legacy card payment needs manual reconciliation before retrying; its journal must not be posted again."}) from exc
        return payload

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
    def _account_code(*, mapping_key: str, field_name: str, expected_type: str) -> str:
        setup = PropertyLedgerSetup.load()
        mapping = setup.account_mappings.filter(mapping_key=mapping_key).first()
        if mapping is None or not mapping.is_valid_for_completion:
            raise ValidationError({field_name: f"A valid {mapping_key.replace('_', ' ')} mapping is required."})
        if mapping.ledgeros_account_type != expected_type:
            raise ValidationError({field_name: f"The {mapping_key.replace('_', ' ')} mapping must be an {expected_type} account."})
        return mapping.ledgeros_account_id

    @staticmethod
    def _posted_sync_event_result(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        event = payload.get("sync_event")
        journal = payload.get("journal_entry")
        return bool(
            isinstance(event, dict)
            and event.get("id")
            and isinstance(journal, dict)
            and journal.get("id")
            and journal.get("status") == "posted"
        )

    @staticmethod
    def _deposit_accounting_entries(*, amount: Decimal, received: bool = True) -> list[dict[str, str]]:
        cash_code = TenantPaymentService._account_code(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
            field_name="operating_bank_account",
            expected_type="asset",
        )
        liability_code = TenantPaymentService._account_code(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.TENANT_SECURITY_DEPOSITS_LIABILITY,
            field_name="tenant_security_deposits_liability",
            expected_type="liability",
        )
        formatted_amount = str(amount.quantize(Decimal("0.01")))
        if received:
            return [
                {"account_code": cash_code, "direction": "debit", "amount": formatted_amount},
                {"account_code": liability_code, "direction": "credit", "amount": formatted_amount},
            ]
        return [
            {"account_code": liability_code, "direction": "debit", "amount": formatted_amount},
            {"account_code": cash_code, "direction": "credit", "amount": formatted_amount},
        ]

    @staticmethod
    def set_deposit_allocation(
        *, payment: TenantPayment, lease: Lease | None, amount: Decimal
    ) -> TenantPaymentDepositAllocation | None:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        with transaction.atomic():
            payment = TenantPayment.objects.select_for_update().get(pk=payment.pk)
            existing = TenantPaymentDepositAllocation.objects.select_related("sync_record").filter(payment=payment).first()
            if existing and not existing.is_editable_after_sync:
                if existing.amount != amount or existing.lease_id != (lease.pk if lease else None):
                    raise ValidationError({"deposit_amount": "An attempted deposit allocation cannot be changed. Reconcile it before retrying."})
                return existing
            if not payment.is_editable_after_sync:
                raise ValidationError({"payment": "A receipt with attempted components cannot be changed."})
            if amount < Decimal("0.00") or amount > payment.amount:
                raise ValidationError({"deposit_amount": "Deposit amount must be between zero and the receipt total."})
            if amount == Decimal("0.00"):
                if existing:
                    existing.delete()
                return None
            if lease is None:
                raise ValidationError({"deposit_lease": "Choose the lease that owns the deposit."})
            if lease.tenant_id != payment.tenant_id or lease.unit.property_id != payment.property_id:
                raise ValidationError({"deposit_lease": "The deposit lease must match the receipt tenant and property."})
            allocation, _ = TenantPaymentDepositAllocation.objects.update_or_create(
                payment=payment,
                defaults={"lease": lease, "amount": amount},
            )
            return allocation

    @staticmethod
    def _build_deposit_allocation_payload(allocation: TenantPaymentDepositAllocation) -> dict[str, Any]:
        payment = allocation.payment
        return TenantPaymentService._build_sync_event_payload(
            source_system="propertyledger",
            domain_event_type="security_deposit.received",
            external_id=f"tenant-payment:{payment.pk}:deposit",
            source_object_type="tenant_payment_deposit_allocation",
            source_object_id=str(allocation.pk),
            occurred_at=f"{payment.payment_date.isoformat()}T00:00:00Z",
            payload={
                "receipt_id": payment.pk,
                "property_id": payment.property_id,
                "unit_id": allocation.lease.unit_id,
                "tenant_id": payment.tenant_id,
                "lease_id": allocation.lease_id,
                "payment_date": payment.payment_date.isoformat(),
                "payment_method": payment.payment_method,
                "reference": payment.reference,
                "total_receipt_amount": str(payment.amount.quantize(Decimal("0.01"))),
                "deposit_amount": str(allocation.amount.quantize(Decimal("0.01"))),
                "accounting_entries": TenantPaymentService._deposit_accounting_entries(amount=allocation.amount),
            },
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
        # Commit allocation identities before posting so a later failure cannot
        # roll them back after LedgerOS has already accepted an earlier payment.
        with transaction.atomic():
            payment = TenantPayment.objects.select_for_update().get(pk=payment.pk)
            if payment.status == TenantPayment.Status.POSTED or (
                payment.sync_record and payment.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
            ):
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
            remaining = payment.remaining_amount
            allocated_charge_ids = {allocation.charge_id for allocation in existing_allocations}
            for charge in open_charges:
                if charge.pk in allocated_charge_ids:
                    continue
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
                TenantPaymentApplication.objects.create(
                    payment=payment,
                    charge=charge,
                    amount_applied=amount_applied,
                )
                remaining = (remaining - amount_applied).quantize(Decimal("0.01"))

        for allocation in payment.applications.order_by("id"):
            TenantPaymentService.sync_payment_application(allocation)

        with transaction.atomic():
            payment = TenantPayment.objects.select_for_update().get(pk=payment.pk)
            if payment.status == TenantPayment.Status.POSTED:
                return payment
            all_allocations_synced = all(
                allocation.sync_record
                and allocation.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
                for allocation in payment.applications.all()
            )
            deposit = TenantPaymentDepositAllocation.objects.select_related("sync_record").filter(payment=payment).first()
            deposit_synced = deposit is None or (
                deposit.sync_record
                and deposit.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
            )
            if not payment.applications.exists() and deposit is None:
                payment.status = TenantPayment.Status.DRAFT
            elif all_allocations_synced and deposit_synced and payment.remaining_amount == Decimal("0.00"):
                payment.status = TenantPayment.Status.READY_TO_SYNC
            else:
                payment.status = TenantPayment.Status.ALLOCATED
            payment.save(update_fields=["status", "updated_at"])
            return payment

    @staticmethod
    @transaction.atomic
    def sync_payment_application(application: TenantPaymentApplication) -> TenantPaymentApplication:
        application = TenantPaymentApplication.objects.select_for_update(of=("self",)).select_related(
            "payment", "charge__sync_record", "sync_record"
        ).get(pk=application.pk)
        if application.payment.status == TenantPayment.Status.VOIDED:
            raise ValidationError({"payment": "Voided payments cannot be posted."})
        current_payload = LedgerOSPaymentService._build_payment_payload(application)
        if application.frozen_request_payload is not None and application.frozen_request_payload != current_payload:
            raise ValidationError({"payment": "An attempted payment allocation cannot be changed. Reconcile it before retrying."})
        if application.frozen_request_payload is None:
            application.frozen_request_payload = current_payload
            application.save(update_fields=["frozen_request_payload", "updated_at"])
        request_payload = application.frozen_request_payload
        sync_record = application.sync_record
        if sync_record is not None:
            if sync_record.request_hash != TenantPaymentService._sync_record_payload(request_payload):
                raise ValidationError({"payment": "An attempted payment allocation cannot be changed. Reconcile it before retrying."})
            if (
                sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
                and sync_record.ledgeros_resource_type == "payment"
                and LedgerOSPaymentService.is_posted_result(sync_record.response_payload)
            ):
                return application
        else:
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

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])

        try:
            result = LedgerOSPaymentService.submit_payment_application(
                application=application,
                idempotency_key=sync_record.idempotency_key,
                payload=request_payload,
            )
            if not LedgerOSPaymentService.is_posted_result(result.payload):
                raise RuntimeError("LedgerOS did not return a payment with a posted journal entry. Retry with the same idempotency key or reconcile the result.")
        except Exception as exc:
            logger.warning("Tenant payment application sync failed", extra={"payment_application_id": application.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return application

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_type = "payment"
        sync_record.ledgeros_resource_id = str(result.payload["payment"]["id"])
        sync_record.ledgeros_journal_entry_id = str(result.payload["journal_entry"]["id"])
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_type", "ledgeros_resource_id", "ledgeros_journal_entry_id", "response_payload", "last_synced_at", "updated_at"])
        return application

    @staticmethod
    @transaction.atomic
    def sync_deposit_allocation(allocation: TenantPaymentDepositAllocation) -> TenantPaymentDepositAllocation:
        allocation = TenantPaymentDepositAllocation.objects.select_for_update(of=("self",)).select_related(
            "payment", "lease__unit", "sync_record"
        ).get(pk=allocation.pk)
        if allocation.payment.status == TenantPayment.Status.VOIDED:
            raise ValidationError({"payment": "Voided receipts cannot be posted."})
        current_payload = TenantPaymentService._build_deposit_allocation_payload(allocation)
        if allocation.frozen_request_payload is not None and allocation.frozen_request_payload != current_payload:
            raise ValidationError({"deposit_amount": "An attempted deposit allocation cannot be changed. Reconcile it before retrying."})
        if allocation.frozen_request_payload is None:
            allocation.frozen_request_payload = current_payload
            allocation.save(update_fields=["frozen_request_payload", "updated_at"])
        request_payload = allocation.frozen_request_payload
        sync_record = allocation.sync_record
        if sync_record is not None:
            if sync_record.request_hash != TenantPaymentService._sync_record_payload(request_payload):
                raise ValidationError({"deposit_amount": "An attempted deposit allocation cannot be changed. Reconcile it before retrying."})
            if (
                sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
                and TenantPaymentService._posted_sync_event_result(sync_record.response_payload)
            ):
                return allocation
        else:
            sync_record = TenantPaymentService._build_sync_record(
                local_object_type="tenant_payment_deposit_allocation",
                local_object_id=str(allocation.pk),
                source_event_type="tenant_payment.deposit_received",
                external_id=f"tenant-payment:{allocation.payment_id}:deposit",
                request_payload=request_payload,
            )
            allocation.sync_record = sync_record
            allocation.save(update_fields=["sync_record", "updated_at"])

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])
        try:
            result = LedgerOSSyncEventService._submit(
                method="POST",
                path=LedgerOSSyncEventService.SYNC_EVENT_PATH,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
            if not TenantPaymentService._posted_sync_event_result(result.payload):
                raise RuntimeError(
                    "LedgerOS did not return a deposit event with a posted journal entry. "
                    "Retry with the same idempotency key or reconcile the result."
                )
        except Exception as exc:
            logger.warning("Tenant receipt deposit sync failed", extra={"deposit_allocation_id": allocation.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return allocation

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_type = "sync_event"
        sync_record.ledgeros_resource_id = str(result.payload["sync_event"]["id"])
        sync_record.ledgeros_journal_entry_id = str(result.payload["journal_entry"]["id"])
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=[
            "status", "ledgeros_resource_type", "ledgeros_resource_id", "ledgeros_journal_entry_id",
            "response_payload", "last_synced_at", "updated_at",
        ])
        return allocation

    @staticmethod
    @transaction.atomic
    def sync_payment(payment: TenantPayment) -> TenantPayment:
        payment = TenantPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == TenantPayment.Status.VOIDED:
            raise ValidationError({"payment": "Voided payments cannot be finalized."})
        deposit = TenantPaymentDepositAllocation.objects.select_related("sync_record", "lease__unit").filter(payment=payment).first()
        if not payment.applications.exists() and deposit is None:
            raise ValidationError({"payment": "Receipt must include an invoice or deposit allocation before sync."})
        if payment.remaining_amount != Decimal("0.00"):
            raise ValidationError({"payment": "Payment must be fully allocated before finalization. Unapplied credit posting is not supported."})

        applications = []
        errors = []
        for application in payment.applications.select_related("charge", "sync_record").order_by("id"):
            application = TenantPaymentService.sync_payment_application(application)
            record = application.sync_record
            if record.status != LedgerOSSyncRecord.Status.SUCCEEDED:
                errors.append(record.last_error or "Payment allocation did not post.")
            else:
                applications.append({
                    "application_id": application.pk,
                    "sync_record_id": record.pk,
                    "payment_id": record.ledgeros_resource_id,
                    "journal_entry_id": record.ledgeros_journal_entry_id,
                    "amount": str(application.amount_applied),
                })

        deposit_summary = None
        if deposit is not None:
            deposit = TenantPaymentService.sync_deposit_allocation(deposit)
            deposit_record = deposit.sync_record
            if deposit_record.status != LedgerOSSyncRecord.Status.SUCCEEDED:
                errors.append(deposit_record.last_error or "Deposit allocation did not post.")
            else:
                deposit_summary = {
                    "deposit_allocation_id": deposit.pk,
                    "sync_record_id": deposit_record.pk,
                    "sync_event_id": deposit_record.ledgeros_resource_id,
                    "journal_entry_id": deposit_record.ledgeros_journal_entry_id,
                    "amount": str(deposit.amount.quantize(Decimal("0.01"))),
                }

        # This local summary is not sent to LedgerOS. Keep legacy receipt events
        # under tenant_payment.received intact for audit history.
        summary = {
            "payment_id": payment.pk,
            "amount": str(payment.amount.quantize(Decimal("0.01"))),
            "rent_amount": str(payment.allocated_amount.quantize(Decimal("0.01"))),
            "deposit_amount": str(payment.deposit_amount.quantize(Decimal("0.01"))),
            "applications": applications,
            "deposit": deposit_summary,
        }
        if (
            not errors
            and payment.status == TenantPayment.Status.POSTED
            and payment.sync_record
            and payment.sync_record.source_event_type == "tenant_payment.finalized"
            and payment.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
            and payment.sync_record.response_payload == summary
        ):
            return payment
        record = TenantPaymentService._build_sync_record(
            local_object_type="tenant_payment", local_object_id=str(payment.pk),
            source_event_type="tenant_payment.finalized",
            external_id=f"tenant-payment:{payment.pk}:finalized",
            request_payload=summary, ledgeros_resource_type="payment_collection",
        )
        record.status = LedgerOSSyncRecord.Status.FAILED if errors else LedgerOSSyncRecord.Status.SUCCEEDED
        record.last_error = "; ".join(errors) or None
        record.response_payload = summary
        record.last_synced_at = None if errors else timezone.now()
        record.save(update_fields=["status", "last_error", "response_payload", "last_synced_at", "updated_at"])
        payment.sync_record = record
        payment.status = TenantPayment.Status.READY_TO_SYNC if errors else TenantPayment.Status.POSTED
        payment.save(update_fields=["sync_record", "status", "updated_at"])
        return payment

    @staticmethod
    @transaction.atomic
    def sync_security_deposit_event(event: SecurityDepositEvent) -> SecurityDepositEvent:
        if event.event_type not in {
            SecurityDepositEvent.EventType.RECEIVED,
            SecurityDepositEvent.EventType.REFUNDED,
        }:
            raise ValidationError({
                "event_type": (
                    "Only received and refunded deposit events have a verified cash/liability posting contract. "
                    "Required and deducted events need an explicit accounting treatment before posting."
                )
            })
        details = TenantPaymentService._security_deposit_event_details(event)
        details["accounting_entries"] = TenantPaymentService._deposit_accounting_entries(
            amount=event.amount,
            received=event.event_type == SecurityDepositEvent.EventType.RECEIVED,
        )
        request_payload = TenantPaymentService._build_sync_event_payload(
            source_system="propertyledger",
            domain_event_type=f"security_deposit.{event.event_type}",
            external_id=f"security-deposit:{event.pk}",
            source_object_type="security_deposit_event",
            source_object_id=str(event.pk),
            occurred_at=f"{event.event_date.isoformat()}T00:00:00Z",
            payload=details,
        )
        if event.frozen_request_payload is not None and event.frozen_request_payload != request_payload:
            raise ValidationError({"event": "An attempted security deposit event cannot be changed. Reconcile it before retrying."})
        if event.frozen_request_payload is None:
            event.frozen_request_payload = request_payload
            event.save(update_fields=["frozen_request_payload", "updated_at"])
        request_payload = event.frozen_request_payload
        sync_record = event.sync_record
        if sync_record is not None:
            if sync_record.request_hash != TenantPaymentService._sync_record_payload(request_payload):
                raise ValidationError({"event": "An attempted security deposit event cannot be changed. Reconcile it before retrying."})
            if (
                sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
                and TenantPaymentService._posted_sync_event_result(sync_record.response_payload)
            ):
                return event
        else:
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
            if not TenantPaymentService._posted_sync_event_result(result.payload):
                raise RuntimeError(
                    "LedgerOS did not return a security deposit event with a posted journal entry. "
                    "Retry with the same idempotency key or reconcile the result."
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
    def save_and_sync_bill(bill: VendorBill, *, actor) -> VendorBill:
        """Compatibility entrypoint: WP2 saves locally and requires explicit approval/posting."""
        return VendorBillApprovalService.save_draft(bill, actor=actor)

    @staticmethod
    @transaction.atomic
    def sync_bill(bill: VendorBill, *, actor) -> VendorBill:
        require_bill_editor(actor)
        bill = VendorBill.objects.select_for_update().get(pk=bill.pk)
        approval_blocker = VendorBillApprovalService.approval_blocker(bill)
        if approval_blocker:
            raise ValidationError(approval_blocker)
        if bill.sync_record and bill.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
            return bill
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
            audit_failure(
                action="vendor_bill_post_failed",
                record_type="VendorBill",
                record_id=str(bill.pk),
                user=actor,
                source="service",
                metadata={"sync_record_id": sync_record.pk, "error": str(exc)},
            )
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
        audit_success(
            action="vendor_bill_posted",
            record=bill,
            user=actor,
            source="service",
            metadata={"sync_record_id": sync_record.pk},
        )
        return bill


class VendorPaymentService(Epic5AccountingService):
    BILL_PAYMENT_FIELDS = (
        "payment_date", "amount", "payment_method", "bank_account_name",
        "credit_card_account_name", "memo", "check_number", "notes",
    )

    @staticmethod
    def bill_payment_blocker(bill, status):
        if bill.status == VendorBill.Status.VOIDED:
            return "Voided bills cannot be paid."
        approval_blocker = VendorBillApprovalService.approval_blocker(bill)
        if approval_blocker:
            return approval_blocker
        if bill.status != VendorBill.Status.POSTED or not bill.sync_record or bill.sync_record.status != LedgerOSSyncRecord.Status.SUCCEEDED:
            return "The bill must sync successfully to LedgerOS before payment."
        if status["status"] == "paid":
            return "This bill is fully settled."
        if status["status"] not in {"unpaid", "partially_paid"} or status["balance"] is None:
            return "A confirmed outstanding balance is required. Resolve the bill payment status before paying."
        if status["balance"] <= 0:
            return "This bill has no outstanding balance."
        return ""

    @staticmethod
    def pay_bill(*, bill, submission_id, details, actor):
        require_vendor_payer(actor)
        try:
            submission_id = uuid.UUID(str(submission_id))
        except (TypeError, ValueError) as exc:
            raise ValidationError("A valid payment submission ID is required.") from exc
        if set(details) - set(VendorPaymentService.BILL_PAYMENT_FIELDS):
            raise ValidationError("Only the reviewed bill payment fields may be submitted.")
        # Persist the local payment identity before an outbound write. A timeout
        # must never cause a replacement payment with another idempotency key.
        with transaction.atomic():
            bill = VendorBill.objects.select_for_update().get(pk=bill.pk)
            candidate = VendorPayment(vendor=bill.vendor, vendor_bill=bill, **details)
            VendorPaymentService._normalize_payment_account(candidate)
            candidate.full_clean()
            if candidate.amount <= 0:
                raise ValidationError("Payment amount must be positive.")
            reviewed = {field: str(getattr(candidate, field) or "") for field in VendorPaymentService.BILL_PAYMENT_FIELDS}
            reviewed["amount"] = str(candidate.amount.quantize(Decimal("0.01")))
            fingerprint = TenantPaymentService._sync_record_payload(reviewed)
            payment = VendorPayment.objects.filter(submission_id=submission_id).first()
            if payment is not None:
                if payment.vendor_bill_id != bill.pk or payment.submission_hash != fingerprint:
                    raise ValidationError("This submission was already used with different payment details.")
            else:
                status = BillPaymentStatusService.statuses([bill])[bill.pk]
                blocker = VendorPaymentService.bill_payment_blocker(bill, status)
                if blocker:
                    raise ValidationError(blocker)
                if candidate.amount > status["balance"]:
                    raise ValidationError("Payment amount cannot exceed the current outstanding balance.")
                blockers = VendorPaymentService._sync_blockers(candidate)
                if blockers:
                    raise ValidationError(blockers)
                candidate.submission_id = submission_id
                candidate.submission_hash = fingerprint
                candidate.initiated_by = actor
                candidate.save()
                payment = candidate
        return VendorPaymentService.sync_payment(payment, actor=actor)

    @staticmethod
    def legacy_card_record(payment):
        if payment.sync_record and payment.sync_record.ledgeros_resource_type == "sync_event":
            return payment.sync_record
        return LedgerOSSyncRecord.objects.filter(
            local_object_type="vendor_payment", local_object_id=str(payment.pk),
            source_event_type="vendor_payment.credit_card", ledgeros_resource_type="sync_event",
        ).first()

    @staticmethod
    def _normalize_payment_account(payment: VendorPayment) -> None:
        if payment.payment_method == VendorPayment.PaymentMethod.CREDIT_CARD and not payment.is_credit_card_payoff:
            payment.bank_account_name = ""
        elif payment.is_credit_card_payoff or payment.payment_method != VendorPayment.PaymentMethod.CREDIT_CARD:
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
    def save_and_sync_payment(payment: VendorPayment, *, actor) -> VendorPayment:
        if payment.is_credit_card_payoff:
            require_bill_editor(actor)
        else:
            require_vendor_payer(actor)
            if payment.pk is None and payment.submission_id is None:
                raise ValidationError(
                    "Start a new vendor settlement from the approved bill so its submission identity is preserved."
                )
        VendorPaymentService._normalize_payment_account(payment)
        payment.full_clean()
        if payment.initiated_by_id is None:
            payment.initiated_by = actor
        current_bill = VendorBill.objects.get(pk=payment.vendor_bill_id)
        payment.vendor_bill = current_bill
        if not payment.is_credit_card_payoff:
            approval_blocker = VendorBillApprovalService.approval_blocker(current_bill)
            if approval_blocker:
                raise ValidationError(approval_blocker)
        payment.save()
        if payment.status == VendorPayment.Status.VOIDED:
            return payment
        if payment.sync_record and payment.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
            if payment.is_credit_card_payoff or payment.sync_record.ledgeros_resource_type == "payment":
                return payment
        if VendorPaymentService._sync_blockers(payment):
            if payment.status != VendorPayment.Status.POSTED:
                payment.status = VendorPayment.Status.DRAFT
                payment.save(update_fields=["status", "updated_at"])
            return payment
        return VendorPaymentService.sync_payment(payment, actor=actor)

    @staticmethod
    @transaction.atomic
    def sync_payment(payment: VendorPayment, *, actor) -> VendorPayment:
        # Read related sync state after acquiring the lock. A joined SELECT can
        # retain pre-wait sync state while another submission finishes posting.
        payment = VendorPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.is_credit_card_payoff:
            require_bill_editor(actor)
        else:
            require_vendor_payer(actor)
        if payment.status == VendorPayment.Status.VOIDED:
            raise ValidationError({"payment": "Voided payments cannot be posted."})
        if payment.sync_record and payment.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED and payment.sync_record.ledgeros_resource_type == "payment":
            return payment
        blockers = VendorPaymentService._sync_blockers(payment)
        if blockers:
            raise ValidationError(blockers)
        attempted = bool(
            payment.sync_record
            and (
                payment.sync_record.attempt_count
                or payment.sync_record.ledgeros_resource_type == "sync_event"
            )
        )
        if not payment.is_credit_card_payoff and not attempted:
            approval_blocker = VendorBillApprovalService.approval_blocker(payment.vendor_bill)
            if approval_blocker:
                raise ValidationError(approval_blocker)
            status = BillPaymentStatusService.statuses([payment.vendor_bill])[payment.vendor_bill_id]
            blocker = VendorPaymentService.bill_payment_blocker(payment.vendor_bill, status)
            if blocker:
                raise ValidationError(blocker)
            if payment.amount > status["balance"]:
                raise ValidationError("Payment amount cannot exceed the current outstanding balance.")
        use_payment_endpoint = not payment.is_credit_card_payoff
        if use_payment_endpoint:
            request_payload = LedgerOSVendorPaymentService._build_payment_payload(payment)
            source_event_type = (
                "vendor_payment.credit_card_settled"
                if payment.payment_method == VendorPayment.PaymentMethod.CREDIT_CARD
                else "vendor_payment.sent"
            )
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
        existing = LedgerOSSyncRecord.objects.filter(
            local_object_type="vendor_payment", local_object_id=str(payment.pk), source_event_type=source_event_type,
        ).first()
        if existing and existing.attempt_count and existing.request_hash != TenantPaymentService._sync_record_payload(request_payload):
            raise ValidationError({"payment": "An attempted vendor payment cannot be changed. Reconcile it before retrying."})
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
            if use_payment_endpoint and not LedgerOSPaymentService.is_posted_result(result.payload):
                raise RuntimeError("LedgerOS did not confirm a payment with a posted journal entry.")
        except Exception as exc:
            logger.warning("Vendor payment sync failed", extra={"vendor_payment_id": payment.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            audit_failure(
                action="vendor_payment_post_failed",
                record_type="VendorPayment",
                record_id=str(payment.pk),
                user=actor,
                source="service",
                metadata={"sync_record_id": sync_record.pk, "error": str(exc)},
            )
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
        audit_success(
            action="vendor_payment_posted",
            record=payment,
            user=actor,
            source="service",
            metadata={"sync_record_id": sync_record.pk},
        )
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
