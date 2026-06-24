from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from django.contrib import messages
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
                "url": reverse("payments-home"),
                "summary": "Record tenant payments and security deposits in the new payments app.",
                "complete": TenantPayment.objects.exists() or SecurityDepositEvent.objects.exists(),
            }
        )
        return steps

    def get_app_context(self) -> dict[str, Any]:
        context = super().get_app_context()
        context["payments_next_step"] = {
            "tenant_payment_url": reverse("tenant-payment-list"),
            "security_deposit_url": reverse("security-deposit-list"),
        }
        return context


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
            TenantPaymentService.allocate_payment_and_sync_applications(payment)
            messages.success(request, "Payment allocations refreshed.")
            return HttpResponseRedirect(reverse("tenant-payment-detail", args=[payment.pk]))
        if action == "sync":
            TenantPaymentService.sync_payment(payment)
            messages.success(request, "Payment sync attempted.")
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
            TenantPaymentService.allocate_payment_and_sync_applications(self.object)
            messages.success(request, "Payment allocations refreshed.")
        elif action == "sync":
            TenantPaymentService.sync_payment(self.object)
            messages.success(request, "Payment sync attempted.")
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
            TenantPaymentService.sync_security_deposit_event(event)
            messages.success(request, "Deposit event sync attempted.")
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
            TenantPaymentService.sync_security_deposit_event(self.object)
            messages.success(request, "Deposit event sync attempted.")
        return HttpResponseRedirect(reverse("security-deposit-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["required_amount"] = SecurityDepositLedgerService.required_amount_for_lease(self.object.lease)
        context["held_balance"] = SecurityDepositLedgerService.balance_for_lease(self.object.lease)
        return context
