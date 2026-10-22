from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import Owner, Property, Tenant
from ledgeros.roles import ROLE_BOOKKEEPER, assign_user_role
from ledgeros.services import HealthCheckResult, LedgerOSWriteReadinessService
from payments.models import TenantPayment


class WorkflowOutageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="outage-bookkeeper", password="password")
        assign_user_role(self.user, ROLE_BOOKKEEPER)
        self.client.force_login(self.user)
        owner = Owner.objects.create(name="Outage owner")
        self.property = Property.objects.create(name="Outage property", primary_owner=owner)
        self.tenant = Tenant.objects.create(name="Outage tenant")

    def test_readiness_classifies_configuration_permission_and_outage_separately(self):
        cases = (
            ({"error": "missing_configuration"}, "configuration"),
            ({"http_status": 403}, "permission"),
            ({"error": "connection refused"}, "unavailable"),
        )
        for details, expected in cases:
            with self.subTest(expected=expected):
                result = LedgerOSWriteReadinessService.classify(
                    HealthCheckResult(False, "ledgeros", details)
                )
                self.assertFalse(result.ready)
                self.assertEqual(result.status, expected)

    @patch("payments.views.TenantPaymentService.sync_payment")
    @patch("payments.views.LedgerOSWriteReadinessService.require")
    def test_outage_allows_receipt_draft_but_blocks_finalization_then_recovers(self, readiness, sync_payment):
        response = self.client.post(
            reverse("tenant-payment-create"),
            {
                "property": self.property.pk,
                "tenant": self.tenant.pk,
                "payment_date": date(2026, 10, 21),
                "amount": "725.00",
                "payment_method": TenantPayment.PaymentMethod.CHECK,
                "reference": "OUTAGE-RECEIPT",
                "notes": "Saved while LedgerOS was down",
                "status": TenantPayment.Status.DRAFT,
                "deposit_amount": "0.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        payment = TenantPayment.objects.get(reference="OUTAGE-RECEIPT")
        payment_id = payment.pk
        readiness.assert_not_called()

        readiness.side_effect = ValidationError(LedgerOSWriteReadinessService.MESSAGES["unavailable"])
        response = self.client.post(
            reverse("tenant-payment-detail", args=[payment.pk]), {"action": "sync"}, follow=True
        )
        self.assertContains(response, "LedgerOS is unavailable")
        sync_payment.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.pk, payment_id)
        self.assertEqual(payment.status, TenantPayment.Status.DRAFT)

        readiness.side_effect = None
        response = self.client.post(
            reverse("tenant-payment-detail", args=[payment.pk]), {"action": "sync"}
        )
        self.assertEqual(response.status_code, 302)
        sync_payment.assert_called_once_with(payment)
        self.assertEqual(TenantPayment.objects.get(pk=payment_id).pk, payment_id)

    @patch("payments.views.TenantPaymentService.sync_payment")
    @patch("payments.views.LedgerOSWriteReadinessService.require", side_effect=ValidationError(
        LedgerOSWriteReadinessService.MESSAGES["permission"]
    ))
    def test_permission_failure_blocks_posting_without_creating_sync_state(self, readiness, sync_payment):
        payment = TenantPayment.objects.create(
            property=self.property,
            tenant=self.tenant,
            payment_date=date(2026, 10, 21),
            amount=Decimal("100.00"),
            payment_method=TenantPayment.PaymentMethod.CASH,
        )
        response = self.client.post(
            reverse("tenant-payment-detail", args=[payment.pk]), {"action": "sync"}, follow=True
        )
        self.assertContains(response, "denied access")
        sync_payment.assert_not_called()
        payment.refresh_from_db()
        self.assertIsNone(payment.sync_record_id)
