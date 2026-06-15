from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any


def _stable_json(value: Any) -> str:
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_idempotency_key(
    *,
    local_object_type: str,
    local_object_id: str,
    source_event_type: str,
    external_id: str | None = None,
    request_body: Any | None = None,
) -> str:
    parts = [
        local_object_type,
        local_object_id,
        source_event_type,
        external_id or "",
        _stable_json(request_body) if request_body is not None else "",
    ]
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
