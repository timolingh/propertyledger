from django.contrib import admin

from reports.models import OwnerContributionDistribution


@admin.register(OwnerContributionDistribution)
class OwnerContributionDistributionAdmin(admin.ModelAdmin):
    list_display = ("owner", "property", "event_type", "event_date", "amount", "status")
    list_select_related = ("owner", "property", "sync_record")
    search_fields = ("owner__name", "property__name", "description")
    list_filter = ("event_type", "status", "event_date")

