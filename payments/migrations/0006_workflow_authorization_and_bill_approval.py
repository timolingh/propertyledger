from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def mark_legacy_posted_bills(apps, schema_editor):
    VendorBill = apps.get_model("payments", "VendorBill")
    VendorBill.objects.filter(status="posted").update(approval_status="legacy_unrecorded")


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0005_vendorpayment_submission"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowAuthorization",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("can_approve_vendor_bills", models.BooleanField(default=False)),
                ("can_pay_vendor_bills", models.BooleanField(default=False)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="propertyledger_authorization_updates", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="propertyledger_workflow_authorization", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["user__username", "user_id"]},
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="approval_status",
            field=models.CharField(choices=[("draft", "Draft"), ("submitted", "Awaiting approval"), ("approved", "Approved"), ("rejected", "Rejected"), ("withdrawn", "Withdrawn"), ("legacy_unrecorded", "Legacy / approval not recorded")], default="draft", max_length=24),
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="approved_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_vendor_bills", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="decision_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="decision_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="decided_vendor_bills", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="decision_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="submission_version",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="submitted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vendorbill",
            name="submitted_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="submitted_vendor_bills", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="vendorpayment",
            name="initiated_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="initiated_vendor_payments", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="VendorBillApprovalEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("draft", "Draft"), ("submitted", "Awaiting approval"), ("approved", "Approved"), ("rejected", "Rejected"), ("withdrawn", "Withdrawn"), ("legacy_unrecorded", "Legacy / approval not recorded")], max_length=32)),
                ("submission_version", models.PositiveIntegerField(default=0)),
                ("financial_fingerprint", models.CharField(blank=True, default="", max_length=64)),
                ("reason", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="vendor_bill_approval_events", to=settings.AUTH_USER_MODEL)),
                ("bill", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="approval_events", to="payments.vendorbill")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.RunPython(mark_legacy_posted_bills, migrations.RunPython.noop),
    ]
