from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("ledgeros", "0006_ledgerosconnectionsettings_host_header"),
    ]

    operations = [
        migrations.CreateModel(
            name="OwnerContributionDistribution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event_type", models.CharField(choices=[("contribution", "Contribution"), ("distribution", "Distribution")], max_length=20)),
                ("event_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("payment_account_name", models.CharField(blank=True, default="", max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                ("notes", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("draft", "Draft"), ("ready_to_sync", "Ready to sync"), ("posted", "Posted"), ("voided", "Voided")], default="draft", max_length=20)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="owner_activity_records", to="ledgeros.owner")),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="owner_activity_records", to="ledgeros.property")),
                ("sync_record", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="owner_activity_record", to="ledgeros.ledgerossyncrecord")),
            ],
            options={
                "ordering": ["-event_date", "-id"],
            },
        ),
    ]

