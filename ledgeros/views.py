from __future__ import annotations

import hashlib
import json
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.db import IntegrityError, transaction
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from ledgeros.forms import (
    LeaseForm,
    LedgerOSConnectionSettingsForm,
    OwnerForm,
    PropertyForm,
    TenantChargeForm,
    TenantForm,
    UnitForm,
)
from ledgeros.models import (
    Lease,
    LedgerOSConnectionSettings,
    LedgerOSSyncRecord,
    Owner,
    Property,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    Tenant,
    TenantCharge,
    Unit,
)
from ledgeros.serializers import LedgerOSSyncEventSerializer
from ledgeros.services import (
    LedgerOSCustomerSyncService,
    LedgerOSHealthCheckService,
    LocalHealthCheckService,
    TenantChargeService,
)
from payments.models import DebtServicePayment, SecurityDepositEvent, TenantPayment, VendorBill, VendorPayment


def _add_form_error_from_exception(form, exc: Exception) -> None:
    if isinstance(exc, ValidationError):
        message_dict = getattr(exc, "message_dict", None)
        if isinstance(message_dict, dict):
            for field, messages in message_dict.items():
                for message in messages:
                    form.add_error(field if field in form.fields else None, message)
            return
        for message in getattr(exc, "messages", [str(exc)]):
            form.add_error(None, message)
        return
    form.add_error(None, str(exc))


class LedgerOSAppContextMixin:
    def _mapping_label(self, mapping_key: str) -> str:
        try:
            return PropertyLedgerAccountMapping.MappingKey(mapping_key).label
        except ValueError:
            return mapping_key.replace("_", " ").title()

    def get_setup_flow_steps(self) -> list[dict[str, Any]]:
        setup_obj = PropertyLedgerSetup.load()
        connection_settings = LedgerOSConnectionSettings.load()
        steps = [
            {
                "label": "Configure LedgerOS connection",
                "url": reverse("ledgeros-setup"),
                "summary": (
                    "Set the LedgerOS base URL, client id, and health settings."
                ),
                "complete": bool(
                    connection_settings.base_url and connection_settings.client_id
                ),
            },
            {
                "label": "Create owners",
                "url": reverse("owner-list"),
                "summary": "Properties require a primary owner.",
                "complete": Owner.objects.filter(is_active=True).exists(),
            },
            {
                "label": "Create properties",
                "url": reverse("property-list"),
                "summary": "Units require a property.",
                "complete": Property.objects.exists(),
            },
            {
                "label": "Create units",
                "url": reverse("unit-list"),
                "summary": "Leases require a unit.",
                "complete": Unit.objects.exists(),
            },
            {
                "label": "Create tenants",
                "url": reverse("tenant-list"),
                "summary": "Leases require a tenant.",
                "complete": Tenant.objects.filter(is_active=True).exists(),
            },
            {
                "label": "Create leases",
                "url": reverse("lease-list"),
                "summary": "Finish the operational record chain.",
                "complete": Lease.objects.exists(),
            },
            {
                "label": "Create tenant invoices",
                "url": reverse("charge-list"),
                "summary": "Manual invoices may be property-level or linked to a lease.",
                "complete": TenantCharge.objects.exists(),
            },
            {
                "label": "Record vendor bills and expenses",
                "url": reverse("vendor-bill-list"),
                "summary": "Vendor bills, vendor payments, and debt-service payments are part of the property-accounting workflow.",
                "complete": VendorBill.objects.exists()
                or VendorPayment.objects.exists()
                or DebtServicePayment.objects.exists(),
            },
            {
                "label": "Record tenant invoices and payments",
                "url": reverse("invoice-list"),
                "summary": "Record tenant invoices, payments, and security deposit events.",
                "complete": TenantPayment.objects.exists() or SecurityDepositEvent.objects.exists(),
            },
        ]
        return steps

    def get_setup_prerequisites(self) -> list[dict[str, Any]]:
        setup_obj = PropertyLedgerSetup.load()
        connection_settings = LedgerOSConnectionSettings.load()
        missing_required_mappings = [
            self._mapping_label(mapping_key)
            for mapping_key in setup_obj.missing_required_account_mappings()
        ]

        return [
            {
                "label": "LedgerOS connection saved",
                "complete": bool(
                    connection_settings.base_url and connection_settings.client_id
                ),
                "summary": (
                    "Base URL and client ID must be present in the saved connection settings."
                ),
                "details": (
                    f"Base URL: {connection_settings.base_url or 'missing'}; "
                    f"Client ID: {connection_settings.client_id or 'missing'}"
                ),
            },
            {
                "label": "LedgerOS health check passes",
                "complete": LedgerOSHealthCheckService.check().healthy,
                "summary": (
                    "The configured LedgerOS health endpoint must return a healthy response."
                ),
                "details": (
                    "Run the LedgerOS health check from the setup page after saving connection settings."
                ),
            },
            {
                "label": "LedgerOS entity selected",
                "complete": setup_obj.has_selected_ledgeros_entity,
                "summary": "Select the LedgerOS entity that owns the PropertyLedger books.",
                "details": (
                    setup_obj.ledgeros_entity_name or "No LedgerOS entity has been selected yet."
                ),
            },
            {
                "label": "Accounting period selected",
                "complete": setup_obj.has_selected_accounting_period,
                "summary": "Select the open accounting period to receive posted activity.",
                "details": (
                    setup_obj.ledgeros_accounting_period_name
                    or "No accounting period has been selected yet."
                ),
            },
            {
                "label": "Required account mappings configured",
                "complete": not missing_required_mappings,
                "summary": (
                    "All required LedgerOS account mappings must exist and be valid before setup can complete."
                ),
                "details": (
                    ", ".join(missing_required_mappings)
                    if missing_required_mappings
                    else "All required mappings are present."
                ),
            },
            {
                "label": "Setup smoke passes",
                "complete": setup_obj.last_setup_smoke_healthy,
                "summary": (
                    "The smoke check confirms the full setup path is usable end to end."
                ),
                "details": (
                    "Run make smoke after configuring LedgerOS, the entity, the period, and the required mappings."
                ),
            },
        ]

    def get_app_context(self) -> dict[str, Any]:
        setup_obj = PropertyLedgerSetup.load()
        setup_flow_steps = self.get_setup_flow_steps()
        return {
            "setup_obj": setup_obj,
            "setup_completion_error_groups": setup_obj.setup_completion_error_groups(),
            "setup_is_complete": (
                setup_obj.setup_status == PropertyLedgerSetup.Status.COMPLETE
            ),
            "setup_prerequisites": self.get_setup_prerequisites(),
            "setup_flow_steps": setup_flow_steps,
            "setup_next_step": next(
                (step for step in setup_flow_steps if not step["complete"]),
                None,
            ),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_app_context())
        return context


