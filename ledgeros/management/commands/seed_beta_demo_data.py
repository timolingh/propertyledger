from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.management import BaseCommand, call_command

from ledgeros.models import (
    Lease,
    Owner,
    Property,
    PropertyLedgerAccountMapping,
    PropertyLedgerSetup,
    Tenant,
    TenantCharge,
    Unit,
)
from ledgeros.roles import (
    ROLE_ADMIN,
    ROLE_BOOKKEEPER,
    ROLE_PROPERTY_MANAGER,
    assign_user_role,
    ensure_role_groups,
)
from payments.models import MaintenanceCategory, Vendor, VendorBill, VendorPayment, SecurityDepositEvent


@dataclass(frozen=True)
class BetaSeedSummary:
    owner_name: str
    property_name: str
    unit_names: tuple[str, ...]
    tenant_names: tuple[str, ...]
    vendor_names: tuple[str, ...]


class Command(BaseCommand):
    help = "Seed a realistic beta-test property with setup data, vendors, tenants, and starter activity."

    DEFAULT_PASSWORD = "PropertyLedgerBeta123!"
    DEMO_USERS = (
        ("beta-admin", ROLE_ADMIN, True),
        ("beta-manager", ROLE_PROPERTY_MANAGER, False),
        ("beta-bookkeeper", ROLE_BOOKKEEPER, False),
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=self.DEFAULT_PASSWORD,
            help="Password to assign to the seeded beta demo users.",
        )

    def handle(self, *args, **options):
        password = options["password"]

        # Keep the beta seed self-contained by bootstrapping the standard setup rows.
        call_command("bootstrap_ledgeros_connection_settings")
        call_command("bootstrap_ledgeros_account_mappings")
        call_command("bootstrap_payment_workflow_settings")
        ensure_role_groups()

        summary = self.seed_demo_data(password=password)

        self.stdout.write(
            self.style.SUCCESS(
                "Beta demo data seeded: "
                f"property={summary.property_name}, "
                f"units={len(summary.unit_names)}, "
                f"tenants={len(summary.tenant_names)}, "
                f"vendors={len(summary.vendor_names)}"
            )
        )

    def seed_demo_data(self, *, password: str) -> BetaSeedSummary:
        today = date.today()
        month_start = date(today.year, today.month, 1)
        month_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])

        owner = self._upsert_owner()
        property_obj = self._upsert_property(owner=owner)
        units = self._upsert_units(property_obj=property_obj)
        tenants = self._upsert_tenants()
        leases = self._upsert_leases(property_obj=property_obj, units=units, tenants=tenants)
        vendors = self._upsert_vendors()
        categories = self._upsert_maintenance_categories()

        self._upsert_base_rent_charges(
            leases=leases,
            month_start=month_start,
            month_end=month_end,
        )
        self._upsert_manual_tenant_charge(property_obj=property_obj, month_end=month_end)
        self._upsert_vendor_bills(
            property_obj=property_obj,
            units=units,
            vendors=vendors,
            categories=categories,
            month_start=month_start,
        )
        self._upsert_vendor_payment(vendor_bill=VendorBill.objects.get(vendor=vendors[0], property=property_obj))
        self._upsert_security_deposit_events(
            property_obj=property_obj,
            leases=leases,
        )
        self._upsert_demo_users(password=password)

        return BetaSeedSummary(
            owner_name=owner.name,
            property_name=property_obj.name,
            unit_names=tuple(unit.name for unit in units),
            tenant_names=tuple(tenant.name for tenant in tenants),
            vendor_names=tuple(vendor.name for vendor in vendors),
        )

    def _upsert_owner(self) -> Owner:
        owner, _ = Owner.objects.update_or_create(
            name="Cedar Grove Holdings LLC",
            defaults={
                "email": "owner@cedargrove.test",
                "phone": "555-0100",
                "is_active": True,
            },
        )
        return owner

    def _upsert_property(self, *, owner: Owner) -> Property:
        property_obj, _ = Property.objects.update_or_create(
            name="Cedar Grove Apartments",
            defaults={
                "primary_owner": owner,
                "status": Property.Status.ACTIVE,
                "notes": "Beta test property seeded for PropertyLedger acceptance testing.",
            },
        )
        return property_obj

    def _upsert_units(self, *, property_obj: Property) -> tuple[Unit, Unit, Unit]:
        unit_names = ("101", "102", "103")
        units: list[Unit] = []
        for unit_name in unit_names:
            unit, _ = Unit.objects.update_or_create(
                property=property_obj,
                name=unit_name,
                defaults={
                    "status": Unit.Status.ACTIVE,
                    "notes": f"Beta test unit {unit_name}.",
                },
            )
            units.append(unit)
        return tuple(units)

    def _upsert_tenants(self) -> tuple[Tenant, Tenant, Tenant]:
        tenant_data = (
            ("Avery Jordan", "avery.jordan@example.test", "555-0201"),
            ("Brooke Chen", "brooke.chen@example.test", "555-0202"),
            ("Carlos Rivera", "carlos.rivera@example.test", "555-0203"),
        )
        tenants: list[Tenant] = []
        for name, email, phone in tenant_data:
            tenant, _ = Tenant.objects.update_or_create(
                name=name,
                defaults={
                    "email": email,
                    "phone": phone,
                    "is_active": True,
                    "notes": "Beta test tenant.",
                },
            )
            tenants.append(tenant)
        return tuple(tenants)

    def _upsert_leases(
        self,
        *,
        property_obj: Property,
        units: tuple[Unit, Unit, Unit],
        tenants: tuple[Tenant, Tenant, Tenant],
    ) -> tuple[Lease, Lease, Lease]:
        lease_specs = (
            (units[0], tenants[0], date(2026, 6, 1), Decimal("1450.00"), Decimal("1450.00"), "resident-manager"),
            (units[1], tenants[1], date(2026, 7, 1), Decimal("1575.00"), Decimal("1575.00"), "mid-market"),
            (units[2], tenants[2], date(2026, 7, 15), Decimal("1695.00"), Decimal("1695.00"), "new-move-in"),
        )
        leases = []
        for unit, tenant, lease_start, rent_amount, deposit_amount, note_suffix in lease_specs:
            lease, _ = unit.leases.update_or_create(
                tenant=tenant,
                lease_start_date=lease_start,
                defaults={
                    "lease_end_date": None,
                    "rent_effective_date": lease_start,
                    "base_monthly_rent_amount": rent_amount,
                    "deposit_required_amount": deposit_amount,
                    "status": "active",
                    "notes": f"Beta test lease for {note_suffix}.",
                },
            )
            leases.append(lease)
        return tuple(leases)

    def _upsert_vendors(self) -> tuple[Vendor, Vendor, Vendor]:
        vendor_data = (
            ("Ace Plumbing", "billing@aceplumbing.test"),
            ("Bright Electric", "billing@brightelectric.test"),
            ("GreenLine Landscaping", "billing@greenline.test"),
        )
        vendors: list[Vendor] = []
        for name, email in vendor_data:
            vendor, _ = Vendor.objects.update_or_create(
                name=name,
                defaults={
                    "email": email,
                    "phone": "555-0300",
                    "is_active": True,
                    "notes": "Beta test vendor.",
                },
            )
            vendors.append(vendor)
        return tuple(vendors)

    def _upsert_maintenance_categories(self) -> tuple[MaintenanceCategory, MaintenanceCategory, MaintenanceCategory]:
        category_names = ("Plumbing", "Electrical", "Landscaping")
        categories: list[MaintenanceCategory] = []
        for name in category_names:
            category, _ = MaintenanceCategory.objects.update_or_create(
                name=name,
                defaults={
                    "description": f"Beta test {name.lower()} work.",
                    "is_active": True,
                },
            )
            categories.append(category)
        return tuple(categories)

    def _upsert_base_rent_charges(
        self,
        *,
        leases: tuple[object, object, object],
        month_start: date,
        month_end: date,
    ) -> None:
        for lease in leases:
            amount = TenantCharge.prorated_amount_for_period(
                monthly_amount=lease.base_monthly_rent_amount,
                period_start=month_start,
                period_end=month_end,
                occupied_start=lease.lease_start_date,
                occupied_end=lease.lease_end_date,
            )
            TenantCharge.objects.update_or_create(
                lease=lease,
                billing_period_start=month_start,
                billing_period_end=month_end,
                charge_type=TenantCharge.ChargeType.BASE_RENT,
                defaults={
                    "property": lease.unit.property,
                    "unit": lease.unit,
                    "tenant": lease.tenant,
                    "charge_date": month_start,
                    "due_date": month_end,
                    "amount": amount,
                    "description": f"Base rent for {month_start.strftime('%B %Y')}",
                    "status": TenantCharge.Status.DRAFT,
                },
            )

    def _upsert_manual_tenant_charge(self, *, property_obj: Property, month_end: date) -> None:
        TenantCharge.objects.update_or_create(
            property=property_obj,
            unit=None,
            tenant=None,
            lease=None,
            charge_type=TenantCharge.ChargeType.OTHER_MANUAL,
            billing_period_start=None,
            billing_period_end=None,
            charge_date=month_end,
            due_date=month_end,
            defaults={
                "amount": Decimal("125.00"),
                "description": "Landscape cleanup charge",
                "status": TenantCharge.Status.DRAFT,
            },
        )

    def _upsert_vendor_bills(
        self,
        *,
        property_obj: Property,
        units: tuple[Unit, Unit, Unit],
        vendors: tuple[Vendor, Vendor, Vendor],
        categories: tuple[MaintenanceCategory, MaintenanceCategory, MaintenanceCategory],
        month_start: date,
    ) -> None:
        bill_specs = (
            (vendors[0], units[0], categories[0], Decimal("240.00"), "Replace sink trap"),
            (vendors[1], units[1], categories[1], Decimal("180.00"), "Replace hallway light ballast"),
            (vendors[2], None, categories[2], Decimal("315.00"), "Monthly landscaping service"),
        )
        for vendor, unit, category, amount, repair_notes in bill_specs:
            VendorBill.objects.update_or_create(
                vendor=vendor,
                property=property_obj,
                unit=unit,
                bill_date=month_start,
                expense_category=VendorBill.ExpenseCategory.REPAIRS_AND_MAINTENANCE,
                maintenance_category=category,
                defaults={
                    "due_date": date(month_start.year, month_start.month, calendar.monthrange(month_start.year, month_start.month)[1]),
                    "amount": amount,
                    "repair_notes": repair_notes,
                    "tenant_chargeable": False,
                    "notes": "Beta test vendor bill.",
                    "status": VendorBill.Status.DRAFT,
                },
            )

    def _upsert_vendor_payment(self, *, vendor_bill: VendorBill) -> None:
        setup = PropertyLedgerSetup.load()
        bank_mapping = setup.account_mappings.filter(
            mapping_key=PropertyLedgerAccountMapping.MappingKey.OPERATING_BANK_ACCOUNT
        ).first()
        bank_account_name = bank_mapping.ledgeros_account_name if bank_mapping else "Operating Bank"
        VendorPayment.objects.update_or_create(
            vendor=vendor_bill.vendor,
            vendor_bill=vendor_bill,
            payment_date=vendor_bill.bill_date,
            payment_method=VendorPayment.PaymentMethod.MANUAL_CHECK,
            defaults={
                "amount": vendor_bill.amount,
                "bank_account_name": bank_account_name,
                "credit_card_account_name": "",
                "memo": "Beta test vendor payment.",
                "check_number": "BETA-1001",
                "check_status": VendorPayment.CheckStatus.PENDING_PRINT,
                "is_credit_card_payoff": False,
                "notes": "Seeded beta payment for bookkeeper walkthroughs.",
                "status": VendorPayment.Status.DRAFT,
            },
        )

    def _upsert_security_deposit_events(
        self,
        *,
        property_obj: Property,
        leases: tuple[object, object, object],
    ) -> None:
        for index, lease in enumerate(leases, start=1):
            SecurityDepositEvent.objects.update_or_create(
                property=property_obj,
                unit=lease.unit,
                tenant=lease.tenant,
                lease=lease,
                event_type=SecurityDepositEvent.EventType.RECEIVED,
                event_date=lease.lease_start_date,
                defaults={
                    "amount": lease.deposit_required_amount,
                    "description": f"Security deposit received for unit {lease.unit.name}",
                    "notes": f"Beta test deposit event {index}.",
                    "status": SecurityDepositEvent.Status.DRAFT,
                },
            )

    def _upsert_demo_users(self, *, password: str) -> None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        ensure_role_groups()

        for username, role, is_superuser in self.DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.test",
                    "is_staff": is_superuser,
                    "is_superuser": is_superuser,
                },
            )
            user.email = f"{username}@example.test"
            user.is_staff = is_superuser
            user.is_superuser = is_superuser
            user.set_password(password)
            user.save()
            assign_user_role(user, role)
            if is_superuser and not user.is_staff:
                user.is_staff = True
                user.save(update_fields=["is_staff"])
