# Generated by Django 3.2.10 on 2022-04-12 13:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("byro_directdebit", "0003_directdebit_directdebitpayment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="directdebit",
            name="additional_data",
            field=models.JSONField(default=dict),
        ),
    ]