class LedgerOSSetupView(LedgerOSAppContextMixin, TemplateView):
    template_name = "ledgeros/setup.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        settings_obj = LedgerOSConnectionSettings.load()
        context["settings_form"] = kwargs.get(
            "form", LedgerOSConnectionSettingsForm(instance=settings_obj)
        )
        context["local_health"] = LocalHealthCheckService.check()
        context["ledgeros_health"] = LedgerOSHealthCheckService.check()
        context["settings_obj"] = settings_obj
        return context

    def post(self, request, *args, **kwargs):
        settings_obj = LedgerOSConnectionSettings.load()
        form = LedgerOSConnectionSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse("ledgeros-setup"))
        context = self.get_context_data(form=form)
        return self.render_to_response(context)


class LedgerOSCrudListView(LoginRequiredMixin, LedgerOSAppContextMixin, ListView):
    login_url = reverse_lazy("admin:login")
    template_name = "ledgeros/crud_list.html"
    context_object_name = "objects"
    page_title = ""
    create_url_name = ""
    create_label = "Add"

    def get_create_gate_context(self) -> dict[str, Any]:
        return {
            "create_available": True,
            "create_gate_message": "",
            "create_gate_url": "",
            "create_gate_label": "",
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["create_url"] = reverse(self.create_url_name)
        context["create_label"] = self.create_label
        context["rows"] = self.get_rows(context["objects"])
        context.update(self.get_create_gate_context())
        return context

    def get_rows(self, objects):
        raise NotImplementedError


class LedgerOSCrudFormView(LoginRequiredMixin, LedgerOSAppContextMixin):
    login_url = reverse_lazy("admin:login")
    template_name = "ledgeros/crud_form.html"
    page_title = ""
    page_action = ""
    list_url_name = ""

    def get_create_gate_context(self) -> dict[str, Any]:
        return {
            "create_available": True,
            "create_gate_message": "",
            "create_gate_url": "",
            "create_gate_label": "",
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["page_action"] = self.page_action
        context["list_url"] = reverse(self.list_url_name)
        context.update(self.get_create_gate_context())
        return context

    def form_valid(self, form):
        self.object = form.save()
        return HttpResponseRedirect(reverse(self.list_url_name))


class LedgerOSCrudArchiveView(LoginRequiredMixin, LedgerOSAppContextMixin, DeleteView):
    login_url = reverse_lazy("admin:login")
    template_name = "ledgeros/crud_confirm_delete.html"
    list_url_name = ""
    page_title = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["list_url"] = reverse(self.list_url_name)
        return context

    def get_success_url(self):
        return reverse(self.list_url_name)

    def form_valid(self, form):
        self.object = self.get_object()
        self.archive_object(self.object)
        return HttpResponseRedirect(self.get_success_url())

    def archive_object(self, obj):
        raise NotImplementedError


class LocalHealthAPIView(APIView):
    def get(self, request, *args, **kwargs):
        result = LocalHealthCheckService.check()
        status_code = 200 if result.healthy else 503
        return Response(
            {
                "healthy": result.healthy,
                "source": result.source,
                "details": result.details,
            },
            status=status_code,
        )


class LedgerOSHealthAPIView(APIView):
    def get(self, request, *args, **kwargs):
        result = LedgerOSHealthCheckService.check()
        status_code = 200 if result.healthy else 503
        return Response(
            {
                "healthy": result.healthy,
                "source": result.source,
                "details": result.details,
            },
            status=status_code,
        )


class LedgerOSSyncEventCreateAPIView(APIView):
    serializer_class = LedgerOSSyncEventSerializer

    @staticmethod
    def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return Response(
                {"idempotency_key": ["This header is required."]},
                status=400,
            )

        validated = serializer.validated_data
        envelope = {
            "source_system": validated["source_system"],
            "domain_event_type": validated["domain_event_type"],
            "external_id": validated["external_id"],
            "source_object_type": validated["source_object_type"],
            "source_object_id": validated["source_object_id"],
            "occurred_at": validated["occurred_at"].isoformat(),
            "payload": validated["payload"],
        }
        request_hash = hashlib.sha256(self._canonical_json_bytes(envelope)).hexdigest()

        try:
            with transaction.atomic():
                sync_record, created = LedgerOSSyncRecord.objects.get_or_create(
                    idempotency_key=idempotency_key,
                    defaults={
                        "local_object_type": validated["source_object_type"],
                        "local_object_id": validated["source_object_id"],
                        "ledgeros_resource_type": "sync_event",
                        "source_event_type": validated["domain_event_type"],
                        "external_id": validated["external_id"],
                        "request_hash": request_hash,
                        "response_payload": envelope,
                        "status": LedgerOSSyncRecord.Status.PENDING,
                    },
                )
        except IntegrityError:
            sync_record = LedgerOSSyncRecord.objects.filter(idempotency_key=idempotency_key).first()
            if sync_record is None:
                sync_record = LedgerOSSyncRecord.objects.filter(
                    external_id=validated["external_id"],
                    source_event_type=validated["domain_event_type"],
                ).first()
            if sync_record is None:
                raise
            created = False

        if sync_record.request_hash != request_hash:
            return Response(
                {"idempotency_key": ["This key was already used for a different sync event."]},
                status=409,
            )

        response_data = {
            "id": sync_record.pk,
            "source_system": envelope["source_system"],
            "domain_event_type": sync_record.source_event_type,
            "external_id": sync_record.external_id,
            "source_object_type": sync_record.local_object_type,
            "source_object_id": sync_record.local_object_id,
            "occurred_at": envelope["occurred_at"],
            "payload": envelope["payload"],
            "idempotency_key": sync_record.idempotency_key,
            "request_hash": sync_record.request_hash,
            "ledgeros_resource_type": sync_record.ledgeros_resource_type,
            "ledgeros_resource_id": sync_record.ledgeros_resource_id,
            "ledgeros_journal_entry_id": sync_record.ledgeros_journal_entry_id,
            "response_payload": sync_record.response_payload,
            "status": sync_record.status,
            "last_error": sync_record.last_error,
            "attempt_count": sync_record.attempt_count,
            "last_synced_at": sync_record.last_synced_at,
            "created_at": sync_record.created_at,
            "updated_at": sync_record.updated_at,
        }
        status_code = 201 if created else 200
        return Response(response_data, status=status_code)


class OwnerListView(LedgerOSCrudListView):
    model = Owner
    page_title = "Owners"
    create_url_name = "owner-create"
    create_label = "Add owner"

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": f"{obj.email or 'No email'} | {'active' if obj.is_active else 'inactive'}",
                "edit_url": reverse("owner-edit", kwargs={"pk": obj.pk}),
                "archive_url": reverse("owner-archive", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]


class OwnerCreateView(LedgerOSCrudFormView, CreateView):
    model = Owner
    form_class = OwnerForm
    page_title = "Add owner"
    page_action = "Create owner"
    list_url_name = "owner-list"


class OwnerUpdateView(LedgerOSCrudFormView, UpdateView):
    model = Owner
    form_class = OwnerForm
    page_title = "Edit owner"
    page_action = "Save owner"
    list_url_name = "owner-list"


class OwnerArchiveView(LedgerOSCrudArchiveView):
    model = Owner
    page_title = "Archive owner"
    list_url_name = "owner-list"

    def archive_object(self, obj):
        obj.is_active = False
        obj.save(update_fields=["is_active", "updated_at"])


class PropertyListView(LedgerOSCrudListView):
    model = Property
    page_title = "Properties"
    create_url_name = "property-create"
    create_label = "Add property"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Owner.objects.filter(is_active=True).exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": (
                "Create at least one active owner before adding a property."
            ),
            "create_gate_url": reverse("owner-list"),
            "create_gate_label": "Go to owners",
        }

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": f"{obj.primary_owner.name} | {obj.get_status_display()}",
                "edit_url": reverse("property-edit", kwargs={"pk": obj.pk}),
                "archive_url": reverse("property-archive", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]


