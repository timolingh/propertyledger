import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ledgeros", "0009_alter_ledgerosconnectionsettings_options"),
        ("payments", "0006_workflow_authorization_and_bill_approval"),
    ]

    operations = [
        migrations.CreateModel(
            name="MaintenanceRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("priority", models.CharField(choices=[("low", "Low"), ("normal", "Normal"), ("urgent", "Urgent"), ("emergency", "Emergency")], default="normal", max_length=16)),
                ("description", models.TextField()),
                ("target_completion_date", models.DateField(blank=True, null=True)),
                ("estimated_cost", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("source", models.CharField(choices=[("internal", "Internal staff"), ("import", "Imported"), ("api", "API")], default="internal", max_length=16)),
                ("source_reference", models.CharField(blank=True, default="", max_length=255)),
                ("status", models.CharField(choices=[("open", "Open"), ("triaged", "Triaged"), ("assigned", "Assigned"), ("in_progress", "In progress"), ("on_hold", "On hold"), ("verified", "Verified"), ("closed", "Closed"), ("cancelled", "Cancelled")], default="open", max_length=20)),
                ("version", models.PositiveIntegerField(default=1)),
                ("hold_from_status", models.CharField(blank=True, choices=[("open", "Open"), ("triaged", "Triaged"), ("assigned", "Assigned"), ("in_progress", "In progress"), ("on_hold", "On hold"), ("verified", "Verified"), ("closed", "Closed"), ("cancelled", "Cancelled")], default="", max_length=20)),
                ("closure_financial_status", models.CharField(blank=True, choices=[("invoice_pending", "Vendor invoice pending"), ("no_external_cost", "No external cost")], default="", max_length=24)),
                ("closure_notes", models.TextField(blank=True, default="")),
                ("reopen_count", models.PositiveIntegerField(default=0)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("assigned_vendor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="maintenance_requests", to="payments.vendor")),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="maintenance_requests", to="payments.maintenancecategory")),
                ("closed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="closed_maintenance_requests", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_maintenance_requests", to=settings.AUTH_USER_MODEL)),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="maintenance_requests", to="ledgeros.property")),
                ("tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="maintenance_requests", to="ledgeros.tenant")),
                ("unit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="maintenance_requests", to="ledgeros.unit")),
                ("verified_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="verified_maintenance_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="MaintenanceRequestEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("created", "Created"), ("updated", "Updated"), ("triage", "Triaged"), ("assign", "Assigned"), ("start", "Started"), ("hold", "Put on hold"), ("resume", "Resumed"), ("verify", "Verified"), ("close", "Closed"), ("reopen", "Reopened"), ("cancel", "Cancelled")], max_length=16)),
                ("from_status", models.CharField(blank=True, choices=[("open", "Open"), ("triaged", "Triaged"), ("assigned", "Assigned"), ("in_progress", "In progress"), ("on_hold", "On hold"), ("verified", "Verified"), ("closed", "Closed"), ("cancelled", "Cancelled")], default="", max_length=20)),
                ("to_status", models.CharField(choices=[("open", "Open"), ("triaged", "Triaged"), ("assigned", "Assigned"), ("in_progress", "In progress"), ("on_hold", "On hold"), ("verified", "Verified"), ("closed", "Closed"), ("cancelled", "Cancelled")], max_length=20)),
                ("reason", models.TextField(blank=True, default="")),
                ("request_version", models.PositiveIntegerField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="maintenance_request_events", to=settings.AUTH_USER_MODEL)),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="payments.maintenancerequest")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddIndex(model_name="maintenancerequest", index=models.Index(fields=["status", "priority"], name="maint_req_status_priority")),
        migrations.AddIndex(model_name="maintenancerequest", index=models.Index(fields=["property", "status"], name="maint_req_property_status")),
        migrations.AddConstraint(model_name="maintenancerequest", constraint=models.CheckConstraint(check=models.Q(("estimated_cost__isnull", True), ("estimated_cost__gte", 0), _connector="OR"), name="maintenance_estimated_cost_nonnegative")),
        migrations.AddConstraint(model_name="maintenancerequest", constraint=models.CheckConstraint(check=models.Q(("version__gte", 1)), name="maintenance_version_positive")),
    ]
