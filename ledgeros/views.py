from __future__ import annotations

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
    Unit,
)
from ledgeros.serializers import LedgerOSSyncRecordSerializer
from ledgeros.services import LedgerOSHealthCheckService, LocalHealthCheckService


class LedgerOSAppContextMixin:
    def get_app_context(self) -> dict[str, Any]:
        setup_obj = PropertyLedgerSetup.load()
        return {
            "setup_obj": setup_obj,
            "setup_completion_errors": setup_obj.setup_completion_errors(),
            "setup_is_complete": (
                setup_obj.setup_status == PropertyLedgerSetup.Status.COMPLETE
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["create_url"] = reverse(self.create_url_name)
        context["create_label"] = self.create_label
        context["rows"] = self.get_rows(context["objects"])
        return context

    def get_rows(self, objects):
        raise NotImplementedError


class LedgerOSCrudFormView(LoginRequiredMixin, LedgerOSAppContextMixin):
    login_url = reverse_lazy("admin:login")
    template_name = "ledgeros/crud_form.html"
    page_title = ""
    page_action = ""
    list_url_name = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["page_action"] = self.page_action
        context["list_url"] = reverse(self.list_url_name)
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
