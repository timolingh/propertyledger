from __future__ import annotations

from django import forms

from ledgeros.models import (
    Lease,
    LedgerOSConnectionSettings,
    Owner,
    Property,
    PropertyLedgerSetup,
    Tenant,
    TenantCharge,
    Unit,
)


class LedgerOSConnectionSettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["base_url"].required = True
        self.fields["client_id"].required = True
        self.fields["base_url"].help_text = (
            "LedgerOS base URL, for example https://ledgeros.example.com or "
            "http://ledgeros-web:8000 in Docker"
        )
        self.fields["client_id"].help_text = "LedgerOS client identifier used by the adapter"
        self.fields["health_path"].help_text = (
            "LedgerOS health endpoint path, usually /api/v1/health/ for the real stack"
        )

    class Meta:
        model = LedgerOSConnectionSettings
        fields = [
            "base_url",
            "client_id",
            "hmac_secret_env_var",
            "api_key_env_var",
            "health_path",
            "timeout_seconds",
        ]


class OwnerForm(forms.ModelForm):
    class Meta:
        model = Owner
        fields = ["name", "email", "phone", "is_active"]


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = ["name", "primary_owner", "status", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["primary_owner"].queryset = Owner.objects.filter(is_active=True)


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["property", "name", "status", "notes"]


class TenantForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ["name", "email", "phone", "is_active", "notes"]


class LeaseForm(forms.ModelForm):
    class Meta:
        model = Lease
        fields = [
            "unit",
            "tenant",
            "lease_start_date",
            "lease_end_date",
            "rent_effective_date",
            "base_monthly_rent_amount",
            "deposit_required_amount",
            "status",
            "notes",
        ]
        widgets = {
            "lease_start_date": forms.DateInput(attrs={"type": "date"}),
            "lease_end_date": forms.DateInput(attrs={"type": "date"}),
            "rent_effective_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = Unit.objects.select_related("property").all()
        self.fields["tenant"].queryset = Tenant.objects.filter(is_active=True)
        self.fields["rent_effective_date"].required = False
        self.fields["lease_end_date"].required = False


class TenantChargeForm(forms.ModelForm):
    class Meta:
        model = TenantCharge
        fields = [
            "property",
            "unit",
            "tenant",
            "lease",
            "charge_type",
            "billing_period_start",
            "billing_period_end",
            "charge_date",
            "due_date",
            "amount",
            "description",
            "status",
        ]
        widgets = {
            "billing_period_start": forms.DateInput(attrs={"type": "date"}),
            "billing_period_end": forms.DateInput(attrs={"type": "date"}),
            "charge_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.all()
        self.fields["unit"].queryset = Unit.objects.select_related("property").all()
        self.fields["tenant"].queryset = Tenant.objects.all()
        self.fields["lease"].queryset = Lease.objects.select_related(
            "unit__property", "tenant"
        ).all()
        self.fields["property"].required = False
        self.fields["unit"].required = False
        self.fields["tenant"].required = False
        self.fields["lease"].required = False
        self.fields["billing_period_start"].required = False
        self.fields["billing_period_end"].required = False
        if self.instance and self.instance.pk and self.instance.status == TenantCharge.Status.SYNCED:
            for name in self.fields:
                if name not in {"due_date", "description"}:
                    self.fields[name].disabled = True

class PropertyLedgerSetupForm(forms.ModelForm):
    class Meta:
        model = PropertyLedgerSetup
        fields = [
            "setup_status",
            "ledgeros_entity_id",
            "ledgeros_entity_name",
            "ledgeros_accounting_period_id",
            "ledgeros_accounting_period_name",
        ]
