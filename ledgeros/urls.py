from django.urls import path

from ledgeros.views import (
    LedgerOSHealthAPIView,
    LedgerOSSetupView,
    LedgerOSSyncRecordCreateAPIView,
    LocalHealthAPIView,
)


urlpatterns = [
    path("", LedgerOSSetupView.as_view(), name="ledgeros-setup"),
    path("api/health/local/", LocalHealthAPIView.as_view(), name="local-health"),
    path(
        "api/health/ledgeros/",
        LedgerOSHealthAPIView.as_view(),
        name="ledgeros-health",
    ),
    path(
        "api/sync-records/",
        LedgerOSSyncRecordCreateAPIView.as_view(),
        name="ledgeros-sync-record-create",
    ),
]
