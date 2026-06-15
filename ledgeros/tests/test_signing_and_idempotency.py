from __future__ import annotations

import base64
import hashlib
import hmac

from django.test import SimpleTestCase

from ledgeros.idempotency import build_idempotency_key
from ledgeros.signing import canonical_request_payload, sign_request


class SigningTests(SimpleTestCase):
    def test_sign_request_is_deterministic_and_matches_hmac_sha256(self):
        kwargs = dict(
            method="post",
            path="api/sync-records/",
            body=b'{"hello":"world"}',
            timestamp="1970-01-01T00:00:00Z",
            client_id="propertyledger",
            secret="supersecret",
        )

        first = sign_request(**kwargs)
        second = sign_request(**kwargs)

        self.assertEqual(first, second)
        payload = canonical_request_payload(
            method=kwargs["method"],
            path=kwargs["path"],
            body=kwargs["body"],
            timestamp=kwargs["timestamp"],
            client_id=kwargs["client_id"],
        )
        expected_digest = hmac.new(
            b"supersecret", payload.encode("utf-8"), hashlib.sha256
        ).digest()
        self.assertEqual(first.signature, base64.b64encode(expected_digest).decode("ascii"))


class IdempotencyTests(SimpleTestCase):
    def test_idempotency_key_is_stable_for_same_inputs(self):
        kwargs = dict(
            local_object_type="tenant_charge",
            local_object_id="42",
            source_event_type="invoice_created",
            external_id="invoice-42",
            request_body={"amount": "100.00", "currency": "USD"},
        )

        first = build_idempotency_key(**kwargs)
        second = build_idempotency_key(**kwargs)

        self.assertEqual(first, second)

    def test_idempotency_key_changes_when_payload_changes(self):
        base_kwargs = dict(
            local_object_type="tenant_charge",
            local_object_id="42",
            source_event_type="invoice_created",
            external_id="invoice-42",
            request_body={"amount": "100.00", "currency": "USD"},
        )

        first = build_idempotency_key(**base_kwargs)
        second = build_idempotency_key(
            **{**base_kwargs, "request_body": {"amount": "101.00", "currency": "USD"}}
        )

        self.assertNotEqual(first, second)
