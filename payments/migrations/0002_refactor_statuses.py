from django.db import migrations, models


def forwards(apps, schema_editor):
    TenantPayment = apps.get_model("payments", "TenantPayment")
    SecurityDepositEvent = apps.get_model("payments", "SecurityDepositEvent")

    TenantPayment.objects.filter(status__in=["sync_pending", "synced", "sync_failed"]).update(
        status="ready_to_sync"
    )
    SecurityDepositEvent.objects.filter(status__in=["sync_pending", "synced", "sync_failed"]).update(
        status="ready_to_sync"
    )


def backwards(apps, schema_editor):
    # The old sync-terminal statuses are intentionally not restored.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("ledgeros", "0007_refactor_tenantcharge_statuses"),
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="securitydepositevent",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("ready_to_sync", "Ready to sync"),
                    ("voided", "Voided"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="tenantpayment",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("allocated", "Allocated"),
                    ("ready_to_sync", "Ready to sync"),
                    ("voided", "Voided"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
