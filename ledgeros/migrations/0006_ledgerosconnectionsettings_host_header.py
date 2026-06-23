from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ledgeros", "0005_alter_property_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="ledgerosconnectionsettings",
            name="host_header",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
