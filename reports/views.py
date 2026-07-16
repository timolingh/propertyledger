from __future__ import annotations

import csv
from decimal import Decimal
from io import StringIO
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from ledgeros.audit import audit_success
from ledgeros.permissions import BookkeepingRoleRequiredMixin, ReportingRoleRequiredMixin
from ledgeros.models import Owner, Property
from payments.models import VendorBill
from reports.forms import (
    LedgerOSDateRangeForm,
    OwnerContributionDistributionForm,
    OwnerStatementForm,
    PropertyDateRangeForm,
    TenantLedgerReportForm,
)
from reports.models import OwnerContributionDistribution
from reports.services import (
    LedgerOSReportReadService,
    OwnerActivityService,
    OwnerStatementService,
    PropertyReportService,
    statement_period_bounds,
)
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


class ReportsLandingView(ReportingRoleRequiredMixin, ReportsAppContextMixin, TemplateView):
    login_url = reverse_lazy("login")
    template_name = "reports/index.html"
    allowed_roles = ReportingRoleRequiredMixin.allowed_roles

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["property_reports"] = [
            {"label": "Rent roll", "url": reverse("rent-roll-report"), "description": "Lease-based rent roll and active occupancy."},
            {"label": "Tenant ledger", "url": reverse("tenant-ledger-report"), "description": "Synced charge and payment ledger with running balance."},
            {"label": "Delinquency", "url": reverse("delinquency-report"), "description": "Open balances past due as of a chosen date."},
            {"label": "Property income / expense", "url": reverse("property-income-expense-report"), "description": "Accrual income, expenses, and cash collections memo."},
            {"label": "Owner statement", "url": reverse("owner-statement-report"), "description": "Read-only statement preview in the reports hub."},
            {"label": "Security deposit ledger", "url": reverse("security-deposit-ledger-report"), "description": "Required, received, deducted, and refunded deposit activity."},
            {"label": "Management fee summary", "url": reverse("management-fee-expense-summary-report"), "description": "Manual management-fee expenses recorded through vendor bills."},
            {"label": "Maintenance summary", "url": reverse("maintenance-expense-summary-report"), "description": "Maintenance-category bills and totals."},
        ]
        context["ledgeros_reports"] = [
            {"label": "Trial balance", "url": reverse("ledgeros-trial-balance-report"), "description": "LedgerOS trial balance rendered in PropertyLedger."},
            {"label": "Profit and loss", "url": reverse("ledgeros-profit-and-loss-report"), "description": "LedgerOS P&L rendered in PropertyLedger."},
            {"label": "Balance sheet", "url": reverse("ledgeros-balance-sheet-report"), "description": "LedgerOS balance sheet rendered in PropertyLedger."},
            {"label": "Period summary", "url": reverse("ledgeros-period-summary-report"), "description": "LedgerOS period summary rendered in PropertyLedger."},
            {"label": "Tax summary", "url": reverse("ledgeros-tax-summary-report"), "description": "LedgerOS tax summary rendered in PropertyLedger."},
            {"label": "Chart of accounts", "url": reverse("ledgeros-chart-of-accounts-report"), "description": "LedgerOS chart of accounts rendered in PropertyLedger."},
            {"label": "Invoice status", "url": reverse("ledgeros-invoice-status-report"), "description": "LedgerOS invoice status rendered in PropertyLedger."},
            {"label": "Bill status", "url": reverse("ledgeros-bill-status-report"), "description": "LedgerOS bill status rendered in PropertyLedger."},
            {"label": "Payment status", "url": reverse("ledgeros-payment-status-report"), "description": "LedgerOS payment status rendered in PropertyLedger."},
            {"label": "Bank balances", "url": reverse("ledgeros-bank-balances-report"), "description": "LedgerOS bank balances rendered in PropertyLedger."},
            {"label": "Reconciliation status", "url": reverse("ledgeros-reconciliation-status-report"), "description": "LedgerOS reconciliation status rendered in PropertyLedger."},
            {"label": "Audit drilldown", "url": reverse("ledgeros-audit-drilldown-report"), "description": "LedgerOS audit drilldown rendered in PropertyLedger."},
        ]
        context["owner_activity_list_url"] = reverse("owner-activity-list")
        context["create_owner_activity_url"] = reverse("owner-activity-create")
        context["pending_sync_url"] = reverse("owner-activity-pending-sync")
        return context