class PropertyCreateView(LedgerOSCrudFormView, CreateView):
    model = Property
    form_class = PropertyForm
    page_title = "Add property"
    page_action = "Create property"
    list_url_name = "property-list"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Owner.objects.filter(is_active=True).exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": (
                "Create at least one active owner before adding a property."
            ),
            "create_gate_url": reverse("owner-list"),
            "create_gate_label": "Go to owners",
        }

    def form_valid(self, form):
        validation_failed = False
        with transaction.atomic():
            self.object = form.save()
            try:
                LedgerOSCustomerSyncService.create_customer(
                    customer_code=LedgerOSCustomerSyncService._customer_code_for_property(
                        self.object
                    ),
                    name=self.object.name,
                )
            except (ValidationError, RuntimeError) as exc:
                _add_form_error_from_exception(form, exc)
                transaction.set_rollback(True)
                validation_failed = True
        if validation_failed:
            return self.form_invalid(form)
        return HttpResponseRedirect(reverse(self.list_url_name))


class PropertyUpdateView(LedgerOSCrudFormView, UpdateView):
    model = Property
    form_class = PropertyForm
    page_title = "Edit property"
    page_action = "Save property"
    list_url_name = "property-list"


class PropertyArchiveView(LedgerOSCrudArchiveView):
    model = Property
    page_title = "Archive property"
    list_url_name = "property-list"

    def archive_object(self, obj):
        obj.units.update(status=Unit.Status.ARCHIVED)
        Lease.objects.filter(unit__property=obj).update(status=Lease.Status.CANCELLED)
        obj.status = Property.Status.ARCHIVED
        obj.save(update_fields=["status", "updated_at"])


