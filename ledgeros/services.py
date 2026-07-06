from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError
from django.db import connection
from django.db import transaction
from django.utils import timezone

from ledgeros.idempotency import build_idempotency_key
from ledgeros.models import (
    LedgerOSConnectionSettings,
    LedgerOSSyncRecord,
    Lease,
    Property,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    Tenant,
    TenantCharge,
)
from ledgeros.signing import sign_api_request, sign_request


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthCheckResult:
    healthy: bool
    source: str
    details: dict[str, Any]
class LocalHealthCheckService:
    @staticmethod
    def check() -> HealthCheckResult:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:  # pragma: no cover - exercised in failure tests
            return HealthCheckResult(
                healthy=False,
                source="local",
                details={"database": "unhealthy", "error": str(exc)},
            )

        return HealthCheckResult(
            healthy=True,
            source="local",
            details={"database": "healthy"},
        )


class LedgerOSHealthCheckService:
    @staticmethod
    def check() -> HealthCheckResult:
        connection_settings = LedgerOSConnectionSettings.load()
        base_url = connection_settings.base_url
        host_header = connection_settings.host_header.strip()
        client_id = connection_settings.client_id
        secret_env_var = connection_settings.hmac_secret_env_var or "LEDGEROS_HMAC_SECRET"
        health_path = connection_settings.health_path
        timeout = connection_settings.timeout_seconds
        api_key = os.environ.get(
            connection_settings.api_key_env_var or "LEDGEROS_API_KEY",
            "",
        )
        secret = os.environ.get(secret_env_var, "")

        missing = []
        if not base_url:
            missing.append("base_url")
        if not client_id:
            missing.append("client_id")
        if not secret:
            missing.append(secret_env_var)

        if missing:
            return HealthCheckResult(
                healthy=False,
                source="ledgeros",
                details={"error": "missing_configuration", "missing": missing},
            )

        body = b""
        path = health_path if health_path.startswith("/") else f"/{health_path}"
        url = f"{base_url.rstrip('/')}{path}"
        timestamp = "1970-01-01T00:00:00Z"
        signed = sign_request(
            method="GET",
            path=path,
            body=body,
            timestamp=timestamp,
            client_id=client_id,
            secret=secret,
        )
        headers = {
            "X-LedgerOS-Client-Id": client_id,
            "X-LedgerOS-Timestamp": timestamp,
            "X-LedgerOS-Signature": signed.signature,
            "X-LedgerOS-Idempotency-Key": build_idempotency_key(
                local_object_type="ledgeros_health_check",
                local_object_id=base_url,
                source_event_type="health_check",
                external_id=path,
            ),
        }
        if host_header:
            headers["Host"] = host_header
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request = Request(url, method="GET", headers=headers)

        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8").strip()
                if response.status != 200:
                    return HealthCheckResult(
                        healthy=False,
                        source="ledgeros",
                        details={
                            "status": "unhealthy",
                            "http_status": response.status,
                            "payload": payload,
                        },
                    )

                try:
                    parsed_payload = json.loads(payload) if payload else None
                except json.JSONDecodeError:
                    parsed_payload = None

                if not isinstance(parsed_payload, dict) or parsed_payload.get("status") not in {
                    "ok",
                    "healthy",
                }:
                    return HealthCheckResult(
                        healthy=False,
                        source="ledgeros",
                        details={
                            "status": "unhealthy",
                            "http_status": response.status,
                            "payload": payload,
                            "error": "unexpected_payload",
                        },
                    )

                return HealthCheckResult(
                    healthy=True,
                    source="ledgeros",
                    details={
                        "status": "healthy",
                        "http_status": response.status,
                        "payload": parsed_payload,
                    },
                )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            return HealthCheckResult(
                healthy=False,
                source="ledgeros",
                details={"status": "unhealthy", "error": str(exc)},
            )


