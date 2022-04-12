# Register your receivers here
from django.dispatch import receiver
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

from byro.office.signals import nav_event


@receiver(nav_event)
def directdebit_sidebar(sender, **kwargs):
    request = sender
    if hasattr(request, "user") and not request.user.is_anonymous:
        return {
            "section": "finance",
            "label": _("Direct debit"),
            "url": reverse("plugins:byro_directdebit:finance.directdebit.dashboard"),
            "active": "byro_directdebit" in request.resolver_match.namespace,
        }