class UnitListView(LedgerOSCrudListView):
    model = Unit
    page_title = "Units"
    create_url_name = "unit-create"
    create_label = "Add unit"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create a property before adding units.",
            "create_gate_url": reverse("property-list"),
            "create_gate_label": "Go to properties",
        }

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": f"{obj.property.name} | {obj.get_status_display()}",
                "edit_url": reverse("unit-edit", kwargs={"pk": obj.pk}),
                "archive_url": reverse("unit-archive", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]


class UnitCreateView(LedgerOSCrudFormView, CreateView):
    model = Unit
    form_class = UnitForm
    page_title = "Add unit"
    page_action = "Create unit"
    list_url_name = "unit-list"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create a property before adding units.",
            "create_gate_url": reverse("property-list"),
            "create_gate_label": "Go to properties",
        }


class UnitUpdateView(LedgerOSCrudFormView, UpdateView):
    model = Unit
    form_class = UnitForm
    page_title = "Edit unit"
    page_action = "Save unit"
    list_url_name = "unit-list"


class UnitArchiveView(LedgerOSCrudArchiveView):
    model = Unit
    page_title = "Archive unit"
    list_url_name = "unit-list"

    def archive_object(self, obj):
        obj.leases.update(status=Lease.Status.CANCELLED)
        obj.status = Unit.Status.ARCHIVED
        obj.save(update_fields=["status", "updated_at"])


