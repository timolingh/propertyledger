from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("ledgeros.urls")),
    path("", include("payments.urls")),
]
