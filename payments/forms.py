from __future__ import annotations

from django import forms

from ledgeros.models import Lease, Property, Tenant, TenantCharge, Unit
from payments.models import SecurityDepositEvent, TenantPayment


class TenantPaymentForm(forms.ModelForm):
    class Meta:
        model = TenantPayment
        fields = [
            "property",
            "tenant",
            "payment_date",
            "amount",
            "payment_method",
            "reference",
            "notes",
            "status",
        ]
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.filter(status=Property.Status.ACTIVE)
        self.fields["tenant"].queryset = Tenant.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.status == TenantPayment.Status.SYNCED:
            for name in self.fields:
                if name != "notes":
                    self.fields[name].disabled = True


class SecurityDepositEventForm(forms.ModelForm):
    class Meta:
        model = SecurityDepositEvent
        fields = [
            "property",
            "unit",
            "tenant",
            "lease",
            "event_type",
            "event_date",
            "amount",
            "description",
            "notes",
            "status",
        ]
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.filter(status=Property.Status.ACTIVE)
        self.fields["unit"].queryset = Unit.objects.select_related("property").all()
        self.fields["tenant"].queryset = Tenant.objects.filter(is_active=True)
        self.fields["lease"].queryset = Lease.objects.select_related("unit__property", "tenant").all()
        if self.instance and self.instance.pk and self.instance.status == SecurityDepositEvent.Status.SYNCED:
            for name in self.fields:
                if name != "notes":
                    self.fields[name].disabled = True

