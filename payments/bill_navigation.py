from urllib.parse import urlsplit, urlunsplit

from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


class BillCreationReturnMixin:
    """Keep the bill entry source across form validation and submission."""

    def default_bill_return_url(self):
        return reverse("vendor-bill-list")

    def get_bill_return_url(self):
        if self.request.method == "POST":
            candidate = self.request.POST.get("return_url", "")
        else:
            candidate = self.request.GET.get("return_url", self.request.META.get("HTTP_REFERER", ""))
        candidate = candidate.strip()
        if url_has_allowed_host_and_scheme(
            candidate, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure(),
        ):
            parts = urlsplit(candidate)
            if (
                parts.path.startswith("/") and not parts.path.startswith("//")
                and "\\" not in parts.path and parts.path != self.request.path
            ):
                return urlunsplit(("", "", parts.path, parts.query, parts.fragment))
        return self.default_bill_return_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["bill_return_url"] = self.get_bill_return_url()
        return context
