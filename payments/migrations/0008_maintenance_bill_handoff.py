import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0007_maintenance_request_workflow"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendorbill",
            name="maintenance_request",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="vendor_bills", to="payments.maintenancerequest"),
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="maintenance_submission_id",
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="maintenancerequestevent",
            name="action",
            field=models.CharField(choices=[("created", "Created"), ("updated", "Updated"), ("triage", "Triaged"), ("assign", "Assigned"), ("start", "Started"), ("hold", "Put on hold"), ("resume", "Resumed"), ("verify", "Verified"), ("close", "Closed"), ("reopen", "Reopened"), ("cancel", "Cancelled"), ("bill_linked", "Vendor bill linked"), ("bill_unlinked", "Vendor bill unlinked")], max_length=16),
        ),
    ]
