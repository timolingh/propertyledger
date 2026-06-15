from __future__ import annotations

from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic import TemplateView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from ledgeros.forms import LedgerOSConnectionSettingsForm
from ledgeros.models import LedgerOSConnectionSettings, LedgerOSSyncRecord
from ledgeros.serializers import LedgerOSSyncRecordSerializer
from ledgeros.services import (
    LedgerOSHealthCheckService,
    LocalHealthCheckService,
)


class LedgerOSSetupView(TemplateView):
    template_name = "ledgeros/setup.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        settings_obj = LedgerOSConnectionSettings.load()
        context["settings_form"] = kwargs.get(
            "form", LedgerOSConnectionSettingsForm(instance=settings_obj)
        )
        context["local_health"] = LocalHealthCheckService.check()
        context["ledgeros_health"] = LedgerOSHealthCheckService.check()
        context["settings_obj"] = settings_obj
        return context

    def post(self, request, *args, **kwargs):
        settings_obj = LedgerOSConnectionSettings.load()
        form = LedgerOSConnectionSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse("ledgeros-setup"))
        context = self.get_context_data(form=form)
        return self.render_to_response(context)


class LocalHealthAPIView(APIView):
    def get(self, request, *args, **kwargs):
        result = LocalHealthCheckService.check()
        status_code = 200 if result.healthy else 503
        return Response(
            {
                "healthy": result.healthy,
                "source": result.source,
                "details": result.details,
            },
            status=status_code,
        )


class LedgerOSHealthAPIView(APIView):
    def get(self, request, *args, **kwargs):
        result = LedgerOSHealthCheckService.check()
        status_code = 200 if result.healthy else 503
        return Response(
            {
                "healthy": result.healthy,
                "source": result.source,
                "details": result.details,
            },
            status=status_code,
        )


class LedgerOSSyncRecordCreateAPIView(generics.CreateAPIView):
    queryset = LedgerOSSyncRecord.objects.all()
    serializer_class = LedgerOSSyncRecordSerializer
