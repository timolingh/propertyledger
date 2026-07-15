from __future__ import annotations

from datetime import date

from django import forms
from django.db import models

from ledgeros.models import Owner, Property, Tenant
from reports.models import OwnerContributionDistribution
from reports.services import statement_period_bounds


class OwnerContributionDistributionForm(forms.ModelForm):
    class Meta:
        model = OwnerContributionDistribution
        fields = [
            "owner",
            "property",
            "event_type",
            "event_date",
            "amount",
            "payment_account_name",
            "description",
            "notes",
            "status",
        ]
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = Owner.objects.filter(is_active=True)
        self.fields["property"].queryset = Property.objects.filter(status=Property.Status.ACTIVE)
        if self.instance and self.instance.pk and not self.instance.is_editable_after_sync:
            for name in self.fields:
                if name != "notes":
                    self.fields[name].disabled = True


class OwnerStatementForm(forms.Form):
    class PeriodType(models.TextChoices):
        MONTH = "month", "Month"
        QUARTER = "quarter", "Quarter"
        YEAR = "year", "Year"
        CUSTOM = "custom", "Custom range"

    owner = forms.ModelChoiceField(queryset=Owner.objects.filter(is_active=True))
    property = forms.ModelChoiceField(queryset=Property.objects.filter(status=Property.Status.ACTIVE))
    period_type = forms.ChoiceField(choices=PeriodType.choices, initial=PeriodType.MONTH)
    period_start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    period_end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)

    def clean(self):
        cleaned_data = super().clean()
        period_type = cleaned_data.get("period_type")
        period_start = cleaned_data.get("period_start")
        period_end = cleaned_data.get("period_end")
        if period_type == self.PeriodType.CUSTOM and period_start and period_end:
            statement_period_bounds(
                period_type=period_type,
                anchor_date=period_start,
                end_date=period_end,
            )
        elif period_type == self.PeriodType.CUSTOM:
            raise forms.ValidationError("Custom ranges require both a start and end date.")
        return cleaned_data


class PropertyDateRangeForm(forms.Form):
    property = forms.ModelChoiceField(queryset=Property.objects.filter(status=Property.Status.ACTIVE), required=False)
    period_start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)
    period_end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)
    as_of_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = date.today()
        first_day = today.replace(day=1)
        self.fields["period_start"].initial = self.fields["period_start"].initial or first_day
        self.fields["period_end"].initial = self.fields["period_end"].initial or today
        self.fields["as_of_date"].initial = self.fields["as_of_date"].initial or today


class TenantLedgerReportForm(PropertyDateRangeForm):
    tenant = forms.ModelChoiceField(queryset=Tenant.objects.filter(is_active=True), required=False)


class LedgerOSDateRangeForm(forms.Form):
    period_start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)
    period_end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = date.today()
        first_day = today.replace(day=1)
        self.fields["period_start"].initial = self.fields["period_start"].initial or first_day
        self.fields["period_end"].initial = self.fields["period_end"].initial or today
