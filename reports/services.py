from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ledgeros.idempotency import build_idempotency_key
from ledgeros.models import (
    LedgerOSConnectionSettings,
    LedgerOSSyncRecord,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    TenantCharge,
)
from ledgeros.signing import sign_request
from payments.models import SecurityDepositEvent, TenantPayment, VendorBill
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
