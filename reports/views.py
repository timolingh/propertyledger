from __future__ import annotations

import csv
from decimal import Decimal
from io import StringIO
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from ledgeros.models import Owner, Property
from payments.models import VendorBill
from reports.forms import OwnerContributionDistributionForm, OwnerStatementForm
from reports.models import OwnerContributionDistribution
from reports.services import OwnerActivityService, OwnerStatementService, statement_period_bounds
from ledgeros.views import LedgerOSAppContextMixin, LedgerOSCrudArchiveView


class ReportsAppContextMixin(LedgerOSAppContextMixin):
    def get_setup_flow_steps(self) -> list[dict[str, Any]]:
        steps = super().get_setup_flow_steps()
        if any(step["label"] == "Generate owner statements" for step in steps):
            return steps
        steps.append(
            {
                "label": "Generate owner statements",
                "url": reverse("reports-home"),
                "summary": "Preview or export owner statements and review pending-sync items for owner activity.",
                "complete": OwnerContributionDistribution.objects.filter(sync_record__isnull=False).exists(),
            }
        )
        return steps


class ReportsLandingView(LoginRequiredMixin, ReportsAppContextMixin, TemplateView):
    login_url = reverse_lazy("admin:login")
    template_name = "reports/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["create_owner_activity_url"] = reverse("owner-activity-create")
        context["owner_activity_list_url"] = reverse("owner-activity-list")
        context["owner_statement_url"] = reverse("owner-statement")
        context["pending_sync_url"] = reverse("owner-activity-pending-sync")
        return context


class OwnerContributionDistributionListView(LoginRequiredMixin, ReportsAppContextMixin, ListView):
    login_url = reverse_lazy("admin:login")
    model = OwnerContributionDistribution
    template_name = "reports/owner_activity_list.html"
    context_object_name = "activities"

    def get_queryset(self):
        return OwnerContributionDistribution.objects.select_related("owner", "property", "sync_record")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["create_url"] = reverse("owner-activity-create")
        return context


class OwnerContributionDistributionCreateView(LoginRequiredMixin, ReportsAppContextMixin, CreateView):
    login_url = reverse_lazy("admin:login")
    model = OwnerContributionDistribution
    form_class = OwnerContributionDistributionForm
    template_name = "ledgeros/crud_form.html"
    success_url = reverse_lazy("owner-activity-list")
    page_title = "Owner activity"
    page_action = "Save owner activity"
    list_url_name = "owner-activity-list"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Owner activity saved.")
        if self.object.status in {
            OwnerContributionDistribution.Status.READY_TO_SYNC,
            OwnerContributionDistribution.Status.POSTED,
        }:
            try:
                OwnerActivityService.sync_activity(self.object)
            except ValidationError as exc:
                messages.error(self.request, "; ".join(exc.messages))
        return response


class OwnerContributionDistributionUpdateView(LoginRequiredMixin, ReportsAppContextMixin, UpdateView):
    login_url = reverse_lazy("admin:login")
    model = OwnerContributionDistribution
    form_class = OwnerContributionDistributionForm
    template_name = "ledgeros/crud_form.html"
    success_url = reverse_lazy("owner-activity-list")
    page_title = "Owner activity"
    page_action = "Update owner activity"
    list_url_name = "owner-activity-list"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Owner activity updated.")
        if self.object.status in {
            OwnerContributionDistribution.Status.READY_TO_SYNC,
            OwnerContributionDistribution.Status.POSTED,
        } and self.object.is_editable_after_sync:
            try:
                OwnerActivityService.sync_activity(self.object)
            except ValidationError as exc:
                messages.error(self.request, "; ".join(exc.messages))
        return response


class OwnerContributionDistributionDetailView(LoginRequiredMixin, ReportsAppContextMixin, DetailView):
    login_url = reverse_lazy("admin:login")
    model = OwnerContributionDistribution
    template_name = "reports/owner_activity_detail.html"
    context_object_name = "activity"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["edit_url"] = reverse("owner-activity-edit", kwargs={"pk": self.object.pk})
        context["list_url"] = reverse("owner-activity-list")
        return context


class OwnerContributionDistributionArchiveView(LedgerOSCrudArchiveView):
    login_url = reverse_lazy("admin:login")
    model = OwnerContributionDistribution
    success_url = reverse_lazy("owner-activity-list")
    page_title = "Owner activity"
    list_url_name = "owner-activity-list"

    def archive_object(self, obj):
        obj.status = OwnerContributionDistribution.Status.VOIDED
        obj.save(update_fields=["status", "updated_at"])


class OwnerStatementView(LoginRequiredMixin, ReportsAppContextMixin, TemplateView):
    login_url = reverse_lazy("admin:login")
    template_name = "reports/owner_statement.html"

    def get_form(self) -> OwnerStatementForm:
        return OwnerStatementForm(self.request.GET or None)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_form()
        context["form"] = form
        statement = None
        if form.is_valid():
            statement = OwnerStatementService.build_statement(
                owner=form.cleaned_data["owner"],
                property_obj=form.cleaned_data["property"],
                period_type=form.cleaned_data["period_type"],
                period_start=form.cleaned_data["period_start"],
                period_end=form.cleaned_data["period_end"],
            )
        context["statement"] = statement
        context["export_url"] = reverse("owner-statement-export")
        return context


class OwnerStatementExportView(LoginRequiredMixin, ReportsAppContextMixin, TemplateView):
    login_url = reverse_lazy("admin:login")

    def get(self, request, *args, **kwargs):
        form = OwnerStatementForm(request.GET or None)
        if not form.is_valid():
            return HttpResponse("Invalid statement parameters.", status=400)
        statement = OwnerStatementService.build_statement(
            owner=form.cleaned_data["owner"],
            property_obj=form.cleaned_data["property"],
            period_type=form.cleaned_data["period_type"],
            period_start=form.cleaned_data["period_start"],
            period_end=form.cleaned_data["period_end"],
        )
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Owner", statement["owner"].name])
        writer.writerow(["Property", statement["property"].name])
        writer.writerow(["Period start", statement["period_start"].isoformat()])
        writer.writerow(["Period end", statement["period_end"].isoformat()])
        writer.writerow([])
        writer.writerow(["Metric", "Amount"])
        for key in [
            "rent_charged",
            "rent_collected",
            "property_expenses",
            "maintenance_expenses",
            "management_fee_expenses",
            "contributions",
            "distributions",
            "deposit_received",
            "deposit_deducted",
            "deposit_refunded",
            "net_summary",
        ]:
            writer.writerow([key.replace("_", " ").title(), statement[key]])
        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="owner-statement.csv"'
        return response


class OwnerPendingSyncReportView(LoginRequiredMixin, ReportsAppContextMixin, TemplateView):
    login_url = reverse_lazy("admin:login")
    template_name = "reports/pending_sync.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        owner_id = self.request.GET.get("owner")
        property_id = self.request.GET.get("property")
        owner = None
        property_obj = None
        if owner_id:
            owner = Owner.objects.filter(pk=owner_id, is_active=True).first()
        if property_id:
            property_obj = Property.objects.filter(pk=property_id, status=Property.Status.ACTIVE).first()
        if owner and property_obj:
            pending = OwnerStatementService.pending_sync_items(owner=owner, property_obj=property_obj)
        else:
            pending = {"owner_activity_items": [], "management_fee_bills": []}
        context["pending"] = pending
        context["owner"] = owner
        context["property_obj"] = property_obj
        return context
