from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ledgeros", "0007_auditlog"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoleLandingPage",
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
                ("group_name", models.CharField(max_length=255, unique=True)),
                ("landing_url_name", models.CharField(max_length=255)),
                ("priority", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ["priority", "group_name", "id"],
            },
        ),
    ]
