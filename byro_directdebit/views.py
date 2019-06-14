from collections import Counter

from django.views.generic import ListView, TemplateView
from django.db.models import Q

from byro.members.models import Member
from byro.plugins.sepa.models import SepaDirectDebitState
from byro.bookkeeping.special_accounts import SpecialAccounts


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
            'all_members': len(all_members),
            'with_due_balance': len(with_due_balance),
            'deactivated_sepa': w_due_counts[SepaDirectDebitState.INACTIVE],
            'eligible': w_due_counts[SepaDirectDebitState.OK],
            'invalid_iban': counts[SepaDirectDebitState.INVALID_IBAN],
            'no_bic': counts[SepaDirectDebitState.NO_BIC],
            'rescinded': counts[SepaDirectDebitState.RESCINDED],
            'bounced': counts[SepaDirectDebitState.BOUNCED],
            'no_mandate_reference': counts[SepaDirectDebitState.NO_MANDATE_REFERENCE],
        })

        return context
