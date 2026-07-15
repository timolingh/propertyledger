from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from ledgeros.models import LedgerOSSyncRecord, Property, TenantCharge
from ledgeros.views import LedgerOSAppContextMixin, LedgerOSCrudArchiveView
from payments.forms import (
    DebtServicePaymentForm,
    InvoicePaymentForm,
    MaintenanceCategoryForm,
    SecurityDepositEventForm,
    TenantPaymentForm,
    VendorBillForm,
    VendorForm,
    VendorPaymentForm,
)
from payments.models import (
    DebtServicePayment,
    MaintenanceCategory,
    SecurityDepositEvent,
    TenantPayment,
    Vendor,
    VendorBill,
    VendorPayment,
)
from payments.services import (
    DebtServicePaymentService,
    LedgerOSBankingReadService,
    MaintenanceExpenseSummaryService,
    SecurityDepositLedgerService,
    TenantPaymentService,
    VendorBillService,
    VendorPaymentService,
    VendorService,
)


class PaymentsAppContextMixin(LedgerOSAppContextMixin):
    def get_setup_flow_steps(self) -> list[dict[str, Any]]:
        steps = super().get_setup_flow_steps()
        if any(step["label"] == "Record vendor bills and expenses" for step in steps):
            return steps
        steps.append(
            {
                "label": "Record vendor bills and expenses",
                "url": reverse("vendor-bill-list"),
                "summary": "Record vendor bills, credit-card payments, and debt-service expenses.",
                "complete": VendorBill.objects.exists()
                or VendorPayment.objects.exists()
                or DebtServicePayment.objects.exists(),
            }
        )
        if any(step["label"] == "Record tenant invoices and payments" for step in steps):
            return steps
        steps.append(
            {
                "label": "Record tenant invoices and payments",
                "url": reverse("invoice-list"),
                "summary": "Review invoices, record payments against them, and track security deposits in the new payments app.",
                "complete": TenantPayment.objects.exists() or SecurityDepositEvent.objects.exists(),
            }
        )
        return steps

    def get_app_context(self) -> dict[str, Any]:
        context = super().get_app_context()
        context["payments_next_step"] = {
            "vendor_bill_list_url": reverse("vendor-bill-list"),
            "vendor_list_url": reverse("vendor-list"),
            "maintenance_category_list_url": reverse("maintenance-category-list"),
            "vendor_payment_list_url": reverse("vendor-payment-list"),
            "debt_service_payment_list_url": reverse("debt-service-payment-list"),
            "banking_dashboard_url": reverse("banking-dashboard"),
            "invoice_list_url": reverse("invoice-list"),
            "invoice_history_url": reverse("tenant-payment-list"),
            "security_deposit_create_url": reverse("security-deposit-create"),
            "security_deposit_url": reverse("security-deposit-list"),
        }
        return context


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


def _invoice_allocated_amount(invoice: TenantCharge) -> Decimal:
    total = Decimal("0.00")
    for application in invoice.payment_applications.select_related("payment").all():
        if application.payment.status != TenantPayment.Status.VOIDED:
            total += application.amount_applied
    return total.quantize(Decimal("0.01"))


def _invoice_balance_due(invoice: TenantCharge) -> Decimal:
    return (invoice.amount - _invoice_allocated_amount(invoice)).quantize(Decimal("0.01"))


def _invoice_payment_history(invoice: TenantCharge) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for application in invoice.payment_applications.select_related("payment", "sync_record").all():
        payment = application.payment
        if payment.status == TenantPayment.Status.VOIDED:
            continue
        entries.append(
            {
                "payment": payment,
                "application": application,
                "sync_status": payment.sync_record.status if payment.sync_record else "",
                "unapplied_amount": payment.unapplied_amount,
            }
        )
    entries.sort(key=lambda entry: (entry["payment"].payment_date, entry["payment"].id))
    return entries


class PaymentsCrudListView(LoginRequiredMixin, PaymentsAppContextMixin, ListView):
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


class PaymentsCrudFormView(LoginRequiredMixin, PaymentsAppContextMixin):
    login_url = reverse_lazy("admin:login")
    template_name = "ledgeros/crud_form.html"
    page_title = ""
    page_action = ""
    list_url_name = ""
    detail_url_name = ""

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
        raise NotImplementedError


