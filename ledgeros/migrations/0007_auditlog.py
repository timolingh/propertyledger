from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("ledgeros", "0006_ledgerosconnectionsettings_host_header"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
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
                ("action", models.CharField(max_length=128)),
                (
                    "record_type",
                    models.CharField(max_length=128),
                ),
                ("record_id", models.CharField(max_length=64)),
                ("source", models.CharField(default="ui", max_length=64)),
                (
                    "outcome",
                    models.CharField(
                        choices=[("success", "Success"), ("failure", "Failure")],
                        default="success",
                        max_length=16,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
