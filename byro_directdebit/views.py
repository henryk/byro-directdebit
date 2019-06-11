from collections import Counter

from django.views.generic import ListView, TemplateView

from byro.members.models import Member
from byro.plugins.sepa.models import SepaDirectDebitState



class MemberList(ListView):
    template_name = 'byro_directdebit/list.html'
    context_object_name = 'members'
    model = Member
    paginate_by = 50

    def get_queryset(self):
        mode = self.request.GET.get('filter', 'all')

        all_members = sorted(Member.objects.all(), key= lambda m: m.pk)

        if mode == 'all':
            return list(all_members)

        with_due_balance = [
            member for member in all_members
            if member.balance < 0
        ]

        if mode == 'invalid_iban':
            return [m for m in with_due_balance if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.INVALID_IBAN]

        elif mode == 'inactive':
            return [m for m in with_due_balance if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.INACTIVE]

        elif mode == 'rescinded':
            return [m for m in with_due_balance if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.RESCINDED]

        elif mode == 'bounced':
            return [m for m in with_due_balance if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.BOUNCED]

        elif mode == 'no_bic':
            return [m for m in with_due_balance if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.NO_BIC]

        elif mode == "no_mandate_reference":
            return [m for m in with_due_balance if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.NO_MANDATE_REFERENCE]

        else:
            return list(with_due_balance)


class Dashboard(TemplateView):
    template_name = 'byro_directdebit/dashboard.html'

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        all_members = list(Member.objects.all())
        with_due_balance = {
            member for member in all_members
            if member.balance < 0
        }

        counts = Counter([m.profile_sepa.sepa_direct_debit_state for m in with_due_balance])
        w_iban = sum(counts.values()) - counts[SepaDirectDebitState.NO_IBAN]
        w_v_iban = w_iban - counts[SepaDirectDebitState.INVALID_IBAN]

        w_rescinded = counts[SepaDirectDebitState.RESCINDED]
        w_bounced = counts[SepaDirectDebitState.BOUNCED]
        w_inactive = counts[SepaDirectDebitState.INACTIVE]

        w_active = w_v_iban - w_rescinded - w_bounced - w_inactive

        w_bic = w_active - counts[SepaDirectDebitState.NO_BIC]

        w_mandate_r = w_bic - counts[SepaDirectDebitState.NO_MANDATE_REFERENCE]

        assert w_mandate_r == counts[SepaDirectDebitState.OK]

        context.update({
            'all_members': len(all_members),
            'with_due_balance': len(with_due_balance),
            'with_iban': w_iban,
            'with_valid_iban': w_v_iban,
            'with_active_sepa': w_active,
            'with_inactive_sepa': w_inactive,
            'with_rescinded_sepa': w_rescinded,
            'with_bounced_sepa': w_bounced,
            'with_bic': w_bic,
            'with_mandate_reference': w_mandate_r,
            'without_mandate_reference': counts[SepaDirectDebitState.NO_MANDATE_REFERENCE],
            'without_bic': counts[SepaDirectDebitState.NO_BIC],
            'without_valid_iban': counts[SepaDirectDebitState.INVALID_IBAN],
        })

        return context
