from collections import Counter
import string

from django.views.generic import ListView, TemplateView, FormView
from django.utils.crypto import get_random_string
from django.db.models import Q
from django.db.transaction import atomic
from django.contrib import messages
from django import forms
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ngettext_lazy
from django.utils.timezone import now
from django.urls import reverse_lazy

from byro.common.models import Configuration
from byro.members.models import Member
from byro.plugins.sepa.models import SepaDirectDebitState
from byro.bookkeeping.special_accounts import SpecialAccounts

from byro_directdebit.models import DirectDebitConfiguration


class MemberList(ListView):
    template_name = 'byro_directdebit/list.html'
    context_object_name = 'members'
    model = Member
    paginate_by = 50

    def get_queryset(self):
        mode = self.request.GET.get('filter', 'all')

        all_members = list(Member.objects.filter(
            Q(memberships__amount__gt=0) |
            Q(bookings__debit_account=SpecialAccounts.fees_receivable)
        ).order_by('-id').distinct().all())

        if mode == 'all':
            return list(all_members)

        if mode == 'invalid_iban':
            return [m for m in all_members if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.INVALID_IBAN]

        elif mode == 'rescinded':
            return [m for m in all_members if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.RESCINDED]

        elif mode == 'bounced':
            return [m for m in all_members if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.BOUNCED]

        elif mode == 'no_bic':
            return [m for m in all_members if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.NO_BIC]

        elif mode == 'no_iban':
            return [m for m in all_members if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.NO_IBAN]

        elif mode == "no_mandate_reference":
            return [m for m in all_members if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.NO_MANDATE_REFERENCE]

        with_due_balance = [
            member for member in all_members
            if member.balance < 0
        ]

        if mode == 'with_due_balance':
            return with_due_balance

        elif mode == 'inactive':
            return [m for m in with_due_balance if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.INACTIVE]

        elif mode == "eligible":
            return [m for m in with_due_balance if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.OK]

        else:
            return list(with_due_balance)


class Dashboard(TemplateView):
    template_name = 'byro_directdebit/dashboard.html'

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        config = DirectDebitConfiguration.get_solo()

        all_members = list(Member.objects.filter(
            Q(memberships__amount__gt=0) |
            Q(bookings__debit_account=SpecialAccounts.fees_receivable)
        ).order_by('-id').distinct().all())

        with_due_balance = {
            member for member in all_members
            if member.balance < 0
        }

        counts = Counter([m.profile_sepa.sepa_direct_debit_state for m in all_members])
        w_due_counts = Counter([m.profile_sepa.sepa_direct_debit_state for m in with_due_balance])

        context.update({
            'creditor_id': config.creditor_id,
            'all_members': len(all_members),
            'with_due_balance': len(with_due_balance),
            'deactivated_sepa': w_due_counts[SepaDirectDebitState.INACTIVE],
            'no_iban': counts[SepaDirectDebitState.NO_IBAN],
            'eligible': w_due_counts[SepaDirectDebitState.OK],
            'invalid_iban': counts[SepaDirectDebitState.INVALID_IBAN],
            'no_bic': counts[SepaDirectDebitState.NO_BIC],
            'rescinded': counts[SepaDirectDebitState.RESCINDED],
            'bounced': counts[SepaDirectDebitState.BOUNCED],
            'no_mandate_reference': counts[SepaDirectDebitState.NO_MANDATE_REFERENCE],
        })

        return context


class AssignSepaMandatesForm(forms.Form):
    prefix = forms.CharField(
        max_length=35,
        required=False,
        help_text=_("A short prefix that should be part of every assigned mandate reference to help the debtor identify the creditor. Good example: Short name of your organization (3-5 characters).")
    )
    length = forms.IntegerField(
        min_value=10,
        max_value=35,
        initial=22,
        help_text=_("Length of the generated SEPA direct debit mandate references (including the prefix).")
    )

    subject = forms.CharField(required=True)
    text = forms.CharField(widget=forms.Textarea)


