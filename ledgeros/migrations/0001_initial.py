from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="LedgerOSConnectionSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("base_url", models.URLField(blank=True)),
                ("client_id", models.CharField(blank=True, max_length=255)),
                (
                    "hmac_secret_env_var",
                    models.CharField(default="LEDGEROS_HMAC_SECRET", max_length=255),
                ),
                ("api_key_env_var", models.CharField(blank=True, default="", max_length=255)),
                ("health_path", models.CharField(default="/health/", max_length=255)),
                ("timeout_seconds", models.PositiveSmallIntegerField(default=5)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "LedgerOS connection settings",
            },
        ),
        migrations.CreateModel(
            name="LedgerOSSyncRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("local_object_type", models.CharField(max_length=255)),
                ("local_object_id", models.CharField(max_length=255)),
                ("ledgeros_resource_type", models.CharField(max_length=255)),
                ("ledgeros_resource_id", models.CharField(blank=True, max_length=255, null=True)),
                ("ledgeros_journal_entry_id", models.CharField(blank=True, max_length=255, null=True)),
                ("source_event_type", models.CharField(max_length=255)),
                ("external_id", models.CharField(max_length=255)),
                ("idempotency_key", models.CharField(max_length=64)),
                ("request_hash", models.CharField(max_length=64)),
                ("response_payload", models.JSONField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("in_progress", "In progress"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("duplicate", "Duplicate"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("last_error", models.TextField(blank=True, null=True)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="ledgerossyncrecord",
            constraint=models.UniqueConstraint(
                fields=["local_object_type", "local_object_id", "source_event_type"],
                name="ledgeros_sync_record_local_object_source_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="ledgerossyncrecord",
            constraint=models.UniqueConstraint(
                fields=["idempotency_key"],
                name="ledgeros_sync_record_idempotency_key_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="ledgerossyncrecord",
            constraint=models.UniqueConstraint(
                fields=["external_id", "source_event_type"],
                name="ledgeros_sync_record_external_id_source_unique",
            ),
        ),
    ]