class TenantListView(LedgerOSCrudListView):
    model = Tenant
    page_title = "Tenants"
    create_url_name = "tenant-create"
    create_label = "Add tenant"

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": f"{obj.email or 'No email'} | {'active' if obj.is_active else 'inactive'}",
                "edit_url": reverse("tenant-edit", kwargs={"pk": obj.pk}),
                "archive_url": reverse("tenant-archive", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]


class TenantCreateView(LedgerOSCrudFormView, CreateView):
    model = Tenant
    form_class = TenantForm
    page_title = "Add tenant"
    page_action = "Create tenant"
    list_url_name = "tenant-list"

    def form_valid(self, form):
        validation_failed = False
        with transaction.atomic():
            self.object = form.save()
            try:
                LedgerOSCustomerSyncService.create_customer(
                    customer_code=LedgerOSCustomerSyncService._customer_code_for_tenant(
                        self.object
                    ),
                    name=self.object.name,
                )
            except (ValidationError, RuntimeError) as exc:
                _add_form_error_from_exception(form, exc)
                transaction.set_rollback(True)
                validation_failed = True
        if validation_failed:
            return self.form_invalid(form)
        return HttpResponseRedirect(reverse(self.list_url_name))


class TenantUpdateView(LedgerOSCrudFormView, UpdateView):
    model = Tenant
    form_class = TenantForm
    page_title = "Edit tenant"
    page_action = "Save tenant"
    list_url_name = "tenant-list"


class TenantArchiveView(LedgerOSCrudArchiveView):
    model = Tenant
    page_title = "Archive tenant"
    list_url_name = "tenant-list"

    def archive_object(self, obj):
        obj.leases.update(status=Lease.Status.CANCELLED)
        obj.is_active = False
        obj.save(update_fields=["is_active", "updated_at"])


class LeaseListView(LedgerOSCrudListView):
    model = Lease
    page_title = "Leases"
    create_url_name = "lease-create"
    create_label = "Add lease"

    def get_create_gate_context(self) -> dict[str, Any]:
        unit_missing = not Unit.objects.exists()
        tenant_missing = not Tenant.objects.filter(is_active=True).exists()
        if unit_missing or tenant_missing:
            if unit_missing and tenant_missing:
                message = "Create a unit and a tenant before adding a lease."
            elif unit_missing:
                message = "Create a unit before adding a lease."
            else:
                message = "Create a tenant before adding a lease."
            gate_url_name = "unit-list" if unit_missing else "tenant-list"
            gate_label = "Go to units" if unit_missing else "Go to tenants"
            return {
                "create_available": False,
                "create_gate_message": message,
                "create_gate_url": reverse(gate_url_name),
                "create_gate_label": gate_label,
            }
        return super().get_create_gate_context()

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": (
                    f"{obj.unit.property.name} / {obj.unit.name} -> {obj.tenant.name} "
                    f"| {obj.base_monthly_rent_amount} "
                    f"| {obj.get_status_display()}"
                ),
                "edit_url": reverse("lease-edit", kwargs={"pk": obj.pk}),
                "archive_url": reverse("lease-archive", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]


