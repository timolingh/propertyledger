from django import forms

from ledgeros.models import Property, Tenant, Unit
from payments.models import MaintenanceCategory, MaintenanceRequest, MaintenanceRequestEvent, Vendor
from payments.models import VendorBill


MAINTENANCE_BILL_TOKEN_SALT = "payments.maintenance-bill-handoff"


class MaintenanceRequestForm(forms.ModelForm):
    version = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = MaintenanceRequest
        fields = [
            "property",
            "unit",
            "tenant",
            "category",
            "priority",
            "description",
            "assigned_vendor",
            "target_completion_date",
            "estimated_cost",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "target_completion_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.filter(status=Property.Status.ACTIVE)
        self.fields["unit"].queryset = Unit.objects.select_related("property").filter(status=Unit.Status.ACTIVE)
        self.fields["tenant"].queryset = Tenant.objects.filter(is_active=True)
        self.fields["category"].queryset = MaintenanceCategory.objects.filter(is_active=True)
        self.fields["assigned_vendor"].queryset = Vendor.objects.filter(is_active=True)
        self.fields["version"].initial = self.instance.version if self.instance and self.instance.pk else 1
        self.fields["unit"].help_text = "Optional. The unit must belong to the selected property."
        self.fields["tenant"].help_text = "Optional. The tenant must have a lease for the selected property and unit."
        self.fields["estimated_cost"].help_text = "Optional planning estimate; this does not create an accounting entry."


class MaintenanceTransitionForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    action = forms.ChoiceField(choices=MaintenanceRequestEvent.Action.choices, widget=forms.HiddenInput)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    assigned_vendor = forms.ModelChoiceField(queryset=Vendor.objects.none(), required=False)
    closure_financial_status = forms.ChoiceField(
        choices=[("", "Select closure outcome"), *MaintenanceRequest.ClosureFinancialStatus.choices],
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_vendor"].queryset = Vendor.objects.filter(is_active=True)


class MaintenanceBillLinkForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    bill = forms.ModelChoiceField(queryset=VendorBill.objects.none())

    def __init__(self, *args, maintenance_request: MaintenanceRequest, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = VendorBill.objects.filter(
            maintenance_request__isnull=True,
            property=maintenance_request.property,
        ).select_related("vendor", "property", "unit")
        if maintenance_request.unit_id:
            queryset = queryset.filter(unit=maintenance_request.unit)
        self.fields["bill"].queryset = queryset.order_by("-bill_date", "-id")
        self.fields["version"].initial = maintenance_request.version
