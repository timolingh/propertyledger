from django.urls import path

from reports.views import (
    OwnerContributionDistributionArchiveView,
    OwnerContributionDistributionCreateView,
    OwnerContributionDistributionDetailView,
    OwnerContributionDistributionListView,
    OwnerContributionDistributionUpdateView,
    OwnerPendingSyncReportView,
    OwnerStatementExportView,
    OwnerStatementView,
    ReportsLandingView,
)


urlpatterns = [
    path("", ReportsLandingView.as_view(), name="reports-home"),
    path("owner-activities/", OwnerContributionDistributionListView.as_view(), name="owner-activity-list"),
    path("owner-activities/add/", OwnerContributionDistributionCreateView.as_view(), name="owner-activity-create"),
    path("owner-activities/<int:pk>/", OwnerContributionDistributionDetailView.as_view(), name="owner-activity-detail"),
    path("owner-activities/<int:pk>/edit/", OwnerContributionDistributionUpdateView.as_view(), name="owner-activity-edit"),
    path("owner-activities/<int:pk>/archive/", OwnerContributionDistributionArchiveView.as_view(), name="owner-activity-archive"),
    path("owner-statements/", OwnerStatementView.as_view(), name="owner-statement"),
    path("owner-statements/export/", OwnerStatementExportView.as_view(), name="owner-statement-export"),
    path("pending-sync/", OwnerPendingSyncReportView.as_view(), name="owner-activity-pending-sync"),
]