class LeaseCreateView(LedgerOSCrudFormView, CreateView):
    model = Lease
    form_class = LeaseForm
    page_title = "Add lease"
    page_action = "Create lease"
    list_url_name = "lease-list"

    def get_create_gate_context(self) -> dict[str, Any]:
        unit_missing = not Unit.objects.exists()
        tenant_missing = not Tenant.objects.filter(is_active=True).exists()
        if unit_missing or tenant_missing:
            if unit_missing and tenant_missing:
                message = "Create a unit and a tenant before adding a lease."
            elif unit_missing:
                message = "Create a unit before adding a lease."
            else:
                message = "Create a tenant before adding a lease."
            gate_url_name = "unit-list" if unit_missing else "tenant-list"
            gate_label = "Go to units" if unit_missing else "Go to tenants"
            return {
                "create_available": False,
                "create_gate_message": message,
                "create_gate_url": reverse(gate_url_name),
                "create_gate_label": gate_label,
            }
        return super().get_create_gate_context()


class LeaseUpdateView(LedgerOSCrudFormView, UpdateView):
    model = Lease
    form_class = LeaseForm
    page_title = "Edit lease"
    page_action = "Save lease"
    list_url_name = "lease-list"


class LeaseArchiveView(LedgerOSCrudArchiveView):
    model = Lease
    page_title = "Archive lease"
    list_url_name = "lease-list"

    def archive_object(self, obj):
        obj.status = Lease.Status.CANCELLED
        obj.save(update_fields=["status", "updated_at"])