class PaymentsLandingView(PaymentsAppContextMixin, TemplateView):
    template_name = "payments/index.html"


class BankingVisibilityView(LoginRequiredMixin, PaymentsAppContextMixin, TemplateView):
    login_url = reverse_lazy("admin:login")
    template_name = "payments/banking.html"

    @staticmethod
    def _format_error(exc: Exception) -> str:
        return str(exc)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bank_accounts_error = ""
        reconciliations_error = ""

        try:
            bank_accounts = LedgerOSBankingReadService.list_bank_accounts()
        except (ValidationError, RuntimeError) as exc:
            bank_accounts = []
            bank_accounts_error = self._format_error(exc)

        try:
            bank_reconciliations = LedgerOSBankingReadService.list_bank_reconciliations()
        except (ValidationError, RuntimeError) as exc:
            bank_reconciliations = []
            reconciliations_error = self._format_error(exc)

        context.update(
            {
                "bank_accounts": bank_accounts,
                "bank_accounts_error": bank_accounts_error,
                "bank_reconciliations": bank_reconciliations,
                "bank_reconciliations_error": reconciliations_error,
            }
        )
        return context


class TenantInvoiceListView(LoginRequiredMixin, PaymentsAppContextMixin, ListView):
    model = TenantCharge
    template_name = "payments/invoice_list.html"
    context_object_name = "invoices"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return (
            TenantCharge.objects.select_related("tenant", "property", "lease")
            .prefetch_related("payment_applications__payment")
            .exclude(status=TenantCharge.Status.VOIDED)
            .order_by("due_date", "charge_date", "id")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice_rows: list[dict[str, Any]] = []
        for invoice in context["invoices"]:
            allocated_amount = _invoice_allocated_amount(invoice)
            balance_due = _invoice_balance_due(invoice)
            if balance_due <= Decimal("0.00"):
                continue
            invoice_rows.append(
                {
                    "invoice": invoice,
                    "allocated_amount": allocated_amount,
                    "balance_due": balance_due,
                    "detail_url": reverse("invoice-detail", args=[invoice.pk]),
                }
            )
        context["invoice_rows"] = invoice_rows
        context["open_invoice_count"] = len(invoice_rows)
        context["total_open_balance"] = sum((row["balance_due"] for row in invoice_rows), Decimal("0.00")).quantize(Decimal("0.01"))
        return context


class TenantInvoiceDetailView(LoginRequiredMixin, PaymentsAppContextMixin, DetailView):
    model = TenantCharge
    template_name = "payments/invoice_detail.html"
    context_object_name = "invoice"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return (
            TenantCharge.objects.select_related("tenant", "property", "lease", "sync_record")
            .prefetch_related("payment_applications__payment", "payment_applications__sync_record")
        )

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = InvoicePaymentForm(request.POST)
        if form.is_valid():
            try:
                payment = TenantPaymentService.record_payment_for_charge(
                    charge=self.object,
                    payment_date=form.cleaned_data["payment_date"],
                    amount=form.cleaned_data["amount"],
                    payment_method=form.cleaned_data["payment_method"],
                    reference=form.cleaned_data["reference"],
                    notes=form.cleaned_data["notes"],
                )
            except ValidationError as exc:
                for message in exc.messages:
                    form.add_error(None, message)
            else:
                payment.refresh_from_db()
                errors = _payment_sync_errors(payment)
                sync_status = payment.sync_record.status if payment.sync_record else ""
                if sync_status == LedgerOSSyncRecord.Status.FAILED:
                    messages.warning(
                        request,
                        "Payment was recorded, but one or more allocation posts failed."
                        + (f" {_format_sync_errors(errors)}" if errors else ""),
                    )
                elif payment.remaining_amount > Decimal("0.00"):
                    messages.success(
                        request,
                        "Payment recorded locally. The excess amount is being held as tenant credit.",
                    )
                else:
                    messages.success(request, "Payment recorded locally against the invoice.")
                return HttpResponseRedirect(reverse("invoice-detail", args=[self.object.pk]))
        context = self.get_context_data(form=form)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoice = self.object
        balance_due = _invoice_balance_due(invoice)
        context["allocated_amount"] = _invoice_allocated_amount(invoice)
        context["balance_due"] = balance_due
        context["payment_form"] = kwargs.get(
            "form",
            InvoicePaymentForm(
                initial={
                    "payment_date": timezone.localdate(),
                    "amount": balance_due if balance_due > Decimal("0.00") else invoice.amount,
                }
            ),
        )
        context["payment_history"] = _invoice_payment_history(invoice)
        open_charges = (
            TenantCharge.objects.filter(property=invoice.property, tenant=invoice.tenant)
            .exclude(status=TenantCharge.Status.VOIDED)
            .order_by("due_date", "charge_date", "id")
        )
        context["open_charge_rows"] = [
            {
                "invoice": open_charge,
                "balance_due": _invoice_balance_due(open_charge),
                "detail_url": reverse("invoice-detail", args=[open_charge.pk]),
            }
            for open_charge in open_charges
        ]
        return context


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
                if errors:
                    messages.warning(
                        request,
                        "Payment allocations refreshed, but one or more posts failed."
                        + (f" {_format_sync_errors(errors)}" if errors else ""),
                    )
                else:
                    messages.success(request, "Payment allocations posted to LedgerOS.")
            return HttpResponseRedirect(reverse("tenant-payment-detail", args=[payment.pk]))
        if action == "sync":
            try:
                TenantPaymentService.sync_payment(payment)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                payment.refresh_from_db()
                errors = _payment_sync_errors(payment)
                sync_status = payment.sync_record.status if payment.sync_record else ""
                if sync_status == LedgerOSSyncRecord.Status.FAILED:
                    messages.error(
                        request,
                        "Payment post to LedgerOS failed."
                        + (f" {_format_sync_errors(errors)}" if errors else ""),
                    )
                else:
                    messages.success(request, "Payment posted to LedgerOS.")
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
                if errors:
                    messages.warning(
                        request,
                        "Payment allocations refreshed, but one or more posts failed."
                        + (f" {_format_sync_errors(errors)}" if errors else ""),
                    )
                else:
                    messages.success(request, "Payment allocations posted to LedgerOS.")
        elif action == "sync":
            try:
                TenantPaymentService.sync_payment(self.object)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                self.object.refresh_from_db()
                errors = _payment_sync_errors(self.object)
                sync_status = self.object.sync_record.status if self.object.sync_record else ""
                if sync_status == LedgerOSSyncRecord.Status.FAILED:
                    messages.error(
                        request,
                        "Payment post to LedgerOS failed."
                        + (f" {_format_sync_errors(errors)}" if errors else ""),
                    )
                else:
                    messages.success(request, "Payment posted to LedgerOS.")
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
                sync_status = event.sync_record.status if event.sync_record else ""
                if sync_status == LedgerOSSyncRecord.Status.FAILED:
                    messages.error(
                        request,
                        "Deposit event sync failed."
                        + (f" {event.sync_record.last_error}" if event.sync_record and event.sync_record.last_error else ""),
                    )
                else:
                    messages.success(request, "Deposit event sync completed.")
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
                sync_status = self.object.sync_record.status if self.object.sync_record else ""
                if sync_status == LedgerOSSyncRecord.Status.FAILED:
                    messages.error(
                        request,
                        "Deposit event sync failed."
                        + (f" {self.object.sync_record.last_error}" if self.object.sync_record and self.object.sync_record.last_error else ""),
                    )
                else:
                    messages.success(request, "Deposit event sync completed.")
            return HttpResponseRedirect(reverse("security-deposit-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["required_amount"] = SecurityDepositLedgerService.required_amount_for_lease(self.object.lease)
        context["held_balance"] = SecurityDepositLedgerService.balance_for_lease(self.object.lease)
        return context


class VendorListView(PaymentsCrudListView):
    model = Vendor
    page_title = "Vendors"
    create_url_name = "vendor-create"
    create_label = "Add vendor"

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": f"{obj.email or 'No email'} | {'active' if obj.is_active else 'inactive'}",
                "edit_url": reverse("vendor-edit", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]


class VendorCreateView(PaymentsCrudFormView, CreateView):
    model = Vendor
    form_class = VendorForm
    page_title = "Add vendor"
    page_action = "Create vendor"
    list_url_name = "vendor-list"

    def form_valid(self, form):
        self.object = form.save(commit=False)
        VendorService.save_and_sync_vendor(self.object)
        self.object.refresh_from_db()
        if self.object.sync_record and self.object.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
            messages.success(self.request, "Vendor saved and provisioned in LedgerOS.")
        elif self.object.sync_record and self.object.sync_record.status == LedgerOSSyncRecord.Status.FAILED:
            messages.warning(
                self.request,
                "Vendor saved locally, but LedgerOS provisioning failed."
                + (f" {self.object.sync_record.last_error}" if self.object.sync_record.last_error else ""),
            )
        else:
            messages.warning(
                self.request,
                "Vendor saved locally. LedgerOS provisioning is pending until setup is complete.",
            )
        return HttpResponseRedirect(reverse(self.list_url_name))


class VendorUpdateView(PaymentsCrudFormView, UpdateView):
    model = Vendor
    form_class = VendorForm
    page_title = "Edit vendor"
    page_action = "Save vendor"
    list_url_name = "vendor-list"

    def form_valid(self, form):
        self.object = form.save(commit=False)
        VendorService.save_and_sync_vendor(self.object)
        self.object.refresh_from_db()
        if self.object.sync_record and self.object.sync_record.status == LedgerOSSyncRecord.Status.SUCCEEDED:
            messages.success(self.request, "Vendor saved and provisioned in LedgerOS.")
        elif self.object.sync_record and self.object.sync_record.status == LedgerOSSyncRecord.Status.FAILED:
            messages.warning(
                self.request,
                "Vendor saved locally, but LedgerOS provisioning failed."
                + (f" {self.object.sync_record.last_error}" if self.object.sync_record.last_error else ""),
            )
        else:
            messages.warning(
                self.request,
                "Vendor saved locally. LedgerOS provisioning is pending until setup is complete.",
            )
        return HttpResponseRedirect(reverse(self.list_url_name))


class MaintenanceCategoryListView(PaymentsCrudListView):
    model = MaintenanceCategory
    page_title = "Maintenance categories"
    create_url_name = "maintenance-category-create"
    create_label = "Add category"

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": f"{obj.description or 'No description'} | {'active' if obj.is_active else 'inactive'}",
                "edit_url": reverse("maintenance-category-edit", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]


class MaintenanceCategoryCreateView(PaymentsCrudFormView, CreateView):
    model = MaintenanceCategory
    form_class = MaintenanceCategoryForm
    page_title = "Add maintenance category"
    page_action = "Create category"
    list_url_name = "maintenance-category-list"

    def form_valid(self, form):
        self.object = form.save()
        return HttpResponseRedirect(reverse(self.list_url_name))


class MaintenanceCategoryUpdateView(PaymentsCrudFormView, UpdateView):
    model = MaintenanceCategory
    form_class = MaintenanceCategoryForm
    page_title = "Edit maintenance category"
    page_action = "Save category"
    list_url_name = "maintenance-category-list"

    def form_valid(self, form):
        self.object = form.save()
        return HttpResponseRedirect(reverse(self.list_url_name))


class VendorBillListView(PaymentsCrudListView):
    model = VendorBill
    page_title = "Vendor bills"
    create_url_name = "vendor-bill-create"
    create_label = "Add bill"
    template_name = "payments/vendor_bill_list.html"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Vendor.objects.filter(is_active=True).exists() and Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create at least one active vendor and one property before adding bills.",
            "create_gate_url": reverse("vendor-list"),
            "create_gate_label": "Go to vendors",
        }

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": (
                    f"{obj.property.name}"
                    f"{' / ' + obj.unit.name if obj.unit_id else ''}"
                    f" | {obj.vendor.name} | {obj.amount} | {obj.get_status_display()}"
                ),
                "detail_url": reverse("vendor-bill-detail", kwargs={"pk": obj.pk}),
                "edit_url": reverse("vendor-bill-edit", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["maintenance_summary_rows"] = MaintenanceExpenseSummaryService.summary_rows()
        return context


class VendorBillCreateView(PaymentsCrudFormView, CreateView):
    model = VendorBill
    form_class = VendorBillForm
    page_title = "Add vendor bill"
    page_action = "Save bill"
    list_url_name = "vendor-bill-list"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Vendor.objects.filter(is_active=True).exists() and Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create at least one active vendor and one property before adding bills.",
            "create_gate_url": reverse("vendor-list"),
            "create_gate_label": "Go to vendors",
        }

    def form_valid(self, form):
        self.object = form.save(commit=False)
        VendorBillService.save_and_sync_bill(self.object)
        return HttpResponseRedirect(reverse("vendor-bill-detail", args=[self.object.pk]))


class VendorBillUpdateView(PaymentsCrudFormView, UpdateView):
    model = VendorBill
    form_class = VendorBillForm
    page_title = "Edit vendor bill"
    page_action = "Save bill"
    list_url_name = "vendor-bill-list"

    def form_valid(self, form):
        self.object = form.save(commit=False)
        VendorBillService.save_and_sync_bill(self.object)
        return HttpResponseRedirect(reverse("vendor-bill-detail", args=[self.object.pk]))


class VendorBillDetailView(LoginRequiredMixin, PaymentsAppContextMixin, DetailView):
    model = VendorBill
    template_name = "payments/vendor_bill_detail.html"
    context_object_name = "bill"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return VendorBill.objects.select_related("vendor", "property", "unit", "maintenance_category", "sync_record")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.POST.get("action", "").strip()
        if action == "sync":
            try:
                VendorBillService.sync_bill(self.object)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                self.object.refresh_from_db()
                sync_status = self.object.sync_record.status if self.object.sync_record else ""
                if sync_status == LedgerOSSyncRecord.Status.FAILED:
                    messages.error(
                        request,
                        "Vendor bill sync failed."
                        + (f" {self.object.sync_record.last_error}" if self.object.sync_record and self.object.sync_record.last_error else ""),
                    )
                else:
                    messages.success(request, "Vendor bill posted to LedgerOS.")
        return HttpResponseRedirect(reverse("vendor-bill-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bill = self.object
        context["sync_log_entries"] = [
            {
                "title": f"Bill {bill.pk} sync status",
                "status": bill.sync_record.status if bill.sync_record else "",
                "error": bill.sync_record.last_error if bill.sync_record else "",
                "response_text": (
                    json.dumps(bill.sync_record.response_payload, indent=2, sort_keys=True)
                    if bill.sync_record and bill.sync_record.response_payload is not None
                    else ""
                ),
                "updated_at": bill.sync_record.updated_at if bill.sync_record else bill.updated_at,
            }
        ] if bill.sync_record else []
        return context


class VendorPaymentListView(PaymentsCrudListView):
    model = VendorPayment
    page_title = "Vendor payments"
    create_url_name = "vendor-payment-create"
    create_label = "Add payment"

    def get_create_gate_context(self) -> dict[str, Any]:
        if VendorBill.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create a vendor bill before recording a vendor payment.",
            "create_gate_url": reverse("vendor-bill-list"),
            "create_gate_label": "Go to bills",
        }

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": (
                    f"{obj.vendor.name} | {obj.vendor_bill.pk} | {obj.amount} | "
                    f"{obj.get_payment_method_display()} | {obj.get_status_display()}"
                ),
                "detail_url": reverse("vendor-payment-detail", kwargs={"pk": obj.pk}),
                "edit_url": reverse("vendor-payment-edit", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]


class VendorPaymentCreateView(PaymentsCrudFormView, CreateView):
    model = VendorPayment
    form_class = VendorPaymentForm
    page_title = "Add vendor payment"
    page_action = "Save payment"
    list_url_name = "vendor-payment-list"

    def get_create_gate_context(self) -> dict[str, Any]:
        if VendorBill.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create a vendor bill before recording a vendor payment.",
            "create_gate_url": reverse("vendor-bill-list"),
            "create_gate_label": "Go to bills",
        }

    def form_valid(self, form):
        self.object = form.save(commit=False)
        VendorPaymentService.save_and_sync_payment(self.object)
        return HttpResponseRedirect(reverse("vendor-payment-detail", args=[self.object.pk]))