class LedgerOSCustomerSyncService:
    CUSTOMER_PATH = "/api/v1/customers/"

    @staticmethod
    def _format_http_error(exc: HTTPError) -> str:
        body = ""
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
    def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")

    @staticmethod
    def _customer_code_for_property(property_obj: Property) -> str:
        return f"property-{property_obj.pk}"

    @staticmethod
    def _customer_code_for_tenant(tenant: Tenant) -> str:
        return f"tenant-{tenant.pk}"

    @staticmethod
    def _default_ar_account_code() -> str:
        setup = PropertyLedgerSetup.load()
        mapping = setup.account_mappings.filter(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.ACCOUNTS_RECEIVABLE
        ).first()
        if mapping is None or not mapping.ledgeros_account_id.strip():
            raise ValidationError(
                {
                    "accounts_receivable": (
                        "Accounts receivable mapping is required to create LedgerOS customers."
                    )
                }
            )
        return mapping.ledgeros_account_id.strip()

    @staticmethod
    def _build_customer_payload(*, customer_code: str, name: str) -> dict[str, Any]:
        return {
            "customer_code": customer_code,
            "name": name,
            "default_ar_account_code": LedgerOSCustomerSyncService._default_ar_account_code(),
        }

    @staticmethod
    def create_customer(*, customer_code: str, name: str) -> tuple[int, dict[str, Any]]:
        connection_settings = LedgerOSConnectionSettings.load()
        base_url = connection_settings.base_url
        host_header = connection_settings.host_header.strip()
        client_id = connection_settings.client_id
        secret_env_var = connection_settings.hmac_secret_env_var or "LEDGEROS_HMAC_SECRET"
        timeout = connection_settings.timeout_seconds
        api_key = os.environ.get(
            connection_settings.api_key_env_var or "LEDGEROS_API_KEY",
            "",
        )
        secret = os.environ.get(secret_env_var, "")

        missing = []
        if not base_url:
            missing.append("base_url")
        if not client_id:
            missing.append("client_id")
        if not secret:
            missing.append(secret_env_var)
        if missing:
            raise ValidationError(
                {"ledgeros": f"Missing LedgerOS configuration: {', '.join(missing)}"}
            )

        payload = LedgerOSCustomerSyncService._build_customer_payload(
            customer_code=customer_code,
            name=name,
        )
        body = LedgerOSCustomerSyncService._canonical_json_bytes(payload)
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        signed = sign_api_request(
            method="POST",
            path=LedgerOSCustomerSyncService.CUSTOMER_PATH,
            body=body,
            timestamp=timestamp,
            nonce=nonce,
            client_id=client_id,
            secret=secret,
        )
        url = f"{base_url.rstrip('/')}{LedgerOSCustomerSyncService.CUSTOMER_PATH}"
        headers = {
            "Content-Type": "application/json",
            "X-LedgerOS-Client-Id": client_id,
            "X-LedgerOS-Timestamp": timestamp,
            "X-LedgerOS-Nonce": nonce,
            "X-LedgerOS-Signature": signed.signature,
            "Idempotency-Key": build_idempotency_key(
                local_object_type="customer",
                local_object_id=customer_code,
                source_event_type="customer.upsert_requested",
                external_id=customer_code,
                request_body=payload,
            ),
        }
        if host_header:
            headers["Host"] = host_header
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request = Request(url, data=body, method="POST", headers=headers)

        try:
            with urlopen(request, timeout=timeout) as response:
                response_payload_raw = response.read().decode("utf-8").strip()
                if response.status not in {200, 201}:
                    raise RuntimeError(
                        f"LedgerOS returned HTTP {response.status}: {response_payload_raw}"
                    )
                try:
                    response_payload = (
                        json.loads(response_payload_raw) if response_payload_raw else {}
                    )
                except json.JSONDecodeError as exc:
                    raise RuntimeError("LedgerOS customer response was not valid JSON.") from exc
                if not isinstance(response_payload, dict):
                    raise RuntimeError("LedgerOS customer response must be a JSON object.")
                return response.status, response_payload
        except HTTPError as exc:
            raise RuntimeError(LedgerOSCustomerSyncService._format_http_error(exc)) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc


