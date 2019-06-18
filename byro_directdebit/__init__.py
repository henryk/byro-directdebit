from django.apps import AppConfig
from django.utils.translation import ugettext_lazy


class PluginApp(AppConfig):
    name = 'byro_directdebit'
    verbose_name = 'Byro SEPA Direct Debit plugin'

    class ByroPluginMeta:
        name = ugettext_lazy('Byro SEPA Direct Debit plugin')
        author = 'Henryk Plötz'
        description = ugettext_lazy('This plugin allows membership fees to be collected with SEPA direct debit')
        visible = True
        version = '0.0.1'

    def ready(self):
        from . import signals  # NOQA
        from . import urls # NOQA
        from . import models # NOQA


default_app_config = 'byro_directdebit.PluginApp'