class OwnerContributionDistributionListView(ReportingRoleRequiredMixin, ReportsAppContextMixin, ListView):
    login_url = reverse_lazy("login")
    model = OwnerContributionDistribution
    template_name = "reports/owner_activity_list.html"
    context_object_name = "activities"
    allowed_roles = ReportingRoleRequiredMixin.allowed_roles

    def get_queryset(self):
        return OwnerContributionDistribution.objects.select_related("owner", "property", "sync_record")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["create_url"] = reverse("owner-activity-create")
        return context


class OwnerContributionDistributionCreateView(BookkeepingRoleRequiredMixin, ReportsAppContextMixin, CreateView):
    login_url = reverse_lazy("login")
    model = OwnerContributionDistribution
    form_class = OwnerContributionDistributionForm
    template_name = "ledgeros/crud_form.html"
    success_url = reverse_lazy("owner-activity-list")
    page_title = "Owner activity"
    page_action = "Save owner activity"
    list_url_name = "owner-activity-list"
    allowed_roles = BookkeepingRoleRequiredMixin.allowed_roles

    def form_valid(self, form):
        response = super().form_valid(form)
        audit_success(
            action="owner_activity_created",
            record=self.object,
            user=self.request.user,
            source="ui",
        )
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


class OwnerContributionDistributionUpdateView(BookkeepingRoleRequiredMixin, ReportsAppContextMixin, UpdateView):
    login_url = reverse_lazy("login")
    model = OwnerContributionDistribution
    form_class = OwnerContributionDistributionForm
    template_name = "ledgeros/crud_form.html"
    success_url = reverse_lazy("owner-activity-list")
    page_title = "Owner activity"
    page_action = "Update owner activity"
    list_url_name = "owner-activity-list"
    allowed_roles = BookkeepingRoleRequiredMixin.allowed_roles

    def form_valid(self, form):
        response = super().form_valid(form)
        audit_success(
            action="owner_activity_updated",
            record=self.object,
            user=self.request.user,
            source="ui",
        )
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


class OwnerContributionDistributionDetailView(ReportingRoleRequiredMixin, ReportsAppContextMixin, DetailView):
    login_url = reverse_lazy("login")
    model = OwnerContributionDistribution
    template_name = "reports/owner_activity_detail.html"
    context_object_name = "activity"
    allowed_roles = ReportingRoleRequiredMixin.allowed_roles

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["edit_url"] = reverse("owner-activity-edit", kwargs={"pk": self.object.pk})
        context["list_url"] = reverse("owner-activity-list")
        return context


class OwnerContributionDistributionArchiveView(LedgerOSCrudArchiveView):
    login_url = reverse_lazy("login")
    model = OwnerContributionDistribution
    success_url = reverse_lazy("owner-activity-list")
    page_title = "Owner activity"
    list_url_name = "owner-activity-list"
    allowed_roles = BookkeepingRoleRequiredMixin.allowed_roles

    def archive_object(self, obj):
        obj.status = OwnerContributionDistribution.Status.VOIDED
        obj.save(update_fields=["status", "updated_at"])
        audit_success(
            action="owner_activity_archived",
            record=obj,
            user=self.request.user,
            source="ui",
        )


class OwnerStatementView(ReportingRoleRequiredMixin, ReportsAppContextMixin, TemplateView):
    login_url = reverse_lazy("login")
    template_name = "reports/owner_statement.html"
    allowed_roles = ReportingRoleRequiredMixin.allowed_roles

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


class OwnerStatementExportView(ReportingRoleRequiredMixin, ReportsAppContextMixin, TemplateView):
    login_url = reverse_lazy("login")
    allowed_roles = ReportingRoleRequiredMixin.allowed_roles

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


