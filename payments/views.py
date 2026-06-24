from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from ledgeros.models import TenantCharge
from ledgeros.views import LedgerOSAppContextMixin, LedgerOSCrudArchiveView
from payments.forms import SecurityDepositEventForm, TenantPaymentForm
from payments.models import SecurityDepositEvent, TenantPayment
from payments.services import SecurityDepositLedgerService, TenantPaymentService


class PaymentsAppContextMixin(LedgerOSAppContextMixin):
    def get_setup_flow_steps(self) -> list[dict[str, Any]]:
        steps = super().get_setup_flow_steps()
        if any(step["label"] == "Record tenant payments" for step in steps):
            return steps
        steps.append(
            {
                "label": "Record tenant payments",
                "url": reverse("tenant-payment-create"),
                "summary": "Record tenant payments and security deposits in the new payments app.",
                "complete": TenantPayment.objects.exists() or SecurityDepositEvent.objects.exists(),
            }
        )
        return steps

    def get_app_context(self) -> dict[str, Any]:
        context = super().get_app_context()
        context["payments_next_step"] = {
            "tenant_payment_create_url": reverse("tenant-payment-create"),
            "tenant_payment_url": reverse("tenant-payment-list"),
            "security_deposit_create_url": reverse("security-deposit-create"),
            "security_deposit_url": reverse("security-deposit-list"),
        }
        return context


def _sync_feedback(*, status: str, success_message: str, failure_message: str, last_error: str | None = None) -> tuple[str, str]:
    if status == "sync_failed":
        detail = last_error or failure_message
        return "error", f"{failure_message} {detail}".strip()
    return "success", success_message


def _format_sync_errors(errors: list[str]) -> str:
    filtered_errors = [error.strip() for error in errors if error and error.strip()]
    return "; ".join(filtered_errors)


def _payment_sync_errors(payment: TenantPayment) -> list[str]:
    errors: list[str] = []
    if payment.sync_record and payment.sync_record.last_error:
        errors.append(payment.sync_record.last_error)
    for application in payment.applications.select_related("charge", "sync_record").all():
        sync_record = application.sync_record
        if sync_record and sync_record.status == sync_record.Status.FAILED and sync_record.last_error:
            errors.append(f"{application.charge}: {sync_record.last_error}")
    return errors


class PaymentsLandingView(PaymentsAppContextMixin, TemplateView):
    template_name = "payments/index.html"


class TenantPaymentListView(LoginRequiredMixin, PaymentsAppContextMixin, ListView):
    model = TenantPayment
    template_name = "payments/tenant_payment_list.html"
    context_object_name = "payments"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return TenantPayment.objects.select_related("tenant", "property", "sync_record").prefetch_related("applications__charge").order_by("-payment_date", "-id")

    def post(self, request, *args, **kwargs):
        payment_id = request.POST.get("payment_id", "").strip()
        action = request.POST.get("action", "").strip()
        payment = self.get_queryset().filter(pk=payment_id).first()
        if payment is None:
            messages.error(request, "Could not find that payment.")
            return HttpResponseRedirect(reverse("tenant-payment-list"))
        if action == "allocate":
            try:
                TenantPaymentService.allocate_payment_and_sync_applications(payment)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                payment.refresh_from_db()
                errors = _payment_sync_errors(payment)
                level, message = _sync_feedback(
                    status=payment.status,
                    success_message="Payment allocations refreshed.",
                    failure_message="Payment allocations refreshed, but one or more syncs failed.",
                    last_error=_format_sync_errors(errors) if errors else None,
                )
                getattr(messages, level)(request, message)
            return HttpResponseRedirect(reverse("tenant-payment-detail", args=[payment.pk]))
        if action == "sync":
            try:
                TenantPaymentService.sync_payment(payment)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                payment.refresh_from_db()
                errors = _payment_sync_errors(payment)
                level, message = _sync_feedback(
                    status=payment.status,
                    success_message="Payment sync completed.",
                    failure_message="Payment sync failed.",
                    last_error=_format_sync_errors(errors) if errors else None,
                )
                getattr(messages, level)(request, message)
            return HttpResponseRedirect(reverse("tenant-payment-detail", args=[payment.pk]))
        messages.error(request, "Unknown payment action.")
        return HttpResponseRedirect(reverse("tenant-payment-list"))


class TenantPaymentCreateView(LoginRequiredMixin, PaymentsAppContextMixin, CreateView):
    model = TenantPayment
    form_class = TenantPaymentForm
    template_name = "payments/payment_form.html"
    login_url = reverse_lazy("admin:login")

    def form_valid(self, form):
        self.object = form.save()
        return HttpResponseRedirect(reverse("tenant-payment-detail", args=[self.object.pk]))


