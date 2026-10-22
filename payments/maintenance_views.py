from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from ledgeros.permissions import RoleRequiredMixin
from ledgeros.roles import user_has_any_role
from ledgeros.views import LedgerOSAppContextMixin
from payments.authorization import MAINTENANCE_EDITOR_ROLES, MAINTENANCE_VIEWER_ROLES
from payments.maintenance_forms import MaintenanceRequestForm, MaintenanceTransitionForm
from payments.maintenance_services import MaintenanceRequestService
from payments.models import MaintenanceRequest, Vendor


class MaintenanceAppContextMixin(LedgerOSAppContextMixin):
    pass


class MaintenanceRequestListView(RoleRequiredMixin, MaintenanceAppContextMixin, ListView):
    model = MaintenanceRequest
    template_name = "payments/maintenance_list.html"
    context_object_name = "maintenance_requests"
    allowed_roles = MAINTENANCE_VIEWER_ROLES
    login_url = reverse_lazy("login")

    def get_queryset(self):
        queryset = MaintenanceRequest.objects.select_related(
            "property", "unit", "tenant", "category", "assigned_vendor", "created_by"
        )
        selected = self.request.GET.get("status", "").strip()
        if selected in MaintenanceRequest.Status.values:
            queryset = queryset.filter(status=selected)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = MaintenanceRequest.Status.choices
        context["selected_status"] = self.request.GET.get("status", "")
        context["can_change_maintenance"] = user_has_any_role(self.request.user, MAINTENANCE_EDITOR_ROLES)
        return context


class MaintenanceRequestCreateView(RoleRequiredMixin, MaintenanceAppContextMixin, CreateView):
    model = MaintenanceRequest
    form_class = MaintenanceRequestForm
    template_name = "payments/maintenance_form.html"
    allowed_roles = MAINTENANCE_EDITOR_ROLES
    login_url = reverse_lazy("login")

    def form_valid(self, form):
        fields = {name: form.cleaned_data[name] for name in MaintenanceRequestForm.Meta.fields}
        self.object = MaintenanceRequestService.create(actor=self.request.user, **fields)
        messages.success(self.request, "Maintenance request created. It remains independent of vendor billing.")
        return HttpResponseRedirect(reverse("maintenance-request-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="New maintenance request", page_action="Create request")
        return context


class MaintenanceRequestUpdateView(RoleRequiredMixin, MaintenanceAppContextMixin, UpdateView):
    model = MaintenanceRequest
    form_class = MaintenanceRequestForm
    template_name = "payments/maintenance_form.html"
    allowed_roles = MAINTENANCE_EDITOR_ROLES
    login_url = reverse_lazy("login")

    def get_queryset(self):
        return MaintenanceRequest.objects.select_related("property", "unit", "tenant", "category", "assigned_vendor")

    def form_valid(self, form):
        candidate = form.save(commit=False)
        try:
            self.object = MaintenanceRequestService.update(
                request=candidate,
                actor=self.request.user,
                expected_version=form.cleaned_data["version"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
            return self.form_invalid(form)
        messages.success(self.request, "Maintenance request updated.")
        return HttpResponseRedirect(reverse("maintenance-request-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="Edit maintenance request", page_action="Save request")
        return context


class MaintenanceRequestDetailView(RoleRequiredMixin, MaintenanceAppContextMixin, DetailView):
    model = MaintenanceRequest
    template_name = "payments/maintenance_detail.html"
    context_object_name = "maintenance_request"
    allowed_roles = MAINTENANCE_VIEWER_ROLES
    write_allowed_roles = MAINTENANCE_EDITOR_ROLES
    login_url = reverse_lazy("login")

    ACTIONS_BY_STATUS = {
        MaintenanceRequest.Status.OPEN: (("triage", "Mark triaged"), ("cancel", "Cancel request")),
        MaintenanceRequest.Status.TRIAGED: (("assign", "Assign vendor"), ("hold", "Put on hold"), ("cancel", "Cancel request")),
        MaintenanceRequest.Status.ASSIGNED: (("start", "Start work"), ("hold", "Put on hold"), ("cancel", "Cancel request")),
        MaintenanceRequest.Status.IN_PROGRESS: (("verify", "Verify completion"), ("hold", "Put on hold"), ("cancel", "Cancel request")),
        MaintenanceRequest.Status.ON_HOLD: (("resume", "Resume work"), ("cancel", "Cancel request")),
        MaintenanceRequest.Status.VERIFIED: (("close", "Close request"),),
        MaintenanceRequest.Status.CLOSED: (("reopen", "Reopen request"),),
        MaintenanceRequest.Status.CANCELLED: (),
    }

    def get_queryset(self):
        return MaintenanceRequest.objects.select_related(
            "property", "unit", "tenant", "category", "assigned_vendor", "created_by",
            "verified_by", "closed_by",
        )

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = MaintenanceTransitionForm(request.POST)
        if form.is_valid():
            try:
                MaintenanceRequestService.transition(
                    request=self.object,
                    action=form.cleaned_data["action"],
                    actor=request.user,
                    expected_version=form.cleaned_data["version"],
                    reason=form.cleaned_data["reason"],
                    assigned_vendor=form.cleaned_data["assigned_vendor"],
                    closure_financial_status=form.cleaned_data["closure_financial_status"],
                )
                messages.success(request, "Maintenance request status updated.")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
        else:
            messages.error(request, "; ".join(message for errors in form.errors.values() for message in errors))
        return HttpResponseRedirect(reverse("maintenance-request-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.object
        context["events"] = request.events.select_related("actor")
        context["can_change_maintenance"] = user_has_any_role(self.request.user, MAINTENANCE_EDITOR_ROLES)
        context["available_actions"] = self.ACTIONS_BY_STATUS[request.status]
        context["active_vendors"] = Vendor.objects.filter(is_active=True)
        context["closure_status_choices"] = MaintenanceRequest.ClosureFinancialStatus.choices
        return context
