from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^directdebit/dashboard$', views.Dashboard.as_view(), name='finance.directdebit.dashboard'),
    url(r'^directdebit/list$', views.MemberList.as_view(), name='finance.directdebit.list'),
    url(r'^directdebit/assign_sepa_mandates$', views.AssignSepaMandatesView.as_view(), name='finance.directdebit.assign_sepa_mandates'),
    url(r'^directdebit/prepare_dd$', views.PrepareDDView.as_view(), name='finance.directdebit.prepare_dd'),
    url(r'^directdebit/transmit_dd/(?P<pk>[0-9a-f-]+)$', views.TransmitDDView.as_view(), name='finance.directdebit.transmit_dd'),
    url(r'^directdebit/transmit_dd/(?P<pk>[0-9a-f-]+)/tan/(?P<transfer_uuid>[0-9a-f-]+|test_data(?:_2)?)$', views.TransmitDDTANView.as_view(), name='finance.directdebit.transmit_dd.tan_request'),
]
