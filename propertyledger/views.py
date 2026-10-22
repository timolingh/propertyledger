from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.template.response import TemplateResponse
from django.views.generic import TemplateView

from ledgeros.navigation import get_home_redirect_url
from propertyledger.workflows import workflow_home_context


class WorkflowHomeView(LoginRequiredMixin, TemplateView):
    template_name = "ledgeros/workflow_home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(workflow_home_context(self.request.user))
        return context


def forbidden_view(request, exception=None):
    return TemplateResponse(
        request,
        "403.html",
        {
            "back_url": request.META.get("HTTP_REFERER") or get_home_redirect_url(request.user),
        },
        status=403,
    )
