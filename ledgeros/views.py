from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView
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
    PropertyLedgerSetup,
    Tenant,
    TenantCharge,
    Unit,
)
from ledgeros.serializers import LedgerOSSyncRecordSerializer
from ledgeros.services import (
    LedgerOSHealthCheckService,
    LocalHealthCheckService,
    TenantChargeService,
)


class LedgerOSAppContextMixin:
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
                "label": "Create tenant charges",
                "url": reverse("charge-list"),
                "summary": "Manual charges may be property-level or linked to a lease.",
                "complete": TenantCharge.objects.exists(),
            },
        ]
        return steps

    def get_app_context(self) -> dict[str, Any]:
        setup_obj = PropertyLedgerSetup.load()
        setup_flow_steps = self.get_setup_flow_steps()
        return {
            "setup_obj": setup_obj,
            "setup_completion_error_groups": setup_obj.setup_completion_error_groups(),
            "setup_is_complete": (
                setup_obj.setup_status == PropertyLedgerSetup.Status.COMPLETE
            ),
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


class LedgerOSSyncRecordCreateAPIView(generics.CreateAPIView):
    queryset = LedgerOSSyncRecord.objects.all()
    serializer_class = LedgerOSSyncRecordSerializer


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
    page_title = "Tenant Charges"
    create_url_name = "charge-create"
    create_label = "Add charge"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create a property before adding charges.",
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
                "edit_url": reverse("charge-edit", kwargs={"pk": obj.pk}),
                "archive_url": reverse("charge-archive", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]

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


class TenantChargeCreateView(LedgerOSCrudFormView, CreateView):
    model = TenantCharge
    form_class = TenantChargeForm
    page_title = "Add charge"
    page_action = "Create charge"
    list_url_name = "charge-list"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create a property before adding charges.",
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
    page_title = "Edit charge"
    page_action = "Save charge"
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
    page_title = "Archive charge"
    list_url_name = "charge-list"

    def archive_object(self, obj):
        obj.status = TenantCharge.Status.VOIDED
        obj.save(update_fields=["status", "updated_at"])
