from django.db import models
from django.utils.translation import ugettext_lazy as _

from byro.common.models.configuration import ByroConfiguration


class DirectDebitConfiguration(ByroConfiguration):
    form_title = _("SEPA Direct Debit settings")

    creditor_id = models.CharField(
        null=True, blank=True,
        max_length=35,
        verbose_name=_("SEPA Creditor ID"),
    )

    mandate_reference_prefix = models.CharField(
        max_length=35,
        null=True, blank=True,
        verbose_name=_("SEPA Direct Debit mandate reference prefix"),
        help_text=_("A short prefix that should be part of every assigned mandate reference to help the debtor identify the creditor. Good example: Short name of your organization (3-5 characters)."),
    )

    mandate_reference_notification_template = models.ForeignKey(
        to='mails.MailTemplate',
        null=True,
        blank=False,
        on_delete=models.SET_NULL,
        related_name='+',
    )