class OwnerPendingSyncReportView(ReportingRoleRequiredMixin, ReportsAppContextMixin, TemplateView):
    login_url = reverse_lazy("login")
    template_name = "reports/pending_sync.html"
    allowed_roles = ReportingRoleRequiredMixin.allowed_roles

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


def _dict_list_columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in columns:
                columns.append(key)
    return columns


def _normalize_remote_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        dict_rows = [item for item in payload if isinstance(item, dict)]
        if dict_rows:
            columns = _dict_list_columns(dict_rows)
            return {
                "summary_items": [],
                "sections": [
                    {
                        "title": "Report results",
                        "summary": "LedgerOS returned a tabular report payload.",
                        "columns": [column.replace("_", " ").title() for column in columns],
                        "rows": [[row.get(column, "") for column in columns] for row in dict_rows],
                        "empty_message": "No rows were returned.",
                    }
                ],
            }
        return {
            "summary_items": [("Rows", len(payload))],
            "sections": [],
        }
    if isinstance(payload, dict):
        summary_items: list[tuple[str, Any]] = []
        sections: list[dict[str, Any]] = []
        for key, value in payload.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                columns = _dict_list_columns([item for item in value if isinstance(item, dict)])
                sections.append(
                    {
                        "title": key.replace("_", " ").title(),
                        "summary": "",
                        "columns": [column.replace("_", " ").title() for column in columns],
                        "rows": [[row.get(column, "") for column in columns] for row in value if isinstance(row, dict)],
                        "empty_message": "No rows were returned.",
                    }
                )
            elif isinstance(value, list):
                sections.append(
                    {
                        "title": key.replace("_", " ").title(),
                        "summary": "",
                        "columns": ["Value"],
                        "rows": [[item] for item in value],
                        "empty_message": "No values were returned.",
                    }
                )
            elif isinstance(value, dict):
                nested_rows = [[nested_key, nested_value] for nested_key, nested_value in value.items()]
                sections.append(
                    {
                        "title": key.replace("_", " ").title(),
                        "summary": "",
                        "columns": ["Field", "Value"],
                        "rows": nested_rows,
                        "empty_message": "No values were returned.",
                    }
                )
            else:
                summary_items.append((key.replace("_", " ").title(), value))
        return {"summary_items": summary_items, "sections": sections}
    return {"summary_items": [("Value", payload)], "sections": []}


