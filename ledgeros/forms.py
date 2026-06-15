from __future__ import annotations

from django import forms

from ledgeros.models import LedgerOSConnectionSettings


class LedgerOSConnectionSettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["base_url"].required = True
        self.fields["client_id"].required = True
        self.fields["base_url"].help_text = "LedgerOS base URL, for example https://ledgeros.example.com"
        self.fields["client_id"].help_text = "LedgerOS client identifier used by the adapter"

    class Meta:
        model = LedgerOSConnectionSettings
        fields = [
            "base_url",
            "client_id",
            "hmac_secret_env_var",
            "api_key_env_var",
            "health_path",
            "timeout_seconds",
        ]
