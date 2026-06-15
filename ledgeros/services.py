from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.db import connection

from ledgeros.idempotency import build_idempotency_key
from ledgeros.models import LedgerOSConnectionSettings
from ledgeros.signing import sign_request


@dataclass(frozen=True)
class HealthCheckResult:
    healthy: bool
    source: str
    details: dict[str, Any]


class LocalHealthCheckService:
    @staticmethod
    def check() -> HealthCheckResult:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:  # pragma: no cover - exercised in failure tests
            return HealthCheckResult(
                healthy=False,
                source="local",
                details={"database": "unhealthy", "error": str(exc)},
            )

        return HealthCheckResult(
            healthy=True,
            source="local",
            details={"database": "healthy"},
        )


class LedgerOSHealthCheckService:
    @staticmethod
    def check() -> HealthCheckResult:
        connection_settings = LedgerOSConnectionSettings.load()
        base_url = connection_settings.base_url
        client_id = connection_settings.client_id
        secret_env_var = connection_settings.hmac_secret_env_var or "LEDGEROS_HMAC_SECRET"
        health_path = connection_settings.health_path
        timeout = connection_settings.timeout_seconds
        api_key = os.environ.get(
            connection_settings.api_key_env_var or "LEDGEROS_API_KEY",
            "",
        )
        secret = os.environ.get(secret_env_var, "")

        missing = []
        if not base_url:
            missing.append("base_url")
        if not client_id:
            missing.append("client_id")
        if not secret:
            missing.append(secret_env_var)

        if missing:
            return HealthCheckResult(
                healthy=False,
                source="ledgeros",
                details={"error": "missing_configuration", "missing": missing},
            )

        body = b""
        path = health_path if health_path.startswith("/") else f"/{health_path}"
        url = f"{base_url.rstrip('/')}{path}"
        timestamp = "1970-01-01T00:00:00Z"
        signed = sign_request(
            method="GET",
            path=path,
            body=body,
            timestamp=timestamp,
            client_id=client_id,
            secret=secret,
        )
        headers = {
            "X-LedgerOS-Client-Id": client_id,
            "X-LedgerOS-Timestamp": timestamp,
            "X-LedgerOS-Signature": signed.signature,
            "X-LedgerOS-Idempotency-Key": build_idempotency_key(
                local_object_type="ledgeros_health_check",
                local_object_id=base_url,
                source_event_type="health_check",
                external_id=path,
            ),
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request = Request(url, method="GET", headers=headers)

        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8").strip()
                if response.status != 200:
                    return HealthCheckResult(
                        healthy=False,
                        source="ledgeros",
                        details={
                            "status": "unhealthy",
                            "http_status": response.status,
                            "payload": payload,
                        },
                    )

                try:
                    parsed_payload = json.loads(payload) if payload else None
                except json.JSONDecodeError:
                    parsed_payload = None

                if not isinstance(parsed_payload, dict) or parsed_payload.get("status") not in {
                    "ok",
                    "healthy",
                }:
                    return HealthCheckResult(
                        healthy=False,
                        source="ledgeros",
                        details={
                            "status": "unhealthy",
                            "http_status": response.status,
                            "payload": payload,
                            "error": "unexpected_payload",
                        },
                    )

                return HealthCheckResult(
                    healthy=True,
                    source="ledgeros",
                    details={
                        "status": "healthy",
                        "http_status": response.status,
                        "payload": parsed_payload,
                    },
                )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            return HealthCheckResult(
                healthy=False,
                source="ledgeros",
                details={"status": "unhealthy", "error": str(exc)},
            )