class LedgerOSInvoiceSyncService:
    INVOICE_PATH = "/api/v1/invoices/"

    @staticmethod
    def _format_http_error(exc: HTTPError) -> str:
        body = ""
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
    def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")

    @staticmethod
    def _customer_code_for_charge(charge: TenantCharge) -> str:
        if charge.tenant_id:
            return f"tenant-{charge.tenant_id}"
        return f"property-{charge.property_id}"

    @staticmethod
    def _rental_income_account_code() -> str:
        setup = PropertyLedgerSetup.load()
        mapping = setup.account_mappings.filter(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.RENTAL_INCOME
        ).first()
        if mapping is None or not mapping.ledgeros_account_id.strip():
            raise ValidationError(
                {
                    "rental_income": (
                        "Rental income account mapping is required to sync tenant charges."
                    )
                }
            )
        return mapping.ledgeros_account_id.strip()

    @staticmethod
    def _build_invoice_payload(
        *,
        charge: TenantCharge,
        external_invoice_number: str,
    ) -> dict[str, Any]:
        line_description = charge.description.strip() or charge.get_charge_type_display()
        return {
            "customer_code": LedgerOSInvoiceSyncService._customer_code_for_charge(charge),
            "external_invoice_number": external_invoice_number,
            "invoice_date": charge.charge_date.isoformat(),
            "due_date": charge.due_date.isoformat(),
            "total_amount": str(charge.amount.quantize(Decimal("0.01"))),
            "lines": [
                {
                    "account_code": LedgerOSInvoiceSyncService._rental_income_account_code(),
                    "line_description": line_description,
                    "amount": str(charge.amount.quantize(Decimal("0.01"))),
                }
            ],
        }

    @staticmethod
    def submit_tenant_charge(
        *,
        charge: TenantCharge,
        sync_record: LedgerOSSyncRecord,
    ) -> tuple[int, dict[str, Any]]:
        connection_settings = LedgerOSConnectionSettings.load()
        base_url = connection_settings.base_url
        host_header = connection_settings.host_header.strip()
        client_id = connection_settings.client_id
        secret_env_var = connection_settings.hmac_secret_env_var or "LEDGEROS_HMAC_SECRET"
        timeout = connection_settings.timeout_seconds
        api_key = os.environ.get(
            connection_settings.api_key_env_var or "LEDGEROS_API_KEY",
            "",
        )
        secret = os.environ.get(secret_env_var, "")

        missing = []
        if not base_url:
            missing.append("base_url")
        if not client_id:
            missing.append("client_id")
        if not secret:
            missing.append(secret_env_var)
        if missing:
            raise ValidationError(
                {"ledgeros": f"Missing LedgerOS configuration: {', '.join(missing)}"}
            )

        payload = LedgerOSInvoiceSyncService._build_invoice_payload(
            charge=charge,
            external_invoice_number=sync_record.external_id,
        )
        body = LedgerOSInvoiceSyncService._canonical_json_bytes(payload)
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        signed = sign_api_request(
            method="POST",
            path=LedgerOSInvoiceSyncService.INVOICE_PATH,
            body=body,
            timestamp=timestamp,
            nonce=nonce,
            client_id=client_id,
            secret=secret,
        )
        url = f"{base_url.rstrip('/')}{LedgerOSInvoiceSyncService.INVOICE_PATH}"
        headers = {
            "Content-Type": "application/json",
            "X-LedgerOS-Client-Id": client_id,
            "X-LedgerOS-Timestamp": timestamp,
            "X-LedgerOS-Nonce": nonce,
            "X-LedgerOS-Signature": signed.signature,
            "Idempotency-Key": sync_record.idempotency_key,
        }
        if host_header:
            headers["Host"] = host_header
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request = Request(url, data=body, method="POST", headers=headers)

        try:
            with urlopen(request, timeout=timeout) as response:
                response_payload_raw = response.read().decode("utf-8").strip()
                if response.status not in {200, 201}:
                    raise RuntimeError(
                        f"LedgerOS returned HTTP {response.status}: {response_payload_raw}"
                    )
                try:
                    response_payload = (
                        json.loads(response_payload_raw) if response_payload_raw else {}
                    )
                except json.JSONDecodeError as exc:
                    raise RuntimeError("LedgerOS invoice response was not valid JSON.") from exc
                if not isinstance(response_payload, dict):
                    raise RuntimeError("LedgerOS invoice response must be a JSON object.")
                return response.status, response_payload
        except HTTPError as exc:
            raise RuntimeError(LedgerOSInvoiceSyncService._format_http_error(exc)) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc


