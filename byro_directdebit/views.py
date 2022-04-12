from collections import Counter
import logging
import string

from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.generic.base import TemplateResponseMixin, View
from django.views.generic.detail import SingleObjectMixin
from django.views.generic.edit import ProcessFormView
from sepaxml import SepaDD
from uuid import uuid4

from django.views.generic import ListView, TemplateView, FormView
from django.utils.crypto import get_random_string
from django.db.models import Q, Sum
from django.db.transaction import atomic
from django.contrib import messages
from django import forms
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ngettext_lazy
from django.utils.timezone import now
from django.urls import reverse_lazy, reverse

from localflavor.generic.forms import IBANFormField, BICFormField

from byro.common.models import Configuration
from byro.members.models import Member
from byro.plugins.sepa.models import SepaDirectDebitState
from byro.bookkeeping.special_accounts import SpecialAccounts

from schwifty import IBAN

from byro_directdebit.models import (
    DirectDebitConfiguration,
    DirectDebit,
    DirectDebitPayment,
    DirectDebitState,
)
from byro_directdebit.utils import next_debit_date


try:
    from byro_fints.plugin_interface import FinTSInterface
    from fints.client import (
        FinTSOperations,
        NeedTANResponse,
        TransactionResponse,
        ResponseStatus,
    )
except ImportError:
    FinTSInterface = None

SUPPORTED_PAIN_FORMATS = [
    # "pain.001.001.03",
    "pain.008.001.02",
    "pain.008.002.02",
    "pain.008.003.02",
]

logger = logging.getLogger(__name__)
DISABLE_AUDITLOGGING = True


class MemberList(ListView):
    template_name = "byro_directdebit/list.html"
    context_object_name = "members"
    model = Member
    paginate_by = 50

    def get_queryset(self):
        mode = self.request.GET.get("filter", "all")

        all_members = list(
            Member.objects.filter(
                Q(memberships__amount__gt=0)
                | Q(bookings__debit_account=SpecialAccounts.fees_receivable)
            )
            .order_by("-id")
            .distinct()
            .all()
        )

        if mode == "all":
            return list(all_members)

        if mode == "invalid_iban":
            return [
                m
                for m in all_members
                if m.profile_sepa.sepa_direct_debit_state
                == SepaDirectDebitState.INVALID_IBAN
            ]

        elif mode == "invalid_bic":
            return [
                m
                for m in all_members
                if m.profile_sepa.sepa_direct_debit_state
                == SepaDirectDebitState.INVALID_BIC
            ]

        elif mode == "rescinded":
            return [
                m
                for m in all_members
                if m.profile_sepa.sepa_direct_debit_state
                == SepaDirectDebitState.RESCINDED
            ]

        elif mode == "bounced":
            return [
                m
                for m in all_members
                if m.profile_sepa.sepa_direct_debit_state
                == SepaDirectDebitState.BOUNCED
            ]

        elif mode == "no_bic":
            return [
                m
                for m in all_members
                if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.NO_BIC
            ]

        elif mode == "no_iban":
            return [
                m
                for m in all_members
                if m.profile_sepa.sepa_direct_debit_state
                == SepaDirectDebitState.NO_IBAN
            ]

        elif mode == "no_mandate_reference":
            return [
                m
                for m in all_members
                if m.profile_sepa.sepa_direct_debit_state
                == SepaDirectDebitState.NO_MANDATE_REFERENCE
            ]

        with_due_balance = [member for member in all_members if member.balance < 0]

        if mode == "with_due_balance":
            return with_due_balance

        elif mode == "inactive":
            return [
                m
                for m in with_due_balance
                if m.profile_sepa.sepa_direct_debit_state
                == SepaDirectDebitState.INACTIVE
            ]

        elif mode == "eligible":
            return [
                m
                for m in with_due_balance
                if m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.OK
            ]

        else:
            return list(with_due_balance)