class TenantPaymentUpdateView(LoginRequiredMixin, PaymentsAppContextMixin, UpdateView):
    model = TenantPayment
    form_class = TenantPaymentForm
    template_name = "payments/payment_form.html"
    login_url = reverse_lazy("admin:login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context

    def form_valid(self, form):
        self.object = form.save()
        return HttpResponseRedirect(reverse("tenant-payment-detail", args=[self.object.pk]))


class TenantPaymentDetailView(LoginRequiredMixin, PaymentsAppContextMixin, DetailView):
    model = TenantPayment
    template_name = "payments/payment_detail.html"
    context_object_name = "payment"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return TenantPayment.objects.select_related("tenant", "property", "sync_record").prefetch_related("applications__charge", "applications__sync_record")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.POST.get("action", "").strip()
        if action == "allocate":
            try:
                TenantPaymentService.allocate_payment_and_sync_applications(self.object)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                self.object.refresh_from_db()
                errors = _payment_sync_errors(self.object)
                level, message = _sync_feedback(
                    status=self.object.status,
                    success_message="Payment allocations refreshed.",
                    failure_message="Payment allocations refreshed, but one or more syncs failed.",
                    last_error=_format_sync_errors(errors) if errors else None,
                )
                getattr(messages, level)(request, message)
        elif action == "sync":
            try:
                TenantPaymentService.sync_payment(self.object)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                self.object.refresh_from_db()
                errors = _payment_sync_errors(self.object)
                level, message = _sync_feedback(
                    status=self.object.status,
                    success_message="Payment sync completed.",
                    failure_message="Payment sync failed.",
                    last_error=_format_sync_errors(errors) if errors else None,
                )
                getattr(messages, level)(request, message)
        return HttpResponseRedirect(reverse("tenant-payment-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object
        context["open_charges"] = (
            TenantCharge.objects.filter(property=payment.property, tenant=payment.tenant)
            .exclude(status=TenantCharge.Status.VOIDED)
            .order_by("due_date", "charge_date", "id")
        )
        context["sync_log_entries"] = [
            {
                "title": f"Payment {payment.pk} sync status",
                "status": payment.sync_record.status if payment.sync_record else "",
                "error": payment.sync_record.last_error if payment.sync_record else "",
                "response_text": (
                    json.dumps(payment.sync_record.response_payload, indent=2, sort_keys=True)
                    if payment.sync_record and payment.sync_record.response_payload is not None
                    else ""
                ),
                "updated_at": payment.sync_record.updated_at if payment.sync_record else payment.updated_at,
            }
        ] if payment.sync_record else []
        context["allocation_sync_log_entries"] = [
            {
                "title": f"Allocation {application.pk} for {application.charge}",
                "status": application.sync_record.status if application.sync_record else "",
                "error": application.sync_record.last_error if application.sync_record else "",
                "response_text": (
                    json.dumps(application.sync_record.response_payload, indent=2, sort_keys=True)
                    if application.sync_record and application.sync_record.response_payload is not None
                    else ""
                ),
                "updated_at": application.sync_record.updated_at if application.sync_record else application.updated_at,
            }
            for application in payment.applications.select_related("charge", "sync_record").all()
            if application.sync_record
        ]
        return context


class TenantPaymentArchiveView(LedgerOSCrudArchiveView):
    model = TenantPayment
    page_title = "Archive payment"
    list_url_name = "tenant-payment-list"

    def archive_object(self, obj):
        obj.status = TenantPayment.Status.VOIDED
        obj.save(update_fields=["status", "updated_at"])


class SecurityDepositEventListView(LoginRequiredMixin, PaymentsAppContextMixin, ListView):
    model = SecurityDepositEvent
    template_name = "payments/security_deposit_list.html"
    context_object_name = "events"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return SecurityDepositEvent.objects.select_related("tenant", "property", "unit", "lease", "sync_record").order_by("-event_date", "-id")

    def post(self, request, *args, **kwargs):
        event_id = request.POST.get("event_id", "").strip()
        action = request.POST.get("action", "").strip()
        event = self.get_queryset().filter(pk=event_id).first()
        if event is None:
            messages.error(request, "Could not find that deposit event.")
            return HttpResponseRedirect(reverse("security-deposit-list"))
        if action == "sync":
            try:
                TenantPaymentService.sync_security_deposit_event(event)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                event.refresh_from_db()
                level, message = _sync_feedback(
                    status=event.status,
                    success_message="Deposit event sync completed.",
                    failure_message="Deposit event sync failed.",
                    last_error=event.sync_record.last_error if event.sync_record else None,
                )
                getattr(messages, level)(request, message)
            return HttpResponseRedirect(reverse("security-deposit-detail", args=[event.pk]))
        messages.error(request, "Unknown deposit event action.")
        return HttpResponseRedirect(reverse("security-deposit-list"))


class SecurityDepositEventCreateView(LoginRequiredMixin, PaymentsAppContextMixin, CreateView):
    model = SecurityDepositEvent
    form_class = SecurityDepositEventForm
    template_name = "payments/security_deposit_form.html"
    login_url = reverse_lazy("admin:login")

    def form_valid(self, form):
        self.object = form.save()
        return HttpResponseRedirect(reverse("security-deposit-detail", args=[self.object.pk]))


class SecurityDepositEventUpdateView(LoginRequiredMixin, PaymentsAppContextMixin, UpdateView):
    model = SecurityDepositEvent
    form_class = SecurityDepositEventForm
    template_name = "payments/security_deposit_form.html"
    login_url = reverse_lazy("admin:login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context

    def form_valid(self, form):
        self.object = form.save()
        return HttpResponseRedirect(reverse("security-deposit-detail", args=[self.object.pk]))


class SecurityDepositEventDetailView(LoginRequiredMixin, PaymentsAppContextMixin, DetailView):
    model = SecurityDepositEvent
    template_name = "payments/security_deposit_detail.html"
    context_object_name = "event"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return SecurityDepositEvent.objects.select_related("tenant", "property", "unit", "lease", "sync_record")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.POST.get("action", "").strip()
        if action == "sync":
            try:
                TenantPaymentService.sync_security_deposit_event(self.object)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                self.object.refresh_from_db()
                level, message = _sync_feedback(
                    status=self.object.status,
                    success_message="Deposit event sync completed.",
                    failure_message="Deposit event sync failed.",
                    last_error=self.object.sync_record.last_error if self.object.sync_record else None,
                )
                getattr(messages, level)(request, message)
        return HttpResponseRedirect(reverse("security-deposit-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["required_amount"] = SecurityDepositLedgerService.required_amount_for_lease(self.object.lease)
        context["held_balance"] = SecurityDepositLedgerService.balance_for_lease(self.object.lease)
        return context