class TenantChargeService:
    @staticmethod
    def month_bounds(for_date: date) -> tuple[date, date]:
        month_start = for_date.replace(day=1)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        month_end = next_month - timedelta(days=1)
        return month_start, month_end

    @staticmethod
    def generate_base_rent_for_month(for_date: date) -> list[TenantCharge]:
        month_start, month_end = TenantChargeService.month_bounds(for_date)
        charges: list[TenantCharge] = []

        active_leases = Lease.objects.filter(status=Lease.Status.ACTIVE).select_related(
            "unit__property", "tenant"
        )
        for lease in active_leases:
            lease_end = lease.lease_end_date or month_end
            if lease.lease_start_date > month_end or lease_end < month_start:
                continue

            amount = TenantCharge.prorated_amount_for_period(
                monthly_amount=lease.base_monthly_rent_amount,
                period_start=month_start,
                period_end=month_end,
                occupied_start=lease.lease_start_date,
                occupied_end=lease_end,
            )

            charge, created = TenantCharge.objects.get_or_create(
                lease=lease,
                charge_type=TenantCharge.ChargeType.BASE_RENT,
                billing_period_start=month_start,
                billing_period_end=month_end,
                defaults={
                    "property": lease.unit.property,
                    "unit": lease.unit,
                    "tenant": lease.tenant,
                    "charge_date": month_start,
                    "due_date": month_end,
                    "amount": amount,
                    "description": (
                        f"Base rent for {month_start:%B %Y}"
                    ),
                    "status": TenantCharge.Status.DRAFT,
                },
            )
            if created:
                charges.append(charge)
        return charges

    @staticmethod
    @transaction.atomic
    def approve_charge(charge: TenantCharge) -> TenantCharge:
        charge.status = TenantCharge.Status.APPROVED
        charge.full_clean()
        charge.save()

        if charge.sync_record is None:
            request_payload = TenantChargeService._build_sync_request_payload(charge)
            sync_record = LedgerOSSyncRecord.objects.create(
                local_object_type="tenant_charge",
                local_object_id=str(charge.pk),
                ledgeros_resource_type="invoice",
                source_event_type="tenant_charge.invoice_created",
                external_id=f"tenant-charge:{charge.pk}",
                idempotency_key=build_idempotency_key(
                    local_object_type="tenant_charge",
                    local_object_id=str(charge.pk),
                    source_event_type="invoice_created",
                    external_id=f"tenant-charge:{charge.pk}",
                    request_body=request_payload,
                ),
                request_hash=hashlib.sha256(
                    json.dumps(
                        request_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode("utf-8")
                ).hexdigest(),
                status=LedgerOSSyncRecord.Status.PENDING,
            )
            charge.sync_record = sync_record

        sync_record = charge.sync_record
        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(
            update_fields=["status", "attempt_count", "last_error", "updated_at"]
        )

        charge.save(update_fields=["sync_record", "updated_at"])

        try:
            _, response_payload = LedgerOSInvoiceSyncService.submit_tenant_charge(
                charge=charge,
                sync_record=sync_record,
            )
        except Exception as exc:
            logger.warning(
                "Tenant charge sync failed",
                extra={
                    "tenant_charge_id": charge.pk,
                    "property_id": charge.property_id,
                    "tenant_id": charge.tenant_id,
                    "lease_id": charge.lease_id,
                    "error": str(exc),
                },
            )
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {
                "status": "failed",
                "error": str(exc),
            }
            sync_record.save(
                update_fields=[
                    "status",
                    "last_error",
                    "response_payload",
                    "updated_at",
                ]
            )
            return charge

        invoice_payload = response_payload.get("invoice")
        if not isinstance(invoice_payload, dict):
            invoice_payload = response_payload
        journal_entry_payload = response_payload.get("journal_entry")
        if not isinstance(journal_entry_payload, dict):
            journal_entry_payload = {}

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            invoice_payload.get("id")
            or invoice_payload.get("invoice_id")
            or invoice_payload.get("invoice_number")
            or sync_record.external_id
        )
        sync_record.ledgeros_journal_entry_id = str(
            journal_entry_payload.get("id")
            or response_payload.get("journal_entry_id")
            or ""
        ) or None
        sync_record.response_payload = response_payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(
            update_fields=[
                "status",
                "ledgeros_resource_id",
                "ledgeros_journal_entry_id",
                "response_payload",
                "last_synced_at",
                "updated_at",
            ]
        )
        return charge

    @staticmethod
    def _build_sync_request_payload(charge: TenantCharge) -> dict[str, Any]:
        return {
            "local_object_type": "tenant_charge",
            "local_object_id": str(charge.pk),
            "charge_type": charge.charge_type,
            "property_id": charge.property_id,
            "unit_id": charge.unit_id,
            "tenant_id": charge.tenant_id,
            "lease_id": charge.lease_id,
            "billing_period_start": (
                charge.billing_period_start.isoformat()
                if charge.billing_period_start
                else None
            ),
            "billing_period_end": (
                charge.billing_period_end.isoformat()
                if charge.billing_period_end
                else None
            ),
            "amount": str(charge.amount),
            "description": charge.description,
            "due_date": charge.due_date.isoformat(),
        }