class Dashboard(TemplateView):
    template_name = "byro_directdebit/dashboard.html"

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        config = DirectDebitConfiguration.get_solo()

        all_members = list(
            Member.objects.filter(
                Q(memberships__amount__gt=0)
                | Q(bookings__debit_account=SpecialAccounts.fees_receivable)
            )
            .order_by("-id")
            .distinct()
            .all()
        )

        with_due_balance = {member for member in all_members if member.balance < 0}

        counts = Counter([m.profile_sepa.sepa_direct_debit_state for m in all_members])
        w_due_counts = Counter(
            [m.profile_sepa.sepa_direct_debit_state for m in with_due_balance]
        )

        context.update(
            {
                "creditor_id": config.creditor_id,
                "all_members": len(all_members),
                "with_due_balance": len(with_due_balance),
                "deactivated_sepa": w_due_counts[SepaDirectDebitState.INACTIVE],
                "no_iban": counts[SepaDirectDebitState.NO_IBAN],
                "eligible": w_due_counts[SepaDirectDebitState.OK],
                "invalid_iban": counts[SepaDirectDebitState.INVALID_IBAN],
                "no_bic": counts[SepaDirectDebitState.NO_BIC],
                "invalid_bic": counts[SepaDirectDebitState.INVALID_BIC],
                "rescinded": counts[SepaDirectDebitState.RESCINDED],
                "bounced": counts[SepaDirectDebitState.BOUNCED],
                "no_mandate_reference": counts[
                    SepaDirectDebitState.NO_MANDATE_REFERENCE
                ],
            }
        )

        return context


class AssignSepaMandatesForm(forms.Form):
    prefix = forms.CharField(
        max_length=35,
        required=False,
        help_text=_(
            "A short prefix that should be part of every assigned mandate reference to help the debtor identify the creditor. Good example: Short name of your organization (3-5 characters)."
        ),
    )
    length = forms.IntegerField(
        min_value=10,
        max_value=35,
        initial=22,
        help_text=_(
            "Length of the generated SEPA direct debit mandate references (including the prefix)."
        ),
    )

    subject = forms.CharField(required=True)
    text = forms.CharField(widget=forms.Textarea)


class AssignSepaMandatesView(FormView):
    template_name = "byro_directdebit/assign_sepa_mandates.html"
    form_class = AssignSepaMandatesForm
    success_url = reverse_lazy("plugins:byro_directdebit:finance.directdebit.dashboard")

    @staticmethod
    def _get_members():
        all_members = list(
            Member.objects.filter(
                Q(memberships__amount__gt=0)
                | Q(bookings__debit_account=SpecialAccounts.fees_receivable)
            )
            .order_by("-id")
            .distinct()
            .all()
        )

        return [
            m
            for m in all_members
            if m.profile_sepa.sepa_direct_debit_state
            == SepaDirectDebitState.NO_MANDATE_REFERENCE
        ]

    @staticmethod
    def _find_unused_mandate_reference(prefix, length, member, now_=None):
        now_ = now_ or now()

        allowed_chars = [x for x in string.ascii_uppercase if not x in "XBGIOQSZ"]
        format_string = "{}{:04d}{}{}"

        member_number = member.number or "0"
        formatted_number = (
            "{:06d}".format(int(member_number))
            if member_number.isdigit()
            else "X{}".format(member_number)
        )

        for i in range(3):
            format_params = [prefix, now_.year, "", formatted_number]

            empty_len = len(format_string.format(*format_params))

            random_string = get_random_string(
                length=length - empty_len, allowed_chars=allowed_chars
            )

            format_params[2] = random_string

            mandate_reference = format_string.format(*format_params).upper()

            if Member.objects.filter(
                profile_sepa__mandate_reference=mandate_reference
            ).count():
                mandate_reference = None
                continue
            else:
                break

        return mandate_reference

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["no_mandate_reference"] = len(self._get_members())

        return context

    def get_initial(self):
        config = DirectDebitConfiguration.get_solo()
        retval = super().get_initial()
        retval["prefix"] = config.mandate_reference_prefix
        retval["subject"] = config.mandate_reference_notification_template.subject
        retval["text"] = config.mandate_reference_notification_template.text
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
                    form.cleaned_data["prefix"],
                    form.cleaned_data["length"],
                    member,
                    now_,
                )

                if not mandate_reference:
                    error_count = error_count + 1
                    continue

                context = {
                    "creditor_id": config.creditor_id,
                    "sepa_mandate_reference": mandate_reference,
                    "sepa_iban": member.profile_sepa.iban,
                    "sepa_bic": member.profile_sepa.bic_autocomplete,
                    "contact": global_config.mail_from,
                    "association_name": global_config.name,
                    "additional_information": "",
                }

                mail = config.mandate_reference_notification_template.to_mail(
                    member.email, context=context, save=False
                )
                mail.save()
                mail.members.add(member)

                member.profile_sepa.mandate_reference = mandate_reference
                member.profile_sepa.save()

                member.log(self, ".updated")
                member.log(
                    self,
                    ".finance.sepadd.mandate_reference_assigned",
                    mandate_reference=mandate_reference,
                )

                success_count = success_count + 1

        if success_count:
            messages.success(
                self.request,
                ngettext_lazy(
                    "Assigned %(n)s mandate reference. Check the e-mail outbox for the notification mail.",
                    "Assigned %(n)s mandate references. Check the e-mail outbox for the notification mails.",
                    success_count,
                )
                % {"n": success_count},
            )

        if error_count:
            messages.error(
                self.request,
                ngettext_lazy(
                    "%(n)s mandate reference could not be assigned.",
                    "%(n)s mandate references could not be assigned.",
                    error_count,
                )
                % {"n": error_count},
            )

        if not error_count and not success_count:
            messages.warning(self.request, _("Nothing to do. Nothing done."))

        return super().form_valid(form)