class VendorPaymentUpdateView(PaymentsCrudFormView, UpdateView):
    model = VendorPayment
    form_class = VendorPaymentForm
    page_title = "Edit vendor payment"
    page_action = "Save payment"
    list_url_name = "vendor-payment-list"

    def form_valid(self, form):
        self.object = form.save(commit=False)
        VendorPaymentService.save_and_sync_payment(self.object)
        return HttpResponseRedirect(reverse("vendor-payment-detail", args=[self.object.pk]))


class VendorPaymentDetailView(LoginRequiredMixin, PaymentsAppContextMixin, DetailView):
    model = VendorPayment
    template_name = "payments/vendor_payment_detail.html"
    context_object_name = "payment"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return VendorPayment.objects.select_related("vendor", "vendor_bill", "vendor_bill__sync_record", "sync_record")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.POST.get("action", "").strip()
        if action == "sync":
            try:
                VendorPaymentService.sync_payment(self.object)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                self.object.refresh_from_db()
                sync_status = self.object.sync_record.status if self.object.sync_record else ""
                if sync_status == LedgerOSSyncRecord.Status.FAILED:
                    messages.error(
                        request,
                        "Vendor payment sync failed."
                        + (f" {self.object.sync_record.last_error}" if self.object.sync_record and self.object.sync_record.last_error else ""),
                    )
                else:
                    messages.success(request, "Vendor payment posted to LedgerOS.")
        return HttpResponseRedirect(reverse("vendor-payment-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object
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


class DebtServicePaymentListView(PaymentsCrudListView):
    model = DebtServicePayment
    page_title = "Debt service payments"
    create_url_name = "debt-service-payment-create"
    create_label = "Add payment"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Vendor.objects.filter(is_active=True).exists() and Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create an active vendor and a property before recording debt-service payments.",
            "create_gate_url": reverse("vendor-list"),
            "create_gate_label": "Go to vendors",
        }

    def get_rows(self, objects):
        return [
            {
                "object": obj,
                "summary": f"{obj.property.name} | {obj.lender.name} | {obj.total_amount} | {obj.get_status_display()}",
                "detail_url": reverse("debt-service-payment-detail", kwargs={"pk": obj.pk}),
                "edit_url": reverse("debt-service-payment-edit", kwargs={"pk": obj.pk}),
            }
            for obj in objects
        ]


class DebtServicePaymentCreateView(PaymentsCrudFormView, CreateView):
    model = DebtServicePayment
    form_class = DebtServicePaymentForm
    page_title = "Add debt service payment"
    page_action = "Save payment"
    list_url_name = "debt-service-payment-list"

    def get_create_gate_context(self) -> dict[str, Any]:
        if Vendor.objects.filter(is_active=True).exists() and Property.objects.exists():
            return super().get_create_gate_context()
        return {
            "create_available": False,
            "create_gate_message": "Create an active vendor and a property before recording debt-service payments.",
            "create_gate_url": reverse("vendor-list"),
            "create_gate_label": "Go to vendors",
        }

    def form_valid(self, form):
        self.object = form.save(commit=False)
        DebtServicePaymentService.save_and_sync_payment(self.object)
        return HttpResponseRedirect(reverse("debt-service-payment-detail", args=[self.object.pk]))


class DebtServicePaymentUpdateView(PaymentsCrudFormView, UpdateView):
    model = DebtServicePayment
    form_class = DebtServicePaymentForm
    page_title = "Edit debt service payment"
    page_action = "Save payment"
    list_url_name = "debt-service-payment-list"

    def form_valid(self, form):
        self.object = form.save(commit=False)
        DebtServicePaymentService.save_and_sync_payment(self.object)
        return HttpResponseRedirect(reverse("debt-service-payment-detail", args=[self.object.pk]))


class DebtServicePaymentDetailView(LoginRequiredMixin, PaymentsAppContextMixin, DetailView):
    model = DebtServicePayment
    template_name = "payments/debt_service_payment_detail.html"
    context_object_name = "payment"
    login_url = reverse_lazy("admin:login")

    def get_queryset(self):
        return DebtServicePayment.objects.select_related("property", "lender", "sync_record")

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.POST.get("action", "").strip()
        if action == "sync":
            try:
                DebtServicePaymentService.sync_payment(self.object)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                self.object.refresh_from_db()
                sync_status = self.object.sync_record.status if self.object.sync_record else ""
                if sync_status == LedgerOSSyncRecord.Status.FAILED:
                    messages.error(
                        request,
                        "Debt service payment sync failed."
                        + (f" {self.object.sync_record.last_error}" if self.object.sync_record and self.object.sync_record.last_error else ""),
                    )
                else:
                    messages.success(request, "Debt service payment posted to LedgerOS.")
        return HttpResponseRedirect(reverse("debt-service-payment-detail", args=[self.object.pk]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object
        context["sync_log_entries"] = [
            {
                "title": f"Debt service payment {payment.pk} sync status",
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