class ReportsBaseView(ReportingRoleRequiredMixin, ReportsAppContextMixin, TemplateView):
    login_url = reverse_lazy("login")
    template_name = "reports/report_page.html"
    form_class = None
    report_title = ""
    report_summary = ""
    report_note = ""
    alternate_url = ""
    alternate_label = ""
    allowed_roles = ReportingRoleRequiredMixin.allowed_roles

    def get_form(self):
        if self.form_class is None:
            return None
        return self.form_class(self.request.GET)

    def build_report(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_form()
        context["form"] = form
        context["report_title"] = self.report_title
        context["report_summary"] = self.report_summary
        context["report_note"] = self.report_note
        context["alternate_url"] = self.alternate_url
        context["alternate_label"] = self.alternate_label
        context["summary_items"] = []
        context["sections"] = []
        context["error_message"] = ""
        if form is not None and form.is_valid():
            try:
                context.update(self.get_report_context(form.cleaned_data))
            except (ValidationError, RuntimeError) as exc:
                context["error_message"] = "; ".join(getattr(exc, "messages", [str(exc)]))
        return context


class RentRollReportView(ReportsBaseView):
    form_class = PropertyDateRangeForm
    report_title = "Rent Roll"
    report_summary = "View active lease-based rent roll by property and unit."
    report_note = "This report is interactive and CSV export remains on the roadmap."

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return PropertyReportService.rent_roll(
            property_obj=cleaned_data.get("property"),
            as_of_date=cleaned_data.get("as_of_date"),
        )


class TenantLedgerReportView(ReportsBaseView):
    form_class = TenantLedgerReportForm
    report_title = "Tenant Ledger"
    report_summary = "Review synced tenant charges and payments with running balances."
    report_note = "This report is interactive and CSV export remains on the roadmap."

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return PropertyReportService.tenant_ledger(
            property_obj=cleaned_data.get("property"),
            tenant=cleaned_data.get("tenant"),
            period_start=cleaned_data.get("period_start"),
            period_end=cleaned_data.get("period_end"),
        )


class DelinquencyReportView(ReportsBaseView):
    form_class = PropertyDateRangeForm
    report_title = "Delinquency Report"
    report_summary = "Show synced charges with outstanding balances past due."
    report_note = "This report is interactive and CSV export remains on the roadmap."

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return PropertyReportService.delinquency(
            property_obj=cleaned_data.get("property"),
            as_of_date=cleaned_data.get("as_of_date"),
        )


class PropertyIncomeExpenseReportView(ReportsBaseView):
    form_class = PropertyDateRangeForm
    report_title = "Property Income / Expense"
    report_summary = "View accrual income and expenses alongside a cash collections memo."
    report_note = "This report is interactive and CSV export remains on the roadmap."

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return PropertyReportService.property_income_expense(
            property_obj=cleaned_data.get("property"),
            period_start=cleaned_data.get("period_start"),
            period_end=cleaned_data.get("period_end"),
        )


class OwnerStatementReportView(ReportsBaseView):
    form_class = OwnerStatementForm
    report_title = "Owner Statement Report"
    report_summary = "Read-only owner statement preview for reports navigation."
    report_note = "Use the linked Epic 7 owner statement page for preview/export workflows."
    alternate_url = reverse_lazy("owner-statement")
    alternate_label = "Open Epic 7 statement"

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        statement = OwnerStatementService.build_statement(
            owner=cleaned_data["owner"],
            property_obj=cleaned_data["property"],
            period_type=cleaned_data["period_type"],
            period_start=cleaned_data["period_start"],
            period_end=cleaned_data["period_end"],
        )
        return {
            "summary_items": [
                ("Owner", statement["owner"]),
                ("Property", statement["property"]),
                ("Period start", statement["period_start"]),
                ("Period end", statement["period_end"]),
                ("Net summary", statement["net_summary"]),
            ],
            "sections": [
                {
                    "title": "Statement totals",
                    "summary": "Official statement totals use synced records only.",
                    "columns": ["Metric", "Amount"],
                    "rows": [
                        ["Rent charged", statement["rent_charged"]],
                        ["Rent collected", statement["rent_collected"]],
                        ["Property expenses", statement["property_expenses"]],
                        ["Maintenance expenses", statement["maintenance_expenses"]],
                        ["Management fee expenses", statement["management_fee_expenses"]],
                        ["Owner contributions", statement["contributions"]],
                        ["Owner distributions", statement["distributions"]],
                        ["Security deposit received", statement["deposit_received"]],
                        ["Security deposit deducted", statement["deposit_deducted"]],
                        ["Security deposit refunded", statement["deposit_refunded"]],
                    ],
                    "empty_message": "No totals available.",
                }
            ],
        }


class SecurityDepositLedgerReportView(ReportsBaseView):
    form_class = PropertyDateRangeForm
    report_title = "Security Deposit Ledger"
    report_summary = "Track required, received, deducted, and refunded deposit activity."
    report_note = "This report is interactive and CSV export remains on the roadmap."

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return PropertyReportService.security_deposit_ledger(
            property_obj=cleaned_data.get("property"),
            period_start=cleaned_data.get("period_start"),
            period_end=cleaned_data.get("period_end"),
        )


class ManagementFeeExpenseSummaryReportView(ReportsBaseView):
    form_class = PropertyDateRangeForm
    report_title = "Management Fee Expense Summary"
    report_summary = "Summarize manual management-fee expenses recorded through vendor bills."
    report_note = "This report is interactive and CSV export remains on the roadmap."

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return PropertyReportService.management_fee_expense_summary(
            property_obj=cleaned_data.get("property"),
            period_start=cleaned_data.get("period_start"),
            period_end=cleaned_data.get("period_end"),
        )


class MaintenanceExpenseSummaryReportView(ReportsBaseView):
    form_class = PropertyDateRangeForm
    report_title = "Maintenance Expense Summary"
    report_summary = "Summarize maintenance-category bills and related expense totals."
    report_note = "This report is interactive and CSV export remains on the roadmap."

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        return PropertyReportService.maintenance_expense_summary(
            property_obj=cleaned_data.get("property"),
            period_start=cleaned_data.get("period_start"),
            period_end=cleaned_data.get("period_end"),
        )


class LedgerOSReportView(ReportsBaseView):
    form_class = LedgerOSDateRangeForm
    report_key = ""
    report_title = ""
    report_summary = ""
    report_note = "LedgerOS data is rendered inside PropertyLedger and remains read-only."

    def get_report_context(self, cleaned_data: dict[str, Any]) -> dict[str, Any]:
        query_params = {
            "start_date": cleaned_data.get("period_start"),
            "end_date": cleaned_data.get("period_end"),
        }
        payload = LedgerOSReportReadService.fetch_report(self.report_key, query_params=query_params)
        normalized = _normalize_remote_payload(payload)
        normalized["summary_items"] = normalized.get("summary_items", []) + [
            ("LedgerOS report", self.report_title),
        ]
        return normalized


class LedgerOSTrialBalanceReportView(LedgerOSReportView):
    report_key = "trial_balance"
    report_title = "LedgerOS Trial Balance"
    report_summary = "Read the LedgerOS trial balance inside PropertyLedger."


class LedgerOSProfitAndLossReportView(LedgerOSReportView):
    report_key = "profit_and_loss"
    report_title = "LedgerOS Profit and Loss"
    report_summary = "Read the LedgerOS profit and loss report inside PropertyLedger."


class LedgerOSBalanceSheetReportView(LedgerOSReportView):
    report_key = "balance_sheet"
    report_title = "LedgerOS Balance Sheet"
    report_summary = "Read the LedgerOS balance sheet inside PropertyLedger."


class LedgerOSPeriodSummaryReportView(LedgerOSReportView):
    report_key = "period_summary"
    report_title = "LedgerOS Period Summary"
    report_summary = "Read the LedgerOS period summary inside PropertyLedger."


class LedgerOSTaxSummaryReportView(LedgerOSReportView):
    report_key = "tax_summary"
    report_title = "LedgerOS Tax Summary"
    report_summary = "Read the LedgerOS tax summary inside PropertyLedger."


class LedgerOSChartOfAccountsReportView(LedgerOSReportView):
    report_key = "chart_of_accounts"
    report_title = "LedgerOS Chart of Accounts"
    report_summary = "Read the LedgerOS chart of accounts inside PropertyLedger."


class LedgerOSInvoiceStatusReportView(LedgerOSReportView):
    report_key = "invoice_status"
    report_title = "LedgerOS Invoice Status"
    report_summary = "Read synced invoice status inside PropertyLedger."


class LedgerOSBillStatusReportView(LedgerOSReportView):
    report_key = "bill_status"
    report_title = "LedgerOS Bill Status"
    report_summary = "Read synced bill status inside PropertyLedger."


class LedgerOSPaymentStatusReportView(LedgerOSReportView):
    report_key = "payment_status"
    report_title = "LedgerOS Payment Status"
    report_summary = "Read synced payment status inside PropertyLedger."


class LedgerOSBankBalancesReportView(LedgerOSReportView):
    report_key = "bank_balances"
    report_title = "LedgerOS Bank Balances"
    report_summary = "Read bank balances inside PropertyLedger."


class LedgerOSReconciliationStatusReportView(LedgerOSReportView):
    report_key = "reconciliation_status"
    report_title = "LedgerOS Reconciliation Status"
    report_summary = "Read reconciliation status inside PropertyLedger."


class LedgerOSAuditDrilldownReportView(LedgerOSReportView):
    report_key = "audit_drilldown"
    report_title = "LedgerOS Audit Drilldown"
    report_summary = "Read audit drilldown data inside PropertyLedger."