class PrepareDDForm(forms.Form):
    debit_date = forms.DateField(
        label=_("Debit date"),
        required=True,
        help_text=_(
            "Date on which the debit should become effective. "
            "Warning: There are likely to be contractual limitations concerning this "
            "date between you and your bank. Generally should be 14 days in the "
            "future, on a bank day, not more than 30 days in the future."
        ),
    )
    debit_text = forms.CharField(
        required=True,
        label=_("Memo"),
        help_text=_(
            "Memo/subject that the member will see " "on their bank statement."
        ),
    )

    own_name = forms.CharField(required=True, label=_("Creditor name"))
    own_iban = IBANFormField(required=True, label=_("Creditor IBAN"))
    own_bic = BICFormField(required=True, label=_("Creditor BIC"))
    sepa_format = forms.CharField(
        required=True, label=_("SEPA PAIN format"), initial="pain.001.001.03"
    )
    own_account = forms.CharField(required=False, widget=forms.HiddenInput())

    cor1 = forms.BooleanField(
        label=_("Issue express debit (COR1)"),
        required=False,
        help_text=_(
            "An express debit has a reduced lead "
            "time of generally 1 business day, "
            "but must be explicitly agreed upon "
            "when giving the SEPA mandate."
        ),
    )

    exp_bank_types = forms.ChoiceField(
        required=True,
        label=_("Bank types"),
        choices=[
            ("ALL", _("All banks")),
            ("DE", _("German banks only")),
            ("NDE", _("Non-German banks only")),
        ],
    )
    exp_member_numbers = forms.CharField(
        required=False,
        label=_("Member numbers"),
        help_text=_(
            "Allows to issue a direct debit for a subset of members only. "
            "Example: 1-9,20-29,42"
        ),
    )

    subject = forms.CharField(required=True)
    text = forms.CharField(widget=forms.Textarea)

    debit_date.widget.attrs.update({"class": "datepicker"})


class FinTSInterfaceMixin:
    def setup(self, *args, **kwargs):
        super().setup(*args, **kwargs)
        if FinTSInterface:
            self.fints_interface = FinTSInterface.with_request(self.request)
        else:
            self.fints_interface = None


