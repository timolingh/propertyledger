from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("ledgeros", "0002_owner_propertyledgersetup_tenant_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="lease",
            name="base_monthly_rent_currency",
        ),
        migrations.RemoveField(
            model_name="lease",
            name="deposit_required_currency",
        ),
    ]
