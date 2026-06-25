from django.urls import path

from payments.views import (
    TenantInvoiceDetailView,
    TenantInvoiceListView,
    SecurityDepositEventCreateView,
    SecurityDepositEventDetailView,
    SecurityDepositEventUpdateView,
    SecurityDepositEventListView,
    TenantPaymentCreateView,
    TenantPaymentDetailView,
    TenantPaymentUpdateView,
    TenantPaymentListView,
    PaymentsLandingView,
)


urlpatterns = [
    path("", PaymentsLandingView.as_view(), name="payments-home"),
    path("invoices/", TenantInvoiceListView.as_view(), name="invoice-list"),
    path("invoices/<int:pk>/", TenantInvoiceDetailView.as_view(), name="invoice-detail"),
    path("tenant-payments/", TenantPaymentListView.as_view(), name="tenant-payment-list"),
    path("tenant-payments/add/", TenantPaymentCreateView.as_view(), name="tenant-payment-create"),
    path("tenant-payments/<int:pk>/", TenantPaymentDetailView.as_view(), name="tenant-payment-detail"),
    path("tenant-payments/<int:pk>/edit/", TenantPaymentUpdateView.as_view(), name="tenant-payment-edit"),
    path("security-deposits/", SecurityDepositEventListView.as_view(), name="security-deposit-list"),
    path("security-deposits/add/", SecurityDepositEventCreateView.as_view(), name="security-deposit-create"),
    path("security-deposits/<int:pk>/", SecurityDepositEventDetailView.as_view(), name="security-deposit-detail"),
    path("security-deposits/<int:pk>/edit/", SecurityDepositEventUpdateView.as_view(), name="security-deposit-edit"),
]
