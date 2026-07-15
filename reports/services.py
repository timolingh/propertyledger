from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from urllib.parse import urlencode
from dataclasses import dataclass
from datetime import date, timedelta
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
    Lease,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    TenantCharge,
)
from ledgeros.signing import sign_request
from payments.models import SecurityDepositEvent, TenantPayment, VendorBill
from payments.models import TenantPaymentApplication
from reports.models import OwnerContributionDistribution


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    payload: dict[str, Any]


class LedgerOSSyncEventService:
    SYNC_EVENT_PATH = "/api/v1/sync-events/"

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
    def _submit(*, method: str, path: str, payload: dict[str, Any], idempotency_key: str) -> SyncResult:
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

        if not base_url or not client_id or not secret:
            raise ValidationError(
                {
                    "ledgeros": "LedgerOS connection settings and secret must be configured before syncing reports."
                }
            )

        body = LedgerOSSyncEventService._canonical_json_bytes(payload)
        timestamp = timezone.now().replace(microsecond=0).isoformat().replace("+00:00", "Z")
        signed = sign_request(
            method=method,
            path=path,
            body=body,
            timestamp=timestamp,
            client_id=client_id,
            secret=secret,
        )
        headers = {
            "Content-Type": "application/json",
            "X-LedgerOS-Client-Id": client_id,
            "X-LedgerOS-Timestamp": timestamp,
            "X-LedgerOS-Nonce": idempotency_key,
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
                response_body = response.read().decode("utf-8").strip()
                try:
                    payload_data = json.loads(response_body) if response_body else {}
                except json.JSONDecodeError:
                    payload_data = {"raw": response_body}
                return SyncResult(payload=payload_data)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc


class OwnerActivityService:
    @staticmethod
    def _account_code(mapping_key: str, field_name: str) -> str:
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
    def _payload_hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _accounting_entries(activity: OwnerContributionDistribution) -> list[dict[str, str]]:
        amount = str(activity.amount.quantize(Decimal("0.01")))
        if activity.event_type == OwnerContributionDistribution.EventType.CONTRIBUTION:
            return [
                {
                    "account_code": OwnerActivityService._account_code(
                        PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
                        "payment_account_name",
                    ),
                    "direction": "debit",
                    "amount": amount,
                },
                {
                    "account_code": OwnerActivityService._account_code(
                        PropertyLedgerAccountMapping.MappingKey.OWNER_CONTRIBUTIONS_EQUITY,
                        "owner",
                    ),
                    "direction": "credit",
                    "amount": amount,
                },
            ]

        return [
            {
                "account_code": OwnerActivityService._account_code(
                    PropertyLedgerAccountMapping.MappingKey.OWNER_DISTRIBUTIONS_EQUITY,
                    "owner",
                ),
                "direction": "debit",
                "amount": amount,
            },
            {
                "account_code": OwnerActivityService._account_code(
                    PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT,
                    "payment_account_name",
                ),
                "direction": "credit",
                "amount": amount,
            },
        ]

    @staticmethod
    def _build_sync_payload(activity: OwnerContributionDistribution) -> dict[str, Any]:
        return {
            "source_system": "propertyledger",
            "domain_event_type": f"owner_activity.{activity.event_type}",
            "external_id": f"owner-activity:{activity.pk}",
            "source_object_type": "owner_contribution_distribution",
            "source_object_id": str(activity.pk),
            "occurred_at": activity.created_at.isoformat(),
            "payload": {
                "owner_id": activity.owner_id,
                "property_id": activity.property_id,
                "event_type": activity.event_type,
                "event_date": activity.event_date.isoformat(),
                "amount": str(activity.amount.quantize(Decimal("0.01"))),
                "payment_account_name": activity.payment_account_name,
                "description": activity.description,
                "notes": activity.notes,
                "accounting_entries": OwnerActivityService._accounting_entries(activity),
            },
        }

    @staticmethod
    def _build_sync_record(activity: OwnerContributionDistribution, request_payload: dict[str, Any]) -> LedgerOSSyncRecord:
        sync_record, _ = LedgerOSSyncRecord.objects.get_or_create(
            local_object_type="owner_contribution_distribution",
            local_object_id=str(activity.pk),
            source_event_type=f"owner_activity.{activity.event_type}",
            defaults={
                "ledgeros_resource_type": "sync_event",
                "external_id": f"owner-activity:{activity.pk}",
                "idempotency_key": build_idempotency_key(
                    local_object_type="owner_contribution_distribution",
                    local_object_id=str(activity.pk),
                    source_event_type=f"owner_activity.{activity.event_type}",
                    external_id=f"owner-activity:{activity.pk}",
                    request_body=request_payload,
                ),
                "request_hash": OwnerActivityService._payload_hash(request_payload),
                "status": LedgerOSSyncRecord.Status.PENDING,
            },
        )
        sync_record.ledgeros_resource_type = "sync_event"
        sync_record.external_id = f"owner-activity:{activity.pk}"
        sync_record.idempotency_key = build_idempotency_key(
            local_object_type="owner_contribution_distribution",
            local_object_id=str(activity.pk),
            source_event_type=f"owner_activity.{activity.event_type}",
            external_id=f"owner-activity:{activity.pk}",
            request_body=request_payload,
        )
        sync_record.request_hash = OwnerActivityService._payload_hash(request_payload)
        sync_record.save()
        return sync_record

    @staticmethod
    @transaction.atomic
    def sync_activity(activity: OwnerContributionDistribution) -> OwnerContributionDistribution:
        request_payload = OwnerActivityService._build_sync_payload(activity)
        sync_record = OwnerActivityService._build_sync_record(activity, request_payload)
        activity.sync_record = sync_record
        activity.save(update_fields=["sync_record", "updated_at"])

        sync_record.status = LedgerOSSyncRecord.Status.IN_PROGRESS
        sync_record.attempt_count += 1
        sync_record.last_error = None
        sync_record.save(update_fields=["status", "attempt_count", "last_error", "updated_at"])
        activity.status = OwnerContributionDistribution.Status.READY_TO_SYNC
        activity.save(update_fields=["status", "updated_at"])

        try:
            result = LedgerOSSyncEventService._submit(
                method="POST",
                path=LedgerOSSyncEventService.SYNC_EVENT_PATH,
                payload=request_payload,
                idempotency_key=sync_record.idempotency_key,
            )
        except Exception as exc:
            logger.warning("Owner activity sync failed", extra={"owner_activity_id": activity.pk, "error": str(exc)})
            sync_record.status = LedgerOSSyncRecord.Status.FAILED
            sync_record.last_error = str(exc)
            sync_record.response_payload = {"status": "failed", "error": str(exc)}
            sync_record.save(update_fields=["status", "last_error", "response_payload", "updated_at"])
            return activity

        sync_record.status = LedgerOSSyncRecord.Status.SUCCEEDED
        sync_record.ledgeros_resource_id = str(
            result.payload.get("sync_event", {}).get("id")
            or result.payload.get("id")
            or sync_record.external_id
        )
        sync_record.response_payload = result.payload
        sync_record.last_synced_at = timezone.now()
        sync_record.save(update_fields=["status", "ledgeros_resource_id", "response_payload", "last_synced_at", "updated_at"])
        activity.status = OwnerContributionDistribution.Status.POSTED
        activity.save(update_fields=["status", "updated_at"])
        return activity


def statement_period_bounds(*, period_type: str, anchor_date: date, end_date: date | None = None) -> tuple[date, date]:
    if period_type == "custom":
        if end_date is None:
            raise ValidationError({"period_end": "End date is required for a custom statement period."})
        return anchor_date, end_date

    if period_type == "month":
        start = anchor_date.replace(day=1)
        if anchor_date.month == 12:
            end = date(anchor_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(anchor_date.year, anchor_date.month + 1, 1) - timedelta(days=1)
        return start, end

    if period_type == "quarter":
        quarter_start_month = ((anchor_date.month - 1) // 3) * 3 + 1
        start = date(anchor_date.year, quarter_start_month, 1)
        if quarter_start_month == 10:
            end = date(anchor_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(anchor_date.year, quarter_start_month + 3, 1) - timedelta(days=1)
        return start, end

    if period_type == "year":
        start = date(anchor_date.year, 1, 1)
        end = date(anchor_date.year + 1, 1, 1) - timedelta(days=1)
        return start, end

    raise ValidationError({"period_type": "Unsupported statement period type."})


class OwnerStatementService:
    @staticmethod
    def build_statement(*, owner, property_obj, period_type: str, period_start: date, period_end: date | None = None) -> dict[str, Any]:
        start_date, end_date = statement_period_bounds(
            period_type=period_type,
            anchor_date=period_start,
            end_date=period_end,
        )
        rent_charges = list(
            TenantCharge.objects.filter(
                property=property_obj,
                sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
                charge_type=TenantCharge.ChargeType.BASE_RENT,
                charge_date__range=(start_date, end_date),
            ).select_related("tenant", "lease")
        )
        payments = list(
            TenantPayment.objects.filter(
                property=property_obj,
                sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
                payment_date__range=(start_date, end_date),
            )
        )
        bills = list(
            VendorBill.objects.filter(
                property=property_obj,
                sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
                bill_date__range=(start_date, end_date),
            )
        )
        owner_activities = list(
            OwnerContributionDistribution.objects.filter(
                owner=owner,
                property=property_obj,
                sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
                event_date__range=(start_date, end_date),
            )
        )
        deposit_events = list(
            SecurityDepositEvent.objects.filter(
                property=property_obj,
                sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
                event_date__range=(start_date, end_date),
            )
        )

        rent_charged = sum((charge.amount for charge in rent_charges), Decimal("0.00")).quantize(Decimal("0.01"))
        rent_collected = sum((payment.amount for payment in payments), Decimal("0.00")).quantize(Decimal("0.01"))
        maintenance_expenses = sum(
            (
                bill.amount
                for bill in bills
                if bill.expense_category == VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE
                or bill.maintenance_category_id
            ),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        management_fee_expenses = sum(
            (bill.amount for bill in bills if bill.expense_category == VendorBill.ExpenseCategory.MANAGEMENT_FEE),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        property_expenses = sum(
            (
                bill.amount
                for bill in bills
                if bill.expense_category not in {
                    VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
                    VendorBill.ExpenseCategory.MANAGEMENT_FEE,
                }
            ),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        contributions = sum(
            (activity.amount for activity in owner_activities if activity.event_type == OwnerContributionDistribution.EventType.CONTRIBUTION),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        distributions = sum(
            (activity.amount for activity in owner_activities if activity.event_type == OwnerContributionDistribution.EventType.DISTRIBUTION),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        deposit_received = sum(
            (event.amount for event in deposit_events if event.event_type == SecurityDepositEvent.EventType.RECEIVED),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        deposit_deducted = sum(
            (event.amount for event in deposit_events if event.event_type == SecurityDepositEvent.EventType.DEDUCTED),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        deposit_refunded = sum(
            (event.amount for event in deposit_events if event.event_type == SecurityDepositEvent.EventType.REFUNDED),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))

        net_summary = (
            rent_collected
            - property_expenses
            - maintenance_expenses
            - management_fee_expenses
            + contributions
            - distributions
        ).quantize(Decimal("0.01"))

        return {
            "owner": owner,
            "property": property_obj,
            "period_type": period_type,
            "period_start": start_date,
            "period_end": end_date,
            "rent_charges": rent_charges,
            "payments": payments,
            "bills": bills,
            "owner_activities": owner_activities,
            "deposit_events": deposit_events,
            "rent_charged": rent_charged,
            "rent_collected": rent_collected,
            "property_expenses": property_expenses,
            "maintenance_expenses": maintenance_expenses,
            "management_fee_expenses": management_fee_expenses,
            "contributions": contributions,
            "distributions": distributions,
            "deposit_received": deposit_received,
            "deposit_deducted": deposit_deducted,
            "deposit_refunded": deposit_refunded,
            "net_summary": net_summary,
        }

    @staticmethod
    def pending_sync_items(*, owner, property_obj) -> dict[str, Any]:
        owner_activity_items = OwnerContributionDistribution.objects.filter(
            owner=owner,
            property=property_obj,
        ).exclude(sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED)
        management_fee_bills = VendorBill.objects.filter(
            property=property_obj,
            expense_category=VendorBill.ExpenseCategory.MANAGEMENT_FEE,
        ).exclude(sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED)
        return {
            "owner_activity_items": owner_activity_items,
            "management_fee_bills": management_fee_bills,
        }


class LedgerOSReportReadService:
    REPORT_PATHS = {
        "chart_of_accounts": "/api/v1/chart-of-accounts/",
        "trial_balance": "/api/v1/trial-balance/",
        "profit_and_loss": "/api/v1/profit-and-loss/",
        "balance_sheet": "/api/v1/balance-sheet/",
        "period_summary": "/api/v1/period-summary/",
        "tax_summary": "/api/v1/tax-summary/",
        "invoice_status": "/api/v1/invoices/",
        "bill_status": "/api/v1/bills/",
        "payment_status": "/api/v1/payments/",
        "bank_balances": "/api/v1/bank-accounts/",
        "reconciliation_status": "/api/v1/bank-reconciliations/",
        "audit_drilldown": "/api/v1/audit-drill-down/",
    }

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
    def _canonical_json_bytes(payload: bytes = b"") -> bytes:
        return payload

    @staticmethod
    def _request_json(*, path: str, query_params: dict[str, Any] | None = None) -> Any:
        base_url, host_header, client_id, secret, timeout, api_key = LedgerOSReportReadService._connection_values()
        if query_params:
            cleaned_params = {
                key: value
                for key, value in query_params.items()
                if value not in {None, ""}
            }
            if cleaned_params:
                separator = "&" if "?" in path else "?"
                path = f"{path}{separator}{urlencode(cleaned_params)}"

        body = LedgerOSReportReadService._canonical_json_bytes()
        timestamp = str(int(time.time()))
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
                    raise RuntimeError(f"LedgerOS returned HTTP {response.status} for GET {path}: {response_raw}")
                if not response_raw:
                    return []
                try:
                    response_payload = json.loads(response_raw)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("LedgerOS report response was not valid JSON.") from exc
                return response_payload
        except HTTPError as exc:
            try:
                raw_body = exc.read()
            except Exception:
                raw_body = b""
            if raw_body:
                try:
                    body_text = raw_body.decode("utf-8").strip()
                except Exception:
                    body_text = raw_body.decode("utf-8", errors="replace").strip()
                if body_text:
                    raise RuntimeError(f"LedgerOS returned HTTP {exc.code} for GET {path}: {body_text}") from exc
            raise RuntimeError(f"LedgerOS returned HTTP {exc.code} for GET {path}: {exc.reason}") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    def fetch_report(report_key: str, *, query_params: dict[str, Any] | None = None) -> Any:
        path = LedgerOSReportReadService.REPORT_PATHS.get(report_key)
        if path is None:
            raise ValidationError({"report": f"Unsupported LedgerOS report: {report_key}"})
        return LedgerOSReportReadService._request_json(path=path, query_params=query_params)


def _quantize(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _rows_from_dicts(dict_rows: list[dict[str, Any]], columns: list[str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in dict_rows:
        rows.append([row.get(column, "") for column in columns])
    return rows


class PropertyReportService:
    @staticmethod
    def rent_roll(*, property_obj=None, as_of_date: date | None = None) -> dict[str, Any]:
        if as_of_date is None:
            as_of_date = timezone.localdate()
        leases = Lease.objects.select_related("unit__property", "tenant")
        if property_obj is not None:
            leases = leases.filter(unit__property=property_obj)
        leases = leases.exclude(status=Lease.Status.CANCELLED).filter(
            lease_start_date__lte=as_of_date
        ).filter(models.Q(lease_end_date__isnull=True) | models.Q(lease_end_date__gte=as_of_date))

        rows: list[list[Any]] = []
        total_rent = Decimal("0.00")
        total_deposit = Decimal("0.00")
        for lease in leases:
            total_rent += _quantize(lease.base_monthly_rent_amount)
            total_deposit += _quantize(lease.deposit_required_amount)
            rows.append(
                [
                    lease.unit.property.name,
                    lease.unit.name,
                    lease.tenant.name,
                    lease.lease_start_date,
                    lease.lease_end_date or "-",
                    lease.status,
                    _quantize(lease.base_monthly_rent_amount),
                    _quantize(lease.deposit_required_amount),
                ]
            )

        return {
            "summary_items": [
                ("As of", as_of_date),
                ("Active leases", leases.count()),
                ("Total monthly rent", total_rent),
                ("Total deposit required", total_deposit),
            ],
            "sections": [
                {
                    "title": "Active leases",
                    "summary": "Lease-based rent roll as of the selected date.",
                    "columns": [
                        "Property",
                        "Unit",
                        "Tenant",
                        "Lease start",
                        "Lease end",
                        "Status",
                        "Base rent",
                        "Deposit required",
                    ],
                    "rows": rows,
                    "empty_message": "No active leases matched the selected filters.",
                }
            ],
        }

    @staticmethod
    def tenant_ledger(*, property_obj=None, tenant=None, period_start: date | None = None, period_end: date | None = None) -> dict[str, Any]:
        if period_start is None:
            period_start = timezone.localdate().replace(day=1)
        if period_end is None:
            period_end = timezone.localdate()

        charges = TenantCharge.objects.select_related("tenant", "property").filter(
            sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
            charge_date__lte=period_end,
        ).exclude(status=TenantCharge.Status.VOIDED)
        payments = TenantPayment.objects.select_related("tenant", "property").filter(
            sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
            payment_date__lte=period_end,
        ).exclude(status=TenantPayment.Status.VOIDED)
        if property_obj is not None:
            charges = charges.filter(property=property_obj)
            payments = payments.filter(property=property_obj)
        if tenant is not None:
            charges = charges.filter(tenant=tenant)
            payments = payments.filter(tenant=tenant)

        opening_balance = sum(
            (_quantize(charge.amount) for charge in charges.filter(charge_date__lt=period_start)),
            Decimal("0.00"),
        ) - sum((_quantize(payment.amount) for payment in payments.filter(payment_date__lt=period_start)), Decimal("0.00"))

        entries: list[dict[str, Any]] = []
        running_balance = opening_balance
        for charge in charges.filter(charge_date__range=(period_start, period_end)):
            running_balance += _quantize(charge.amount)
            entries.append(
                {
                    "date": charge.charge_date,
                    "type": "Charge",
                    "reference": charge.description or charge.get_charge_type_display(),
                    "tenant": charge.tenant.name if charge.tenant_id else "-",
                    "property": charge.property.name,
                    "amount": _quantize(charge.amount),
                    "running_balance": running_balance,
                    "status": charge.get_status_display(),
                }
            )

        for payment in payments.filter(payment_date__range=(period_start, period_end)):
            payment_amount = _quantize(payment.amount)
            running_balance -= payment_amount
            entries.append(
                {
                    "date": payment.payment_date,
                    "type": "Payment",
                    "reference": payment.reference or payment.payment_method,
                    "tenant": payment.tenant.name,
                    "property": payment.property.name,
                    "amount": -payment_amount,
                    "running_balance": running_balance,
                    "status": payment.get_status_display(),
                }
            )

        entries.sort(key=lambda item: (item["date"], item["type"], item["reference"]))

        closing_balance = running_balance

        return {
            "summary_items": [
                ("Period start", period_start),
                ("Period end", period_end),
                ("Opening balance", opening_balance),
                ("Closing balance", closing_balance),
            ],
            "sections": [
                {
                    "title": "Tenant ledger entries",
                    "summary": "Synced charges and payments within the selected period.",
                    "columns": ["Date", "Type", "Reference", "Tenant", "Property", "Amount", "Running balance", "Status"],
                    "rows": [
                        [
                            row["date"],
                            row["type"],
                            row["reference"],
                            row["tenant"],
                            row["property"],
                            row["amount"],
                            row["running_balance"],
                            row["status"],
                        ]
                        for row in entries
                    ],
                    "empty_message": "No synced charges or payments matched the selected filters.",
                }
            ],
        }

    @staticmethod
    def delinquency(*, property_obj=None, as_of_date: date | None = None) -> dict[str, Any]:
        if as_of_date is None:
            as_of_date = timezone.localdate()
        charges = TenantCharge.objects.select_related("tenant", "property").filter(
            sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
            due_date__lte=as_of_date,
        ).exclude(status=TenantCharge.Status.VOIDED)
        if property_obj is not None:
            charges = charges.filter(property=property_obj)

        rows: list[list[Any]] = []
        total_due = Decimal("0.00")
        for charge in charges:
            paid = sum(
                (
                    _quantize(application.amount_applied)
                    for application in charge.payment_applications.select_related("payment", "sync_record")
                    if application.sync_record and application.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
                    and application.payment.sync_record
                    and application.payment.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED
                    and application.payment.status != TenantPayment.Status.VOIDED
                ),
                Decimal("0.00"),
            )
            balance = (_quantize(charge.amount) - paid).quantize(Decimal("0.01"))
            if balance <= Decimal("0.00"):
                continue
            total_due += balance
            days_past_due = max((as_of_date - charge.due_date).days, 0)
            rows.append(
                [
                    charge.property.name,
                    charge.tenant.name if charge.tenant_id else "-",
                    charge.charge_date,
                    charge.due_date,
                    charge.get_charge_type_display(),
                    _quantize(charge.amount),
                    paid,
                    balance,
                    days_past_due,
                ]
            )

        return {
            "summary_items": [
                ("As of", as_of_date),
                ("Open charges", len(rows)),
                ("Total delinquent balance", total_due),
            ],
            "sections": [
                {
                    "title": "Delinquent charges",
                    "summary": "Synced charges with an outstanding balance due as of the selected date.",
                    "columns": [
                        "Property",
                        "Tenant",
                        "Charge date",
                        "Due date",
                        "Type",
                        "Amount",
                        "Paid",
                        "Balance",
                        "Days past due",
                    ],
                    "rows": rows,
                    "empty_message": "No delinquent balances matched the selected filters.",
                }
            ],
        }

    @staticmethod
    def property_income_expense(*, property_obj=None, period_start: date | None = None, period_end: date | None = None) -> dict[str, Any]:
        if period_start is None:
            period_start = timezone.localdate().replace(day=1)
        if period_end is None:
            period_end = timezone.localdate()

        charges = TenantCharge.objects.select_related("property", "tenant").filter(
            sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
            charge_date__range=(period_start, period_end),
        ).exclude(status=TenantCharge.Status.VOIDED)
        bills = VendorBill.objects.select_related("property", "vendor").filter(
            sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
            bill_date__range=(period_start, period_end),
        ).exclude(status=VendorBill.Status.VOIDED)
        payments = TenantPayment.objects.select_related("property", "tenant").filter(
            sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
            payment_date__range=(period_start, period_end),
        ).exclude(status=TenantPayment.Status.VOIDED)
        if property_obj is not None:
            charges = charges.filter(property=property_obj)
            bills = bills.filter(property=property_obj)
            payments = payments.filter(property=property_obj)

        income_by_type: dict[str, Decimal] = {}
        for charge in charges:
            income_by_type.setdefault(charge.charge_type, Decimal("0.00"))
            income_by_type[charge.charge_type] += _quantize(charge.amount)

        expense_by_type: dict[str, Decimal] = {}
        for bill in bills:
            expense_by_type.setdefault(bill.expense_category, Decimal("0.00"))
            expense_by_type[bill.expense_category] += _quantize(bill.amount)

        collections_by_method: dict[str, Decimal] = {}
        for payment in payments:
            collections_by_method.setdefault(payment.payment_method, Decimal("0.00"))
            collections_by_method[payment.payment_method] += _quantize(payment.amount)

        income_total = sum(income_by_type.values(), Decimal("0.00")).quantize(Decimal("0.01"))
        expense_total = sum(expense_by_type.values(), Decimal("0.00")).quantize(Decimal("0.01"))
        cash_collections = sum(collections_by_method.values(), Decimal("0.00")).quantize(Decimal("0.01"))

        income_rows = [
            [dict(TenantCharge.ChargeType.choices).get(charge_type, charge_type), amount]
            for charge_type, amount in sorted(income_by_type.items())
        ]
        expense_rows = [
            [dict(VendorBill.ExpenseCategory.choices).get(expense_type, expense_type), amount]
            for expense_type, amount in sorted(expense_by_type.items())
        ]
        collection_rows = [
            [dict(TenantPayment.PaymentMethod.choices).get(method, method), amount]
            for method, amount in sorted(collections_by_method.items())
        ]

        return {
            "summary_items": [
                ("Period start", period_start),
                ("Period end", period_end),
                ("Income total", income_total),
                ("Expense total", expense_total),
                ("Net operating income", (income_total - expense_total).quantize(Decimal("0.01"))),
                ("Cash collections memo", cash_collections),
            ],
            "sections": [
                {
                    "title": "Income by charge type",
                    "summary": "Synced tenant charges within the selected period.",
                    "columns": ["Charge type", "Total"],
                    "rows": income_rows,
                    "empty_message": "No synced charges matched the selected filters.",
                },
                {
                    "title": "Expenses by bill type",
                    "summary": "Synced vendor bills within the selected period.",
                    "columns": ["Expense category", "Total"],
                    "rows": expense_rows,
                    "empty_message": "No synced vendor bills matched the selected filters.",
                },
                {
                    "title": "Cash collections memo",
                    "summary": "Synced tenant payments for reference. This report remains accrual-first.",
                    "columns": ["Payment method", "Total"],
                    "rows": collection_rows,
                    "empty_message": "No synced payments matched the selected filters.",
                },
            ],
        }

    @staticmethod
    def security_deposit_ledger(*, property_obj=None, tenant=None, period_start: date | None = None, period_end: date | None = None) -> dict[str, Any]:
        if period_start is None:
            period_start = timezone.localdate().replace(day=1)
        if period_end is None:
            period_end = timezone.localdate()

        events = SecurityDepositEvent.objects.select_related("property", "unit", "tenant", "lease").filter(
            sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
            event_date__range=(period_start, period_end),
        ).exclude(status=SecurityDepositEvent.Status.VOIDED)
        if property_obj is not None:
            events = events.filter(property=property_obj)
        if tenant is not None:
            events = events.filter(tenant=tenant)

        rows: list[list[Any]] = []
        running_balance = Decimal("0.00")
        for event in events.order_by("event_date", "id"):
            if event.event_type == SecurityDepositEvent.EventType.RECEIVED:
                running_balance += _quantize(event.amount)
            elif event.event_type in {
                SecurityDepositEvent.EventType.DEDUCTED,
                SecurityDepositEvent.EventType.REFUNDED,
            }:
                running_balance -= _quantize(event.amount)
            rows.append(
                [
                    event.property.name,
                    event.tenant.name,
                    event.unit.name,
                    event.get_event_type_display(),
                    event.event_date,
                    _quantize(event.amount),
                    running_balance,
                    event.get_status_display(),
                ]
            )

        return {
            "summary_items": [
                ("Period start", period_start),
                ("Period end", period_end),
                ("Ending balance", running_balance),
            ],
            "sections": [
                {
                    "title": "Security deposit events",
                    "summary": "Synced deposit activity with running balance.",
                    "columns": [
                        "Property",
                        "Tenant",
                        "Unit",
                        "Type",
                        "Date",
                        "Amount",
                        "Running balance",
                        "Status",
                    ],
                    "rows": rows,
                    "empty_message": "No synced security deposit events matched the selected filters.",
                }
            ],
        }

    @staticmethod
    def management_fee_expense_summary(*, property_obj=None, period_start: date | None = None, period_end: date | None = None) -> dict[str, Any]:
        if period_start is None:
            period_start = timezone.localdate().replace(day=1)
        if period_end is None:
            period_end = timezone.localdate()
        bills = VendorBill.objects.select_related("property", "vendor").filter(
            sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
            expense_category=VendorBill.ExpenseCategory.MANAGEMENT_FEE,
            bill_date__range=(period_start, period_end),
        ).exclude(status=VendorBill.Status.VOIDED)
        if property_obj is not None:
            bills = bills.filter(property=property_obj)
        rows: list[list[Any]] = []
        total = Decimal("0.00")
        for bill in bills.order_by("property__name", "vendor__name", "bill_date"):
            total += _quantize(bill.amount)
            rows.append([bill.property.name, bill.vendor.name, bill.bill_date, _quantize(bill.amount), bill.get_status_display()])

        return {
            "summary_items": [
                ("Period start", period_start),
                ("Period end", period_end),
                ("Bill count", bills.count()),
                ("Total management fee expense", total),
            ],
            "sections": [
                {
                    "title": "Management fee expenses",
                    "summary": "Manual management-fee expenses recorded through vendor bills or journals.",
                    "columns": ["Property", "Vendor", "Bill date", "Amount", "Status"],
                    "rows": rows,
                    "empty_message": "No synced management fee expenses matched the selected filters.",
                }
            ],
        }

    @staticmethod
    def maintenance_expense_summary(*, property_obj=None, period_start: date | None = None, period_end: date | None = None) -> dict[str, Any]:
        if period_start is None:
            period_start = timezone.localdate().replace(day=1)
        if period_end is None:
            period_end = timezone.localdate()
        bills = VendorBill.objects.select_related("property", "vendor", "maintenance_category").filter(
            sync_record__status=LedgerOSSyncRecord.Status.SUCCEEDED,
            bill_date__range=(period_start, period_end),
        ).exclude(status=VendorBill.Status.VOIDED)
        if property_obj is not None:
            bills = bills.filter(property=property_obj)
        rows: list[list[Any]] = []
        total = Decimal("0.00")
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for bill in bills:
            key = (
                bill.expense_category,
                bill.maintenance_category.name if bill.maintenance_category_id else "-",
            )
            bucket = grouped.setdefault(
                key,
                {
                    "expense_category": bill.expense_category,
                    "maintenance_category": bill.maintenance_category.name if bill.maintenance_category_id else "-",
                    "bill_count": 0,
                    "total": Decimal("0.00"),
                },
            )
            bucket["bill_count"] += 1
            bucket["total"] += _quantize(bill.amount)
            total += _quantize(bill.amount)
        for bucket in sorted(grouped.values(), key=lambda item: (item["expense_category"], item["maintenance_category"])):
            rows.append([
                dict(VendorBill.ExpenseCategory.choices).get(bucket["expense_category"], bucket["expense_category"]),
                bucket["maintenance_category"],
                bucket["bill_count"],
                bucket["total"],
            ])

        return {
            "summary_items": [
                ("Period start", period_start),
                ("Period end", period_end),
                ("Bill count", bills.count()),
                ("Total maintenance expense", total),
            ],
            "sections": [
                {
                    "title": "Maintenance expenses",
                    "summary": "Synced vendor bills categorized for maintenance reporting.",
                    "columns": ["Expense category", "Maintenance category", "Bill count", "Total"],
                    "rows": rows,
                    "empty_message": "No synced maintenance expenses matched the selected filters.",
                }
            ],
        }