class AssignSepaMandatesView(FormView):
    template_name = 'byro_directdebit/assign_sepa_mandates.html'
    form_class = AssignSepaMandatesForm
    success_url = reverse_lazy('plugins:byro_directdebit:finance.directdebit.dashboard')

    @staticmethod
    def _get_members():
        all_members = list(Member.objects.filter(
            Q(memberships__amount__gt=0) |
            Q(bookings__debit_account=SpecialAccounts.fees_receivable)
        ).order_by('-id').distinct().all())

        return [
            m for m in all_members
            if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.NO_MANDATE_REFERENCE
        ]

    @staticmethod
    def _find_unused_mandate_reference(prefix, length, member, now_ = None):
        now_ = now_ or now()

        allowed_chars = [x for x in string.ascii_uppercase if not x in 'XBGIOQSZ']
        format_string = "{}{:04d}{}{}"

        member_number = member.number or "0"
        formatted_number = "{:06d}".format(int(member_number)) if member_number.isdigit() else "X{}".format(
            member_number)

        for i in range(3):
            format_params = [
                prefix,
                now_.year,
                "",
                formatted_number
            ]

            empty_len = len(format_string.format(*format_params))

            random_string = get_random_string(
                length=length - empty_len,
                allowed_chars=allowed_chars
            )

            format_params[2] = random_string

            mandate_reference = format_string.format(*format_params).upper()

            if Member.objects.filter(profile_sepa__mandate_reference=mandate_reference).count():
                mandate_reference = None
                continue
            else:
                break

        return mandate_reference

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['no_mandate_reference'] = len(self._get_members())

        return context

    def get_initial(self):
        config = DirectDebitConfiguration.get_solo()
        retval = super().get_initial()
        retval['prefix'] = config.mandate_reference_prefix
        retval['subject'] = config.mandate_reference_notification_template.subject
        retval['text'] = config.mandate_reference_notification_template.text
        return retval

    def form_valid(self, form):
        config = DirectDebitConfiguration.get_solo()
        global_config = Configuration.get_solo()
        members = self._get_members()
        now_ = now()

        error_count = 0
        success_count = 0

        for member in members:

            with atomic():
                mandate_reference = self._find_unused_mandate_reference(
                    form.cleaned_data['prefix'],
                    form.cleaned_data['length'],
                    member,
                    now_,
                )

                if not mandate_reference:
                    error_count = error_count + 1
                    continue

                context = {
                    'creditor_id': config.creditor_id,
                    'sepa_mandate_reference': mandate_reference,
                    'sepa_iban': member.profile_sepa.iban,
                    'sepa_bic': member.profile_sepa.bic_autocomplete,
                    'contact': global_config.mail_from,
                    'association_name': global_config.name,
                    'additional_information': '',
                }

                mail =  config.mandate_reference_notification_template.to_mail(
                    member.email,
                    context=context,
                    save=False
                )
                mail.save()
                mail.members.add(member)

                member.profile_sepa.mandate_reference = mandate_reference
                member.profile_sepa.save()

                member.log(self, '.updated')
                member.log(self, '.finance.sepadd.mandate_reference_assigned', mandate_reference=mandate_reference)

                success_count = success_count + 1

        if success_count:
            messages.success(
                self.request,
                ngettext_lazy(
                    "Assigned %(n)s mandate reference. Check the e-mail outbox for the notification mail.",
                    "Assigned %(n)s mandate references. Check the e-mail outbox for the notification mails.",
                    success_count
                ) % {
                    'n': success_count
                }
            )

        if error_count:
            messages.error(
                self.request,
                ngettext_lazy(
                    "%(n)s mandate reference could not be assigned.",
                    "%(n)s mandate references could not be assigned.",
                    error_count
                ) % {
                    'n': error_count
                }
            )

        if not error_count and not success_count:
            messages.warning(
                self.request,
                _("Nothing to do. Nothing done.")
            )

        return super().form_valid(form)
