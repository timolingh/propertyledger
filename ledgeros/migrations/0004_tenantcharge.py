from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ledgeros", "0003_remove_lease_currency_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantCharge",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("charge_type", models.CharField(choices=[("base_rent", "Base rent"), ("utility_reimbursement", "Utility reimbursement"), ("late_fee_manual", "Late fee manual"), ("other_manual", "Other manual")], max_length=64)),
                ("billing_period_start", models.DateField(blank=True, null=True)),
                ("billing_period_end", models.DateField(blank=True, null=True)),
                ("charge_date", models.DateField()),
                ("due_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("description", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("draft", "Draft"), ("approved", "Approved"), ("sync_pending", "Sync pending"), ("synced", "Synced"), ("sync_failed", "Sync failed"), ("voided", "Voided")], default="draft", max_length=20)),
                (
                    "lease",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tenant_charges",
                        to="ledgeros.lease",
                    ),
                ),
                (
                    "property",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tenant_charges",
                        to="ledgeros.property",
                    ),
                ),
                (
                    "sync_record",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tenant_charge",
                        to="ledgeros.ledgerossyncrecord",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tenant_charges",
                        to="ledgeros.tenant",
                    ),
                ),
                (
                    "unit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tenant_charges",
                        to="ledgeros.unit",
                    ),
                ),
            ],
            options={
                "ordering": ["-charge_date", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="tenantcharge",
            constraint=models.UniqueConstraint(
                condition=models.Q(charge_type="base_rent"),
                fields=("lease", "billing_period_start", "billing_period_end"),
                name="uniq_base_rent_charge_period",
            ),
        ),
    ]