class TenantChargeListView(LedgerOSCrudListView):
    model = TenantCharge
    page_title = "Invoices"
    create_url_name = "charge-create"
    create_label = "Add invoice"
    bulk_action_choices = [
        ("approve", "Approve selected"),
        ("archive", "Archive selected"),
    ]

    def get_create_gate_context(self) -> dict[str, Any]:
        if Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create a property before adding invoices.",
            "create_gate_url": reverse("property-list"),
            "create_gate_label": "Go to properties",
        }

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": (
                    f"{obj.get_charge_scope_summary()} | {obj.get_charge_type_display()} "
                    f"| {obj.amount} | {obj.get_status_display()}"
                ),
                "detail_url": reverse("charge-detail", kwargs={"pk": obj.pk}),
                "edit_url": reverse("charge-edit", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]

    def post(self, request, *args, **kwargs):
        action = request.POST.get("bulk_action", "").strip()
        selected_ids = [
            value
            for value in request.POST.getlist("selected_charge_ids")
            if value.strip().isdigit()
        ]
        if not action:
            messages.error(request, "Choose a bulk action before submitting.")
            return HttpResponseRedirect(reverse("charge-list"))
        if not selected_ids:
            messages.error(request, "Select at least one charge first.")
            return HttpResponseRedirect(reverse("charge-list"))

        charges_by_id = {
            str(charge.pk): charge
            for charge in TenantCharge.objects.filter(pk__in=selected_ids)
        }
        missing_ids = [pk for pk in selected_ids if pk not in charges_by_id]
        if missing_ids:
            messages.error(
                request,
                f"Could not find charge(s): {', '.join(missing_ids)}.",
            )
            return HttpResponseRedirect(reverse("charge-list"))

        charges = list(charges_by_id.values())
        if action == "approve":
            approved_count = 0
            skipped_ids: list[str] = []
            for charge in charges:
                if charge.status in {
                    TenantCharge.Status.SYNCED,
                    TenantCharge.Status.VOIDED,
                }:
                    skipped_ids.append(str(charge.pk))
                    continue
                TenantChargeService.approve_charge(charge)
                approved_count += 1
            if approved_count:
                messages.success(
                    request,
                    f"Approved {approved_count} charge"
                    f"{'' if approved_count == 1 else 's'}.",
                )
            if skipped_ids:
                messages.warning(
                    request,
                    f"Skipped already finalized charge(s): {', '.join(skipped_ids)}.",
                )
            return HttpResponseRedirect(reverse("charge-list"))

        if action == "archive":
            archived_count = 0
            for charge in charges:
                if charge.status != TenantCharge.Status.VOIDED:
                    charge.status = TenantCharge.Status.VOIDED
                    charge.save(update_fields=["status", "updated_at"])
                    archived_count += 1
            messages.success(
                request,
                f"Archived {archived_count} charge"
                f"{'' if archived_count == 1 else 's'}.",
            )
            return HttpResponseRedirect(reverse("charge-list"))

        messages.error(request, f"Unknown bulk action: {action}.")
        return HttpResponseRedirect(reverse("charge-list"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        failed_charges = (
            TenantCharge.objects.select_related("sync_record", "property", "tenant", "lease")
            .filter(sync_record__status=LedgerOSSyncRecord.Status.FAILED)
            .order_by("-updated_at", "-id")[:5]
        )
        context["sync_log_entries"] = [
            {
                "title": f"Charge {charge.pk} sync failed",
                "object": charge,
                "status": charge.sync_record.status if charge.sync_record else "",
                "error": charge.sync_record.last_error if charge.sync_record else "",
                "response_text": (
                    json.dumps(charge.sync_record.response_payload, indent=2, sort_keys=True)
                    if charge.sync_record and charge.sync_record.response_payload is not None
                    else ""
                ),
                "updated_at": charge.sync_record.updated_at if charge.sync_record else charge.updated_at,
            }
            for charge in failed_charges
            if charge.sync_record is not None
        ]
        return context


class TenantChargeDetailView(LoginRequiredMixin, LedgerOSAppContextMixin, DetailView):
    model = TenantCharge
    template_name = "ledgeros/charge_detail.html"
    context_object_name = "invoice"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return TenantCharge.objects.select_related("sync_record", "property", "tenant", "lease").prefetch_related(
            "payment_applications__payment",
            "payment_applications__sync_record",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object
        context["payment_applications"] = invoice.payment_applications.select_related("payment", "sync_record").all()
        context["payment_history_url"] = reverse("tenant-payment-list")
        context["payments_url"] = reverse("invoice-list")
        return context


class TenantChargeCreateView(LedgerOSCrudFormView, CreateView):
    model = TenantCharge
    form_class = TenantChargeForm
    page_title = "Add invoice"
    page_action = "Create invoice"
    list_url_name = "charge-list"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create a property before adding invoices.",
            "create_gate_url": reverse("property-list"),
            "create_gate_label": "Go to properties",
        }

    def form_valid(self, form):
        self.object = form.save()
        if self.object.status == TenantCharge.Status.APPROVED:
            TenantChargeService.approve_charge(self.object)
        return HttpResponseRedirect(reverse(self.list_url_name))


class TenantChargeUpdateView(LedgerOSCrudFormView, UpdateView):
    model = TenantCharge
    form_class = TenantChargeForm
    page_title = "Edit invoice"
    page_action = "Save invoice"
    list_url_name = "charge-list"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if getattr(self, "object", None) and self.object.sync_record:
            context["sync_log_entries"] = [
                {
                    "title": f"Charge {self.object.pk} sync status",
                    "object": self.object,
                    "status": self.object.sync_record.status,
                    "error": self.object.sync_record.last_error or "",
                    "response_text": (
                        json.dumps(self.object.sync_record.response_payload, indent=2, sort_keys=True)
                        if self.object.sync_record.response_payload is not None
                        else ""
                    ),
                    "updated_at": self.object.sync_record.updated_at,
                }
            ]
        return context

    def form_valid(self, form):
        self.object = form.save()
        if self.object.status == TenantCharge.Status.APPROVED:
            TenantChargeService.approve_charge(self.object)
        return HttpResponseRedirect(reverse(self.list_url_name))


class TenantChargeArchiveView(LedgerOSCrudArchiveView):
    model = TenantCharge
    page_title = "Archive invoice"
    list_url_name = "charge-list"

    def archive_object(self, obj):
        obj.status = TenantCharge.Status.VOIDED
        obj.save(update_fields=["status", "updated_at"])
