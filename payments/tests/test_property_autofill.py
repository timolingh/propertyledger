import json
from datetime import date

from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ledgeros.form_relationships import configure_property_autofill
from ledgeros.models import Lease, Owner, Property, Tenant, Unit
from payments.forms import SecurityDepositEventForm, TenantPaymentForm, VendorBillForm
from payments.maintenance_forms import MaintenanceRequestForm
from payments.models import TenantPayment


class PropertyAutofillTests(TestCase):
    def setUp(self):
        owner = Owner.objects.create(name="Owner")
        self.property = Property.objects.create(name="Building", primary_owner=owner)
        self.unit = Unit.objects.create(property=self.property, name="101")
        self.tenant = Tenant.objects.create(name="Resident")
        self.lease = Lease.objects.create(
            tenant=self.tenant, unit=self.unit, lease_start_date=date(2026, 1, 1),
            status=Lease.Status.ACTIVE,
        )

    def tenant_units(self, form):
        return json.loads(form.fields["tenant"].widget.attrs["data-tenant-units"])

    def test_forms_supply_relationships_without_writing_records(self):
        for form_class in (MaintenanceRequestForm, SecurityDepositEventForm, VendorBillForm, TenantPaymentForm):
            form = form_class()
            with CaptureQueriesContext(connection) as queries:
                configure_property_autofill(form)
            self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries))
            html = form.as_p()
            if "unit" in form.fields:
                self.assertEqual(
                    json.loads(form.fields["unit"].widget.attrs["data-unit-properties"]),
                    {str(self.unit.pk): str(self.property.pk)},
                )
            if "tenant" in form.fields:
                self.assertEqual(self.tenant_units(form), {
                    str(self.tenant.pk): {str(self.unit.pk): str(self.property.pk)},
                })
            self.assertIn("data-", html)
        self.assertEqual(Lease.objects.count(), 1)
        self.assertEqual(TenantPayment.objects.count(), 0)

    def test_multiple_active_units_are_preserved_for_explicit_choice(self):
        other = Unit.objects.create(property=self.property, name="102")
        Lease.objects.create(
            tenant=self.tenant, unit=other, lease_start_date=date(2026, 2, 1),
            status=Lease.Status.ACTIVE,
        )
        self.assertEqual(self.tenant_units(MaintenanceRequestForm())[str(self.tenant.pk)], {
            str(self.unit.pk): str(self.property.pk), str(other.pk): str(self.property.pk),
        })

    def test_ended_leases_and_unselectable_properties_are_not_suggested(self):
        self.lease.status = Lease.Status.ENDED
        self.lease.save()
        self.assertEqual(self.tenant_units(MaintenanceRequestForm()), {})
        self.lease.status = Lease.Status.ACTIVE
        self.lease.save()
        self.property.status = Property.Status.ARCHIVED
        self.property.save()
        form = MaintenanceRequestForm()
        self.assertEqual(self.tenant_units(form), {})
        self.assertEqual(json.loads(form.fields["unit"].widget.attrs["data-unit-properties"]), {})

    def test_locked_receipts_receive_no_autofill_attributes(self):
        payment = TenantPayment.objects.create(
            property=self.property, tenant=self.tenant, payment_date=date(2026, 1, 1),
            amount="100.00", status=TenantPayment.Status.POSTED,
        )
        form = TenantPaymentForm(instance=payment)
        self.assertTrue(form.fields["tenant"].disabled)
        self.assertNotIn("data-tenant-units", form.fields["tenant"].widget.attrs)
