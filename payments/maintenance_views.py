from uuid import uuid4

from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from ledgeros.permissions import RoleRequiredMixin
from ledgeros.roles import user_has_any_role
from ledgeros.views import LedgerOSAppContextMixin
from payments.authorization import BILL_EDITOR_ROLES, MAINTENANCE_EDITOR_ROLES, MAINTENANCE_VIEWER_ROLES
from payments.forms import VendorBillForm
from payments.maintenance_forms import (
    MAINTENANCE_BILL_TOKEN_SALT,
    MaintenanceBillLinkForm,
    MaintenanceRequestForm,
    MaintenanceTransitionForm,
)
from payments.maintenance_services import MaintenanceBillHandoffService, MaintenanceRequestService
from payments.models import MaintenanceRequest, Vendor, VendorBill
from payments.services import BillPaymentStatusService


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
        bills = list(request.vendor_bills.select_related("vendor", "sync_record").all())
        statuses = BillPaymentStatusService.statuses(bills) if bills else {}
        context["linked_bill_rows"] = [
            {"bill": bill, "payment_status": statuses[bill.pk]}
            for bill in bills
        ]
        context["bill_link_form"] = MaintenanceBillLinkForm(maintenance_request=request)
        context["can_create_bill"] = user_has_any_role(self.request.user, BILL_EDITOR_ROLES)
        return context


class MaintenanceBillCreateView(RoleRequiredMixin, MaintenanceAppContextMixin, CreateView):
    form_class = VendorBillForm
    template_name = "payments/maintenance_bill_form.html"
    allowed_roles = BILL_EDITOR_ROLES
    login_url = reverse_lazy("login")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not user_has_any_role(request.user, self.allowed_roles):
            return super().dispatch(request, *args, **kwargs)
        self.maintenance_request = get_object_or_404(
            MaintenanceRequest.objects.select_related("property", "unit", "category", "assigned_vendor"),
            pk=kwargs["pk"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        request = self.maintenance_request
        return {
            "property": request.property,
            "unit": request.unit,
            "vendor": request.assigned_vendor,
            "bill_date": timezone.localdate(),
            "expense_category": VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
            "maintenance_category": request.category,
            "repair_notes": request.description,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.method == "POST":
            token = self.request.POST.get("handoff_token", "")
        else:
            token = signing.dumps(
                {
                    "request_id": self.maintenance_request.pk,
                    "request_version": self.maintenance_request.version,
                    "submission_id": str(uuid4()),
                },
                salt=MAINTENANCE_BILL_TOKEN_SALT,
            )
        context.update(maintenance_request=self.maintenance_request, handoff_token=token)
        return context

    def form_valid(self, form):
        token = self.request.POST.get("handoff_token", "")
        try:
            payload = signing.loads(token, salt=MAINTENANCE_BILL_TOKEN_SALT, max_age=86400)
        except signing.BadSignature:
            form.add_error(None, "This bill form has expired or is invalid. Open it again from the maintenance request.")
            return self.form_invalid(form)
        if payload.get("request_id") != self.maintenance_request.pk:
            form.add_error(None, "This bill form belongs to another maintenance request.")
            return self.form_invalid(form)
        try:
            bill, created = MaintenanceBillHandoffService.create_bill(
                request=self.maintenance_request,
                bill=form.save(commit=False),
                actor=self.request.user,
                expected_version=int(payload["request_version"]),
                submission_id=payload["submission_id"],
            )
            if created and self.request.POST.get("action") == "submit":
                from payments.approval_services import VendorBillApprovalService

                bill = VendorBillApprovalService.submit(bill, actor=self.request.user)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            error_messages = exc.messages if isinstance(exc, ValidationError) else ["The bill handoff identity is invalid."]
            form.add_error(None, "; ".join(error_messages))
            return self.form_invalid(form)
        if created:
            message = "Vendor bill created and linked to this maintenance request."
            if bill.approval_status == VendorBill.ApprovalStatus.SUBMITTED:
                message = "Vendor bill created, linked, and submitted for approval."
            messages.success(self.request, message)
        else:
            messages.info(self.request, "This submission already created a vendor bill; the existing bill was reused.")
        return HttpResponseRedirect(reverse("vendor-bill-detail", args=[bill.pk]))


class MaintenanceBillLinkView(RoleRequiredMixin, View):
    allowed_roles = MAINTENANCE_EDITOR_ROLES
    login_url = reverse_lazy("login")

    def post(self, request, *args, **kwargs):
        maintenance_request = get_object_or_404(MaintenanceRequest, pk=kwargs["pk"])
        form = MaintenanceBillLinkForm(request.POST, maintenance_request=maintenance_request)
        if form.is_valid():
            try:
                MaintenanceBillHandoffService.link_bill(
                    request=maintenance_request,
                    bill=form.cleaned_data["bill"],
                    actor=request.user,
                    expected_version=form.cleaned_data["version"],
                )
                messages.success(request, "Vendor bill linked to the maintenance request.")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
        else:
            messages.error(request, "Select a compatible unlinked vendor bill.")
        return HttpResponseRedirect(reverse("maintenance-request-detail", args=[maintenance_request.pk]))


class MaintenanceBillUnlinkView(RoleRequiredMixin, View):
    allowed_roles = MAINTENANCE_EDITOR_ROLES
    login_url = reverse_lazy("login")

    def post(self, request, *args, **kwargs):
        maintenance_request = get_object_or_404(MaintenanceRequest, pk=kwargs["pk"])
        bill = get_object_or_404(VendorBill, pk=kwargs["bill_pk"])
        try:
            MaintenanceBillHandoffService.unlink_bill(
                request=maintenance_request,
                bill=bill,
                actor=request.user,
                expected_version=int(request.POST.get("version", 0)),
            )
            messages.success(request, "Vendor bill unlinked from the maintenance request.")
        except (ValueError, ValidationError) as exc:
            error_messages = exc.messages if isinstance(exc, ValidationError) else ["The request version is invalid."]
            messages.error(request, "; ".join(error_messages))
        return HttpResponseRedirect(reverse("maintenance-request-detail", args=[maintenance_request.pk]))
