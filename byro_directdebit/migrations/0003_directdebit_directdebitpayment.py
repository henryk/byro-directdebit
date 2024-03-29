# Generated by Django 2.2.1 on 2019-08-14 12:06

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0010_memberbalance"),
        (
            "byro_directdebit",
            "0002_directdebitconfiguration_debit_notification_template",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="DirectDebit",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "datetime",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("multiple", models.BooleanField(default=True)),
                ("cor1", models.BooleanField(default=False)),
                (
                    "sepa_xml",
                    models.TextField(
                        blank=True,
                        max_length=1048576,
                        null=True,
                        verbose_name="SEPA-XML file",
                    ),
                ),
                ("pain_descriptor", models.CharField(max_length=1024)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("unknown", "Unknown"),
                            ("failed", "Failed"),
                            ("transmitted", "Transmitted"),
                            ("executed", "Executed"),
                        ],
                        default="unknown",
                        max_length=11,
                    ),
                ),
                (
                    "additional_data",
                    django.contrib.postgres.fields.jsonb.JSONField(default=dict),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DirectDebitPayment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("FRST", "First (Recurring)"),
                            ("RCUR", "Reccurring"),
                            ("FNAL", "Last (Recurring)"),
                            ("OOFF", "One-off"),
                        ],
                        max_length=4,
                    ),
                ),
                ("mandate_reference", models.CharField(max_length=35)),
                ("collection_date", models.DateTimeField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("unknown", "Unknown"),
                            ("transmitted", "Transmitted"),
                            ("executed", "Executed"),
                            ("bounced", "Bounced"),
                        ],
                        default="unknown",
                        max_length=11,
                    ),
                ),
                (
                    "direct_debit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="byro_directdebit.DirectDebit",
                    ),
                ),
                (
                    "member",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="direct_debit_payments",
                        to="members.Member",
                    ),
                ),
            ],
        ),
    ]