class PrepareDDView(FinTSInterfaceMixin, FormView):
    template_name = "byro_directdebit/prepare_dd.html"
    form_class = PrepareDDForm

    def setup(self, *args, **kwargs):
        super().setup(*args, **kwargs)

        all_accounts = []
        capable_accounts = []

        self.selected_sepa_pain_formats = None
        self.do_cor1 = False
        self.selected_account = None
        self.selected_account_login_pk = None
        self.bank_connections = []

        fallback_account = None
        fallback_login_pk = None

        if self.fints_interface:
            connections = self.fints_interface.get_bank_connections()
            for login_pk, connection in connections.items():
                for account in connection.get("accounts", []):
                    if "iban" in account and account["iban"]:
                        iban = IBAN(account["iban"])

                        if (
                            not fallback_account
                        ):  # Randomly select the first one as fallback
                            fallback_account = iban
                            fallback_login_pk = login_pk

                        if (
                            account["supported_operations"][
                                FinTSOperations.SEPA_DEBIT_MULTIPLE
                            ]
                            or account["supported_operations"][
                                FinTSOperations.SEPA_DEBIT_MULTIPLE_COR1
                            ]
                        ):

                            capable_accounts.append(iban)

                            if not self.selected_account:
                                self.selected_account = iban
                                self.selected_account_login_pk = login_pk

                                if connection.get("bank", {}).get(
                                    "supported_formats", {}
                                ):
                                    sup_mul = connection["bank"][
                                        "supported_formats"
                                    ].get(FinTSOperations.SEPA_DEBIT_MULTIPLE, None)
                                    sup_mul_cor1 = connection["bank"][
                                        "supported_formats"
                                    ].get(
                                        FinTSOperations.SEPA_DEBIT_MULTIPLE_COR1, None
                                    )

                                    if sup_mul:
                                        self.selected_sepa_pain_formats = sup_mul
                                        self.do_cor1 = False
                                    elif sup_mul_cor1:
                                        self.selected_sepa_pain_formats = sup_mul_cor1
                                        self.do_cor1 = True
                                    else:
                                        self.selected_account = None
                                        self.selected_account_login_pk = None

            self.bank_connections = connections

        if self.selected_sepa_pain_formats:
            self.selected_sepa_pain_formats = set(
                (e[:-4] if e.lower().endswith(".xml") else e).rsplit(":", 1)[-1]
                for e in self.selected_sepa_pain_formats
            )

        if not self.selected_account:
            messages.warning(self.request, "No account with DEBIT capability found")
            if fallback_account:
                self.selected_account = fallback_account
                self.selected_account_login_pk = fallback_login_pk

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.bank_connections = []
        self.selected_account = None

    def get_initial(self):
        config = DirectDebitConfiguration.get_solo()
        global_config = Configuration.get_solo()
        retval = super().get_initial()

        retval["debit_date"] = next_debit_date(region=config.creditor_id[:2])
        retval["debit_text"] = _(
            "Membership fees for %(organization_name)s"
            % {
                "organization_name": global_config.name,
            }
        )
        retval["own_name"] = global_config.name
        retval["subject"] = config.debit_notification_template.subject
        retval["text"] = config.debit_notification_template.text
        retval["own_account"] = self.selected_account_login_pk

        if self.do_cor1:
            retval["cor1"] = True

        if self.selected_sepa_pain_formats:
            l = list(
                e.lower()
                for e in self.selected_sepa_pain_formats
                if e.lower() in SUPPORTED_PAIN_FORMATS
            )
            if not l:
                messages.warning(
                    self.request, _("No common supported SEPA PAIN format")
                )
                l = self.selected_sepa_pain_formats
            if l:
                l.sort()
                retval["sepa_format"] = l[-1]
            else:
                messages.warning(self.request, _("No supported SEPA PAIN format"))

        if self.selected_account:
            retval["own_iban"] = str(self.selected_account)
            retval["own_bic"] = str(self.selected_account.bic)

        return retval

    @staticmethod
    def _get_members():
        all_members = list(
            Member.objects.filter(
                Q(memberships__amount__gt=0)
                | Q(bookings__debit_account=SpecialAccounts.fees_receivable)
            )
            .order_by("-id")
            .distinct()
            .all()
        )

        return [
            m
            for m in all_members
            if m.balance < 0
            and m.profile_sepa.sepa_direct_debit_state == SepaDirectDebitState.OK
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["eligible"] = len(self._get_members())

        return context

    def form_valid(self, form):
        config = DirectDebitConfiguration.get_solo()
        global_config = Configuration.get_solo()
        members = self._get_members()
        now_ = now()

        dd_config = {
            "name": form.cleaned_data["own_name"],
            "IBAN": str(form.cleaned_data["own_iban"]),
            "BIC": str(form.cleaned_data["own_bic"]),
            "batch": True,
            "creditor_id": config.creditor_id,
            "currency": global_config.currency,
            "instrument": "COR1" if form.cleaned_data["cor1"] else "CORE",
        }
        sepa = SepaDD(dd_config, schema=form.cleaned_data["sepa_format"], clean=True)

        exp_member_numbers = [
            (
                (int(x.split("-")[0]), int(x.split("-")[1]))
                if "-" in x
                else (int(x), int(x))
            )
            for x in form.cleaned_data["exp_member_numbers"].split(",")
        ]

        with atomic():
            debit = DirectDebit(
                datetime=now_,
                multiple=True,
                cor1=form.cleaned_data["cor1"],
                pain_descriptor="urn:iso:std:iso:20022:tech:xsd:"
                + form.cleaned_data["sepa_format"],
                additional_data={
                    "login_pk": self.selected_account_login_pk,
                    "account_iban": form.cleaned_data["own_iban"],
                    "account_bic": form.cleaned_data["own_bic"],
                },
            )
            debit_payments = []

            for member in members:
                ## Experimental gates
                if form.cleaned_data["exp_bank_types"] == "DE":
                    if not member.profile_sepa.iban.upper().startswith("DE"):
                        continue
                elif form.cleaned_data["exp_bank_types"] == "NDE":
                    if member.profile_sepa.iban.upper().startswith("DE"):
                        continue

                if exp_member_numbers:
                    if not any(
                        a <= int(member.number) <= b for (a, b) in exp_member_numbers
                    ):
                        continue

                debit_payment = DirectDebitPayment(
                    id=uuid4(),
                    type="FRST",  ## FIXME Based on existing data
                    mandate_reference=member.profile_sepa.mandate_reference,
                    collection_date=form.cleaned_data["debit_date"],
                    amount=-member.balance,
                    direct_debit=debit,
                    member=member,
                )

                payment = {
                    "name": member.name,
                    "IBAN": member.profile_sepa.iban,
                    "BIC": member.profile_sepa.bic_autocomplete,
                    "collection_date": debit_payment.collection_date,
                    "amount": int(debit_payment.amount * 100),  # in cents
                    "type": debit_payment.type,
                    "mandate_id": debit_payment.mandate_reference,
                    "mandate_date": member.profile_sepa.issue_date or now_.date(),
                    "description": form.cleaned_data["debit_text"],
                    "endtoend_id": debit_payment.id.hex,
                }
                sepa.add_payment(payment)
                debit_payments.append(debit_payment)

                context = {
                    "creditor_id": config.creditor_id,
                    "sepa_mandate_reference": debit_payment.mandate_reference,
                    "sepa_iban": member.profile_sepa.iban,
                    "sepa_bic": member.profile_sepa.bic_autocomplete,
                    "contact": global_config.mail_from,
                    "association_name": global_config.name,
                    "additional_information": "",
                    "debit_date": form.cleaned_data["debit_date"],
                    "amount": "%.2f %s"
                    % (debit_payment.amount, global_config.currency),
                }

                mail = config.debit_notification_template.to_mail(
                    member.email,
                    context=context,
                    save=False,
                )
                mail.text = form.cleaned_data["text"].format(**context)
                mail.subject = form.cleaned_data["subject"].format(**context)
                mail.save()
                mail.members.add(member)

            debit.sepa_xml = sepa.export(validate=True).decode("utf-8")
            debit.save()
            for p in debit_payments:
                p.save()

        return HttpResponseRedirect(
            reverse(
                "plugins:byro_directdebit:finance.directdebit.transmit_dd",
                kwargs={"pk": debit.pk},
            )
        )


class TransmitDDView(
    FinTSInterfaceMixin, SingleObjectMixin, TemplateResponseMixin, View
):
    template_name = "byro_directdebit/transmit_dd.html"
    model = DirectDebit
    success_url = reverse_lazy("plugins:byro_fints:finance.fints.dashboard")

    def setup(self, *args, **kwargs):
        super().setup(*args, **kwargs)
        self.object = self.get_object()

    def get_context_data(self, **kwargs):
        global_config = Configuration.get_solo()

        context = super().get_context_data(**kwargs)
        context["fints_form"] = None
        if self.fints_interface:
            debit_meta = self.fints_interface.sepa_debit_init(
                self.object.additional_data["login_pk"]
            )
            context["fints_form"] = debit_meta["form"]

        context["debit_count"] = self.object.payments.count()
        context["debit_currency"] = global_config.currency
        context["debit_sum"] = self.object.payments.aggregate(amount=Sum("amount"))[
            "amount"
        ]
        context["debit_account"] = self.object.additional_data["account_iban"]

        return context

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()

        if context["fints_form"]:
            if context["fints_form"].is_valid():
                try:
                    response = self.fints_interface.sepa_debit_do(
                        self.object.additional_data["login_pk"],
                        self.object.additional_data["account_iban"],
                        pain_message=self.object.sepa_xml,
                        multiple=self.object.multiple,
                        cor1=self.object.cor1,
                        control_sum=context["debit_sum"],
                        currency=context["debit_currency"],
                        pain_descriptor=self.object.pain_descriptor,
                    )

                    if isinstance(response, TransactionResponse):
                        self.fints_interface._show_transaction_messages(response)
                        if not DISABLE_AUDITLOGGING:
                            self.object.log(
                                self,
                                ".transmitdd.completed",
                                response_status=response.status,
                                response_messages=response.responses,
                                response_data=response.data,
                            )
                    elif isinstance(response, str):
                        if not DISABLE_AUDITLOGGING:
                            self.object.log(self, ".transmitdd.started", uuid=response)
                        return HttpResponseRedirect(
                            reverse(
                                "plugins:byro_directdebit:finance.directdebit.transmit_dd.tan_request",
                                kwargs={
                                    "pk": self.object.pk,
                                    "transfer_uuid": response,
                                },
                            )
                        )
                    else:
                        if not DISABLE_AUDITLOGGING:
                            self.object.log(self, ".transmitdd.internal_error")
                        messages.error(
                            self.request, _("Invalid response: {}".format(response))
                        )
                except:
                    if not DISABLE_AUDITLOGGING:
                        self.object.log(self, ".transmitdd.internal_error")
                    logger.exception("Internal error when transmitting SEPA-XML")
                    messages.error(
                        self.request,
                        _(
                            "An error occurred, please see server log for more information"
                        ),
                    )

        return self.render_to_response(context)


class TransmitDDTANView(
    FinTSInterfaceMixin, SingleObjectMixin, TemplateResponseMixin, View
):
    template_name = "byro_directdebit/transmit_dd_tan.html"
    model = DirectDebit
    success_url = reverse_lazy("plugins:byro_fints:finance.fints.dashboard")

    def setup(self, *args, **kwargs):
        super().setup(*args, **kwargs)
        self.object = self.get_object()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.fints_interface:
            tan_props = self.fints_interface.tan_request_init(
                self.object.additional_data["login_pk"], self.kwargs["transfer_uuid"]
            )
            context.update(tan_props["context"])
            context["tan_form"] = tan_props["form"]
            context["tan_template"] = tan_props["template"]
        return context

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        context = self.get_context_data()

        if context["tan_form"]:
            if context["tan_form"].is_valid():
                try:
                    response = self.fints_interface.tan_request_send_tan(
                        self.object.additional_data["login_pk"],
                        self.kwargs["transfer_uuid"],
                    )
                    if isinstance(response, TransactionResponse):
                        if not DISABLE_AUDITLOGGING:
                            self.object.log(
                                self,
                                ".transmitdd.completed",
                                response_status=response.status,
                                response_messages=response.responses,
                                response_data=response.data,
                                uuid=self.kwargs["transfer_uuid"],
                            )
                        self.fints_interface._show_transaction_messages(response)
                        messages.success(
                            self.request,
                            _(
                                "Successfully authorized the direct debit with your bank"
                            ),
                        )
                        self.object.state = DirectDebitState.TRANSMITTED.value
                    else:
                        if not DISABLE_AUDITLOGGING:
                            self.object.log(
                                self,
                                ".transmitdd.internal_error",
                                uuid=self.kwargs["transfer_uuid"],
                            )
                        messages.error(
                            self.request, _("Invalid response: {}".format(response))
                        )
                        self.object.state = DirectDebitState.FAILED.value
                except:
                    if not DISABLE_AUDITLOGGING:
                        self.object.log(
                            self,
                            ".transmitdd.internal_error",
                            uuid=self.kwargs["transfer_uuid"],
                        )
                    logger.exception("Internal error when transmitting TAN")
                    self.object.state = DirectDebitState.FAILED.value
                    messages.error(
                        self.request,
                        _(
                            "An error occurred, please see server log for more information"
                        ),
                    )
                self.object.save(update_fields=["state"])

                return HttpResponseRedirect(self.success_url)

        return self.render_to_response(context)
