from __future__ import annotations

from django import forms

from ledgeros.models import (
    Lease,
    LedgerOSConnectionSettings,
    Owner,
    Property,
    PropertyLedgerAccountMapping,
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
        self.fields["host_header"].help_text = (
            "Optional Host header override, for example localhost:8001 when Docker "
            "connects to a host-run LedgerOS instance"
        )
        self.fields["client_id"].help_text = "LedgerOS client identifier used by the adapter"
        self.fields["health_path"].help_text = (
            "LedgerOS health endpoint path, usually /api/v1/health/ for the real stack"
        )

    class Meta:
        model = LedgerOSConnectionSettings
        fields = [
            "base_url",
            "host_header",
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
        self.fields["lease"].queryset = Lease.objects.select_related(
            "unit__property", "tenant"
        ).all()
        self.fields["lease"].required = True
        self.fields["billing_period_start"].required = False
        self.fields["billing_period_end"].required = False
        self.fields["lease"].help_text = (
            "Select a lease to auto-fill property, unit, and tenant."
        )
        if (
            self.instance
            and self.instance.pk
            and self.instance.status == TenantCharge.Status.SYNCED
        ):
            for name in self.fields:
                if name not in {"due_date", "description"}:
                    self.fields[name].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        lease = cleaned_data.get("lease")
        if lease is None:
            raise forms.ValidationError({"lease": "Lease is required."})

        cleaned_data["property"] = lease.unit.property
        cleaned_data["unit"] = lease.unit
        cleaned_data["tenant"] = lease.tenant
        return cleaned_data


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


class PropertyLedgerAccountMappingForm(forms.ModelForm):
    class Meta:
        model = PropertyLedgerAccountMapping
        fields = [
            "ledgeros_account_id",
            "ledgeros_account_name",
            "ledgeros_account_type",
            "is_enabled",
            "notes",
        ]

    def __init__(self, *args, mapping_key: str, **kwargs):
        self.mapping_key = mapping_key
        super().__init__(*args, **kwargs)
        self.fields["ledgeros_account_id"].required = False
        self.fields["ledgeros_account_name"].required = False
        self.fields["ledgeros_account_type"].required = False
        self.fields["ledgeros_account_id"].help_text = "LedgerOS account code used for this mapping."
        self.fields["ledgeros_account_name"].help_text = "Friendly LedgerOS account name."
        self.fields["ledgeros_account_type"].help_text = "LedgerOS account type, such as asset, liability, expense, revenue, or equity."

    def save(self, commit=True):  # type: ignore[override]
        obj = super().save(commit=False)
        obj.mapping_key = self.mapping_key
        obj.is_required = True
        if commit:
            obj.save()
        return obj
