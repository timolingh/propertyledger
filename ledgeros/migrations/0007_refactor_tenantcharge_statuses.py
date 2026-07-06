from django.db import migrations, models


def forwards(apps, schema_editor):
    TenantCharge = apps.get_model("ledgeros", "TenantCharge")
    TenantCharge.objects.filter(status__in=["sync_pending", "synced", "sync_failed"]).update(
        status="approved"
    )


def backwards(apps, schema_editor):
    # Sync outcomes are intentionally not restored on reverse migrations.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("ledgeros", "0006_ledgerosconnectionsettings_host_header"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenantcharge",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("approved", "Approved"),
                    ("voided", "Voided"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
