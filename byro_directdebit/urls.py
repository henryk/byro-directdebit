from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^directdebit/dashboard$', views.Dashboard.as_view(), name='finance.directdebit.dashboard'),
    url(r'^directdebit/list$', views.MemberList.as_view(), name='finance.directdebit.list'),
    url(r'^directdebit/assign_sepa_mandates$', views.AssignSepaMandatesView.as_view(), name='finance.directdebit.assign_sepa_mandates'),
]
