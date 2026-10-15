from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ledgeros.models import Lease, Owner, Property, Tenant, Unit
from ledgeros.roles import ROLE_PROPERTY_MANAGER, ROLE_OWNER_VIEWER, assign_user_role


class RecordDetailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="manager")
        assign_user_role(self.user, ROLE_PROPERTY_MANAGER)
        self.client.force_login(self.user)
        owner = Owner.objects.create(name="Cedar Owner")
        property_obj = Property.objects.create(name="Cedar Grove", primary_owner=owner)
        unit = Unit.objects.create(property=property_obj, name="101")
        tenant = Tenant.objects.create(name="Avery", email="avery@example.com")
        lease = Lease.objects.create(unit=unit, tenant=tenant, lease_start_date=date(2026, 1, 1), base_monthly_rent_amount="1450.00")
        self.records = [("property", property_obj, "Cedar Owner"), ("unit", unit, "Cedar Grove"), ("tenant", tenant, "avery@example.com"), ("lease", lease, "1450.00")]

    def test_lists_link_to_read_only_details_and_explicit_edit(self):
        for name, obj, expected in self.records:
            with self.subTest(record=name):
                url = reverse(f"{name}-detail", args=[obj.pk])
                before = type(obj).objects.filter(pk=obj.pk).values().get()
                self.assertContains(self.client.get(reverse(f"{name}-list")), f'href="{url}">View</a>')
                response = self.client.get(url)
                self.assertContains(response, expected)
                self.assertContains(response, reverse(f"{name}-edit", args=[obj.pk]))
                content = response.content.decode().split("<main>", 1)[1]
                self.assertNotIn("<form", content)
                self.assertEqual(self.client.post(url, {"name": "Changed"}).status_code, 405)
                self.assertEqual(type(obj).objects.filter(pk=obj.pk).values().get(), before)
                self.assertEqual(self.client.get(reverse(f"{name}-detail", args=[999999])).status_code, 404)

    def test_details_keep_existing_access_rules(self):
        for name, obj, _ in self.records:
            url = reverse(f"{name}-detail", args=[obj.pk])
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302)
            assign_user_role(self.user, ROLE_OWNER_VIEWER)
            self.client.force_login(self.user)
            self.assertEqual(self.client.get(url).status_code, 403)
