from datetime import date
from decimal import Decimal

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from ledgeros.models import AuditLog, Lease, LedgerOSSyncRecord, Owner, Property, Tenant, Unit
from ledgeros.roles import (
    ROLE_ADMIN,
    ROLE_BOOKKEEPER,
    ROLE_OWNER_VIEWER,
    ROLE_PROPERTY_MANAGER,
    ROLE_READ_ONLY_VIEWER,
    assign_user_role,
)
from payments.admin import MaintenanceRequestAdmin
from payments.maintenance_services import MaintenanceRequestService
from payments.models import (
    MaintenanceCategory,
    MaintenanceRequest,
    MaintenanceRequestEvent,
    Vendor,
    VendorBill,
)


class MaintenanceWorkflowTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.admin = users.create_user("maintenance-admin", is_staff=True)
        self.manager = users.create_user("maintenance-manager")
        self.bookkeeper = users.create_user("maintenance-bookkeeper")
        self.viewer = users.create_user("maintenance-viewer")
        self.owner_viewer = users.create_user("maintenance-owner-viewer")
        assign_user_role(self.admin, ROLE_ADMIN)
        assign_user_role(self.manager, ROLE_PROPERTY_MANAGER)
        assign_user_role(self.bookkeeper, ROLE_BOOKKEEPER)
        assign_user_role(self.viewer, ROLE_READ_ONLY_VIEWER)
        assign_user_role(self.owner_viewer, ROLE_OWNER_VIEWER)

        owner = Owner.objects.create(name="Owner")
        self.property = Property.objects.create(name="Building", primary_owner=owner)
        self.other_property = Property.objects.create(name="Other building", primary_owner=owner)
        self.unit = Unit.objects.create(property=self.property, name="1A")
        self.other_unit = Unit.objects.create(property=self.other_property, name="2B")
        self.tenant = Tenant.objects.create(name="Resident")
        self.other_tenant = Tenant.objects.create(name="Other resident")
        Lease.objects.create(
            unit=self.unit,
            tenant=self.tenant,
            lease_start_date=date(2026, 1, 1),
            status=Lease.Status.ACTIVE,
        )
        self.category = MaintenanceCategory.objects.create(name="Plumbing")
        self.vendor = Vendor.objects.create(name="Plumber")

    def request_data(self, **overrides):
        data = {
            "property": self.property,
            "unit": self.unit,
            "tenant": self.tenant,
            "category": self.category,
            "priority": MaintenanceRequest.Priority.NORMAL,
            "description": "Kitchen sink is leaking.",
            "assigned_vendor": self.vendor,
            "target_completion_date": date(2026, 11, 1),
            "estimated_cost": Decimal("250.00"),
            "source": MaintenanceRequest.Source.INTERNAL,
        }
        data.update(overrides)
        return data

    def create_request(self, actor=None, **overrides):
        return MaintenanceRequestService.create(
            actor=actor or self.manager,
            **self.request_data(**overrides),
        )

    def transition(self, request, action, *, actor=None, reason="", **kwargs):
        return MaintenanceRequestService.transition(
            request=request,
            action=action,
            actor=actor or self.manager,
            expected_version=request.version,
            reason=reason,
            **kwargs,
        )

    def test_create_records_required_optional_fields_actor_and_audit(self):
        request = self.create_request()

        self.assertEqual(request.created_by, self.manager)
        self.assertEqual(request.status, MaintenanceRequest.Status.OPEN)
        self.assertEqual(request.version, 1)
        self.assertEqual(request.unit, self.unit)
        self.assertEqual(request.tenant, self.tenant)
        self.assertEqual(request.assigned_vendor, self.vendor)
        self.assertEqual(request.estimated_cost, Decimal("250.00"))
        event = request.events.get()
        self.assertEqual(event.action, MaintenanceRequestEvent.Action.CREATED)
        self.assertEqual(event.actor, self.manager)
        self.assertTrue(
            AuditLog.objects.filter(
                action="maintenance_request.created", record_id=str(request.pk), actor=self.manager
            ).exists()
        )

    def test_scope_and_cost_validation(self):
        with self.assertRaises(ValidationError):
            self.create_request(unit=self.other_unit)
        with self.assertRaises(ValidationError):
            self.create_request(tenant=self.other_tenant)
        with self.assertRaises(ValidationError):
            self.create_request(estimated_cost=Decimal("-0.01"))
        with self.assertRaises(ValidationError):
            self.create_request(description="   ")

    def test_canonical_lifecycle_verification_and_independent_closure(self):
        request = self.create_request(assigned_vendor=None)
        request = self.transition(request, "triage")
        request = self.transition(request, "assign", assigned_vendor=self.vendor)
        request = self.transition(request, "start")
        request = self.transition(request, "verify", reason="Work inspected")
        request = self.transition(
            request,
            "close",
            reason="Invoice has not arrived yet",
            closure_financial_status=MaintenanceRequest.ClosureFinancialStatus.INVOICE_PENDING,
        )

        self.assertEqual(request.status, MaintenanceRequest.Status.CLOSED)
        self.assertEqual(request.verified_by, self.manager)
        self.assertIsNotNone(request.verified_at)
        self.assertEqual(request.closed_by, self.manager)
        self.assertIsNotNone(request.closed_at)
        self.assertEqual(request.version, 6)
        self.assertEqual(
            list(request.events.values_list("action", flat=True)),
            ["created", "triage", "assign", "start", "verify", "close"],
        )

    def test_no_cost_closure_and_reasoned_reopening_preserve_history(self):
        request = self.create_request()
        request = self.transition(request, "triage")
        request = self.transition(request, "assign")
        request = self.transition(request, "start")
        request = self.transition(request, "verify", reason="Completed internally")
        request = self.transition(
            request,
            "close",
            reason="Staff repair; no outside invoice",
            closure_financial_status=MaintenanceRequest.ClosureFinancialStatus.NO_EXTERNAL_COST,
        )
        with self.assertRaises(ValidationError):
            self.transition(request, "reopen")

        request = self.transition(request, "reopen", reason="Leak returned")
        self.assertEqual(request.status, MaintenanceRequest.Status.TRIAGED)
        self.assertIsNone(request.closed_at)
        self.assertEqual(request.reopen_count, 1)
        self.assertEqual(request.events.filter(action="close").count(), 1)
        self.assertEqual(request.events.filter(action="reopen", reason="Leak returned").count(), 1)

    def test_hold_resume_and_cancel_are_explicit_transitions(self):
        request = self.create_request()
        request = self.transition(request, "triage")
        request = self.transition(request, "hold", reason="Waiting for access")
        self.assertEqual(request.status, MaintenanceRequest.Status.ON_HOLD)
        self.assertEqual(request.hold_from_status, MaintenanceRequest.Status.TRIAGED)
        request = self.transition(request, "resume", reason="Access arranged")
        self.assertEqual(request.status, MaintenanceRequest.Status.TRIAGED)
        request = self.transition(request, "cancel", reason="Duplicate request")
        self.assertEqual(request.status, MaintenanceRequest.Status.CANCELLED)

    def test_invalid_and_stale_transitions_do_not_mutate(self):
        request = self.create_request()
        with self.assertRaises(ValidationError):
            self.transition(request, "close", reason="Too early")
        stale_version = request.version
        request = self.transition(request, "triage")
        with self.assertRaises(ValidationError):
            MaintenanceRequestService.transition(
                request=request,
                action="assign",
                actor=self.manager,
                expected_version=stale_version,
            )
        request.refresh_from_db()
        self.assertEqual(request.status, MaintenanceRequest.Status.TRIAGED)
        self.assertEqual(request.events.count(), 2)

    def test_update_is_authorized_validated_and_versioned(self):
        request = self.create_request()
        request.description = "Sink and cabinet are wet."
        updated = MaintenanceRequestService.update(
            request=request,
            actor=self.bookkeeper,
            expected_version=request.version,
        )
        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.events.last().action, MaintenanceRequestEvent.Action.UPDATED)
        self.assertEqual(
            updated.events.last().metadata["changes"]["description"],
            {"from": "Kitchen sink is leaking.", "to": "Sink and cabinet are wet."},
        )

        request.description = "Stale edit"
        with self.assertRaises(ValidationError):
            MaintenanceRequestService.update(
                request=request,
                actor=self.bookkeeper,
                expected_version=1,
            )

    def test_role_matrix_at_service_and_ui_boundaries(self):
        for actor in (self.admin, self.manager, self.bookkeeper):
            request = self.create_request(actor=actor, description=f"Created by {actor.username}")
            self.assertEqual(request.created_by, actor)
        for actor in (self.viewer, self.owner_viewer):
            with self.assertRaises(PermissionDenied):
                self.create_request(actor=actor)

        request = self.create_request()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("maintenance-request-list")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("maintenance-request-detail", args=[request.pk])).status_code,
            200,
        )
        self.assertEqual(self.client.get(reverse("maintenance-request-create")).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("maintenance-request-detail", args=[request.pk]),
                {"action": "triage", "version": request.version},
            ).status_code,
            403,
        )
        self.client.force_login(self.owner_viewer)
        self.assertEqual(self.client.get(reverse("maintenance-request-list")).status_code, 403)

    def test_ui_create_and_transition_work_while_ledgeros_is_unavailable(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("maintenance-request-create"),
            {
                "property": self.property.pk,
                "unit": self.unit.pk,
                "tenant": self.tenant.pk,
                "category": self.category.pk,
                "priority": MaintenanceRequest.Priority.URGENT,
                "description": "No heat",
                "assigned_vendor": "",
                "target_completion_date": "",
                "estimated_cost": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        request = MaintenanceRequest.objects.get(description="No heat")
        response = self.client.post(
            reverse("maintenance-request-detail", args=[request.pk]),
            {"action": "triage", "version": request.version, "reason": "Reviewed"},
        )
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, MaintenanceRequest.Status.TRIAGED)
        self.assertFalse(LedgerOSSyncRecord.objects.exists())
        self.assertFalse(VendorBill.objects.exists())

        home = self.client.get(reverse("app-home"))
        self.assertContains(home, "Active maintenance requests")
        self.assertContains(home, reverse("maintenance-request-detail", args=[request.pk]))
        self.assertContains(home, reverse("maintenance-request-create"))

    def test_admin_save_uses_service_and_history_is_immutable(self):
        request_factory = RequestFactory()
        request = request_factory.post("/admin/payments/maintenancerequest/add/")
        request.user = self.admin
        obj = MaintenanceRequest(**self.request_data())
        MaintenanceRequestAdmin(MaintenanceRequest, django_admin.site).save_model(
            request, obj, form=None, change=False
        )
        self.assertEqual(obj.created_by, self.admin)
        self.assertEqual(obj.events.get().action, "created")

        event_admin = django_admin.site._registry[MaintenanceRequestEvent]
        self.assertFalse(event_admin.has_add_permission(request))
        self.assertFalse(event_admin.has_change_permission(request))
        self.assertFalse(event_admin.has_delete_permission(request))


class MaintenanceRequestModelTests(TestCase):
    def test_database_defaults_do_not_forge_lifecycle_state(self):
        fields = {field.name for field in MaintenanceRequest._meta.fields}
        self.assertIn("status", fields)
        self.assertIn("version", fields)
        self.assertIn("source", fields)
        self.assertNotIn("photo", fields)

