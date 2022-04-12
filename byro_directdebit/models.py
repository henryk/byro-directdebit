import uuid
from enum import Enum

from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.utils.timezone import now

from byro.common.models.configuration import ByroConfiguration
from byro.common.models import LogTargetMixin


class DirectDebitConfiguration(ByroConfiguration):
    form_title = _("SEPA Direct Debit settings")

    creditor_id = models.CharField(  ## FIXME Validator
        null=True,
        blank=True,
        max_length=35,
        verbose_name=_("SEPA Creditor ID"),
    )

    mandate_reference_prefix = models.CharField(
        max_length=35,
        null=True,
        blank=True,
        verbose_name=_("SEPA Direct Debit mandate reference prefix"),
        help_text=_(
            "A short prefix that should be part of every assigned mandate reference to help the debtor identify the creditor. Good example: Short name of your organization (3-5 characters)."
        ),
    )

    mandate_reference_notification_template = models.ForeignKey(
        to="mails.MailTemplate",
        null=True,
        blank=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    debit_notification_template = models.ForeignKey(
        to="mails.MailTemplate",
        null=True,
        blank=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )


class DirectDebitState(Enum):
    UNKNOWN = "unknown"
    FAILED = "failed"
    TRANSMITTED = "transmitted"
    EXECUTED = "executed"
    BOUNCED = "bounced"


class DirectDebit(models.Model, LogTargetMixin):
    LOG_TARGET_BASE = "byro_directdebit.directdebit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    datetime = models.DateTimeField(default=now, db_index=True)

    multiple = models.BooleanField(default=True)
    cor1 = models.BooleanField(default=False)

    sepa_xml = models.TextField(
        max_length=1024 * 1024, verbose_name=_("SEPA-XML file"), null=True, blank=True
    )
    pain_descriptor = models.CharField(max_length=1024, null=False, blank=False)

    state = models.CharField(
        choices=[
            (DirectDebitState.UNKNOWN.value, _("Unknown")),
            (DirectDebitState.FAILED.value, _("Failed")),
            (DirectDebitState.TRANSMITTED.value, _("Transmitted")),
            (DirectDebitState.EXECUTED.value, _("Executed")),
        ],
        default=DirectDebitState.UNKNOWN.value,
        max_length=11,
        blank=False,
        null=False,
    )

    additional_data = models.JSONField(default=dict)


class DirectDebitPayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    type = models.CharField(
        max_length=4,
        choices=[
            ("FRST", _("First (Recurring)")),
            ("RCUR", _("Reccurring")),
            ("FNAL", _("Last (Recurring)")),
            ("OOFF", _("One-off")),
        ],
    )
    mandate_reference = models.CharField(max_length=35)
    collection_date = models.DateTimeField(null=False)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    direct_debit = models.ForeignKey(
        to=DirectDebit,
        null=False,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    member = models.ForeignKey(
        to="members.Member",
        related_name="direct_debit_payments",
        on_delete=models.PROTECT,
        null=True,
    )

    state = models.CharField(
        choices=[
            (DirectDebitState.UNKNOWN.value, _("Unknown")),
            (DirectDebitState.TRANSMITTED.value, _("Transmitted")),
            (DirectDebitState.EXECUTED.value, _("Executed")),
            (DirectDebitState.BOUNCED.value, _("Bounced")),
        ],
        default=DirectDebitState.UNKNOWN.value,
        max_length=11,
        blank=False,
        null=False,
    )
