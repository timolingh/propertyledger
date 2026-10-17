from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("payments", "0004_vendor_sync_record")]
    operations = [
        migrations.AddField(model_name="vendorpayment", name="submission_id",
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True)),
        migrations.AddField(model_name="vendorpayment", name="submission_hash",
            field=models.CharField(blank=True, default="", editable=False, max_length=64)),
    ]
