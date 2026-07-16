from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views import View

from ledgeros.navigation import get_home_redirect_url


class AppHomeRedirectView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return redirect(get_home_redirect_url(request.user))
