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
from ledgeros.models import LedgerOSConnectionSettings, LedgerOSSyncRecord, PropertyLedgerAccountMapping, PropertyLedgerSetup, TenantCharge, Lease
from ledgeros.signing import sign_api_request
from payments.models import PaymentWorkflowSettings, SecurityDepositEvent, TenantPayment, TenantPaymentApplication


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    status_code: int
    payload: dict[str, Any]


class LedgerOSPaymentsSyncService:
    PAYMENT_PATH = "/api/v1/payments/"
    PAYMENT_APPLICATION_PATH = "/api/v1/payment-applications/"
    SECURITY_DEPOSIT_EVENT_PATH = "/api/v1/security-deposit-events/"

    @staticmethod
    def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")

    @staticmethod
    def _format_http_error(exc: HTTPError) -> str:
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
                return f"LedgerOS returned HTTP {exc.code}: {body}"
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
        base_url, host_header, client_id, secret, timeout, api_key = LedgerOSPaymentsSyncService._connection_values()
        body = LedgerOSPaymentsSyncService._canonical_json_bytes(payload)
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
            raise RuntimeError(LedgerOSPaymentsSyncService._format_http_error(exc)) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc


class TenantPaymentService:
    @staticmethod
    def _payment_request_payload(payment: TenantPayment) -> dict[str, Any]:
        return {
            "customer_code": f"tenant-{payment.tenant_id}",
            "external_payment_number": f"tenant-payment:{payment.pk}",
            "payment_date": payment.payment_date.isoformat(),
            "total_amount": str(payment.amount.quantize(Decimal("0.01"))),
            "payment_method": payment.payment_method,
            "reference": payment.reference,
            "applications": [
                {
                    "application_external_id": f"tenant-payment-application:{application.pk}",
                    "charge_external_id": f"tenant-charge:{application.charge_id}",
                    "amount": str(application.amount_applied.quantize(Decimal("0.01"))),
                }
                for application in payment.applications.select_related("charge").order_by("charge__due_date", "charge__charge_date", "id")
            ],
        }

    @staticmethod
    def _application_request_payload(application: TenantPaymentApplication) -> dict[str, Any]:
        return {
            "external_application_number": f"tenant-payment-application:{application.pk}",
            "external_payment_number": f"tenant-payment:{application.payment_id}",
            "external_charge_number": f"tenant-charge:{application.charge_id}",
            "applied_amount": str(application.amount_applied.quantize(Decimal("0.01"))),
        }

    @staticmethod
    def _deposit_request_payload(event: SecurityDepositEvent) -> dict[str, Any]:
        return {
            "customer_code": f"tenant-{event.tenant_id}",
            "external_deposit_event_number": f"security-deposit:{event.pk}",
            "event_type": event.event_type,
            "event_date": event.event_date.isoformat(),
            "total_amount": str(event.amount.quantize(Decimal("0.01"))),
            "description": event.description,
        }

    @staticmethod
    def _sync_record_payload(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _build_sync_record(*, local_object_type: str, local_object_id: str, ledgeros_resource_type: str, source_event_type: str, external_id: str, request_payload: dict[str, Any]) -> LedgerOSSyncRecord:
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
        if not sync_record.ledgeros_resource_type:
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
    def allocate_payment(payment: TenantPayment) -> TenantPayment:
        if payment.status in {
            TenantPayment.Status.SYNC_PENDING,
            TenantPayment.Status.SYNCED,
        }:
            raise ValidationError({"payment": "Synced payments cannot be reallocated."})

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
        open_charges.sort(key=lambda charge: TenantPaymentService._charge_sort_key(charge, priority_index))

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
            payment.status = TenantPayment.Status.SYNC_FAILED
        elif remaining == Decimal("0.00") and all_allocations_synced:
            payment.status = TenantPayment.Status.READY_TO_SYNC
        else:
            payment.status = TenantPayment.Status.ALLOCATED
        payment.save(update_fields=["status", "updated_at"])
        return payment

    @staticmethod
    @transaction.atomic
    def sync_payment_application(application: TenantPaymentApplication) -> TenantPaymentApplication:
        request_payload = TenantPaymentService._application_request_payload(application)
        sync_record = TenantPaymentService._build_sync_record(
            local_object_type="tenant_payment_application",
            local_object_id=str(application.pk),
            ledgeros_resource_type="payment_application",
            source_event_type="tenant_payment.application_applied",
            external_id=f"tenant-payment-application:{application.pk}",
            request_payload=request_payload,
        )
        application.sync_record = sync_record
        application.save(update_fields=["sync_record", "updated_at"])

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])

        try:
            result = LedgerOSPaymentsSyncService._submit(
                method="POST",
                path=LedgerOSPaymentsSyncService.PAYMENT_APPLICATION_PATH,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Tenant payment application sync failed", extra={"payment_application_id": application.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return application

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("payment_application", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "response_payload", "last_synced_at", "updated_at"])
        return application

    @staticmethod
    @transaction.atomic
    def sync_payment(payment: TenantPayment) -> TenantPayment:
        if payment.remaining_amount != Decimal("0.00"):
            raise ValidationError({"payment": "Payment must be fully allocated before sync."})
        pending_applications = payment.applications.filter(
            models.Q(sync_record__isnull=True) | ~models.Q(sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED)
        )
        if pending_applications.exists():
            raise ValidationError({"payment": "All payment allocations must sync successfully before the payment can sync."})

        request_payload = TenantPaymentService._payment_request_payload(payment)
        sync_record = TenantPaymentService._build_sync_record(
            local_object_type="tenant_payment",
            local_object_id=str(payment.pk),
            ledgeros_resource_type="payment",
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
        payment.status = TenantPayment.Status.SYNC_PENDING
        payment.save(update_fields=["status", "updated_at"])

        try:
            result = LedgerOSPaymentsSyncService._submit(
                method="POST",
                path=LedgerOSPaymentsSyncService.PAYMENT_PATH,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Tenant payment sync failed", extra={"payment_id": payment.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            payment.status = TenantPayment.Status.SYNC_FAILED
            payment.save(update_fields=["status", "updated_at"])
            return payment

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("payment", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "response_payload", "last_synced_at", "updated_at"])
        payment.status = TenantPayment.Status.SYNCED
        payment.save(update_fields=["status", "updated_at"])
        return payment

    @staticmethod
    @transaction.atomic
    def sync_security_deposit_event(event: SecurityDepositEvent) -> SecurityDepositEvent:
        request_payload = TenantPaymentService._deposit_request_payload(event)
        sync_record = TenantPaymentService._build_sync_record(
            local_object_type="security_deposit_event",
            local_object_id=str(event.pk),
            ledgeros_resource_type="security_deposit_event",
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
        event.status = SecurityDepositEvent.Status.SYNC_PENDING
        event.save(update_fields=["status", "updated_at"])

        try:
            result = LedgerOSPaymentsSyncService._submit(
                method="POST",
                path=LedgerOSPaymentsSyncService.SECURITY_DEPOSIT_EVENT_PATH,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Security deposit event sync failed", extra={"security_deposit_event_id": event.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            event.status = SecurityDepositEvent.Status.SYNC_FAILED
            event.save(update_fields=["status", "updated_at"])
            return event

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("security_deposit_event", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "response_payload", "last_synced_at", "updated_at"])
        event.status = SecurityDepositEvent.Status.SYNCED
        event.save(update_fields=["status", "updated_at"])
        return event

    @staticmethod
    def allocate_payment_and_sync_applications(payment: TenantPayment) -> TenantPayment:
        payment = TenantPaymentService.allocate_payment(payment)
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
