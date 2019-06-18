from i18nfield.strings import LazyI18nString
from django.utils.translation import ugettext_lazy as _


MANDATE_REFERENCE_NOTIFICATION_SUBJECT = LazyI18nString.from_gettext(_('SEPA Direct Debit mandate reference notification'))
MANDATE_REFERENCE_NOTIFICATION_TEXT = LazyI18nString.from_gettext(
    _(
        '''Hi,

this is to inform you of the SEPA mandate reference we will be using in the
future to issue direct debits for your {association_name} membership fees.

 Mandate reference: {sepa_mandate_reference}
 Your IBAN on file: {sepa_iban}
 Your BIC:          {sepa_bic}
 
 Our Creditor ID:   {creditor_id}

If you have any questions relating to your member fees or you want to update
your member data, please contact us at {contact}.

{additional_information}

Thanks,
the robo clerk'''
    )
)
