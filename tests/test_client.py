import base64
import hashlib
import hmac
import io
import json
import unittest
import urllib.error
from email.message import Message

from fiskit import Fiskit, FiskitError, verify_webhook

INVOICE = {"id": "inv_1", "object": "invoice", "status": "authorized", "number": 42, "cae": "76451234567890"}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _http_error(status, body, headers=None):
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError("https://api.test", status, "error", message, io.BytesIO(json.dumps(body).encode()))


class FakeOpener:
    """Answers from a list and records every request."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _Response(answer if isinstance(answer, bytes) else json.dumps(answer).encode())


class ClientTest(unittest.TestCase):

    def test_creates_an_invoice_with_the_key_the_body_and_an_idempotency_key(self):
        opener = FakeOpener([INVOICE])
        client = Fiskit("sk_test_x", base_url="https://api.test", opener=opener)

        invoice = client.invoices.create({"voucher_type": "invoice_c", "amounts": {"total": 1500}},
                                         idempotency_key="sale-1")

        self.assertEqual(invoice["cae"], "76451234567890")
        request = opener.requests[0]
        self.assertEqual(request.full_url, "https://api.test/v1/invoices")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk_test_x")
        self.assertEqual(request.get_header("Idempotency-key"), "sale-1")
        self.assertEqual(json.loads(request.data), {"voucher_type": "invoice_c", "amounts": {"total": 1500}})

    def test_retries_an_outage_with_the_same_generated_idempotency_key(self):
        opener = FakeOpener([
            _http_error(503, {"error": {"code": "authority_unavailable"}}, {"Retry-After": "0"}),
            urllib.error.URLError("reset"),
            INVOICE,
        ])
        client = Fiskit("sk_test_x", opener=opener)

        client.invoices.create({"voucher_type": "invoice_c", "amounts": {"total": 1}})

        keys = {request.get_header("Idempotency-key") for request in opener.requests}
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(len(keys), 1)
        self.assertTrue(next(iter(keys)))

    def test_api_errors_become_a_fiskit_error(self):
        opener = FakeOpener([_http_error(400, {"error": {
            "type": "invalid_request_error", "code": "parameter_invalid", "message": "Bad total",
            "param": "amounts.total", "request_id": "req_1"}})])
        client = Fiskit("sk_test_x", opener=opener)

        with self.assertRaises(FiskitError) as raised:
            client.invoices.retrieve("inv_1")

        error = raised.exception
        self.assertEqual((error.status, error.code, error.param, error.request_id),
                         (400, "parameter_invalid", "amounts.total", "req_1"))

    def test_the_pdf_comes_back_as_bytes_and_the_taxpayer_by_cuit(self):
        opener = FakeOpener([b"%PDF-1.7", {"object": "taxpayer", "vat_condition": "registered"}])
        client = Fiskit("sk_test_x", opener=opener)

        self.assertEqual(client.invoices.pdf("inv_1"), b"%PDF-1.7")
        self.assertEqual(client.taxpayers.retrieve(30712345671)["vat_condition"], "registered")
        self.assertEqual(opener.requests[0].get_header("Accept"), "application/pdf")
        self.assertTrue(opener.requests[1].full_url.endswith("/v1/taxpayers/30712345671"))

    def test_a_post_without_idempotency_key_is_never_retried(self):
        opener = FakeOpener([urllib.error.URLError("reset")])
        client = Fiskit("sk_test_x", opener=opener)

        with self.assertRaises(FiskitError) as raised:
            client.invoices.email("inv_1", "a@b.com")

        self.assertEqual(raised.exception.code, "network")
        self.assertEqual(len(opener.requests), 1)


class WebhookTest(unittest.TestCase):
    # Example from the Standard Webhooks specification
    SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
    HEADERS = {
        "webhook-id": "msg_p5jXN8AQM9LWM0D4loKWxJek",
        "webhook-timestamp": "1614265330",
        "webhook-signature": "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
    }

    def test_verifies_the_specification_example(self):
        event = verify_webhook('{"test": 2432232314}', self.HEADERS, self.SECRET, now=1614265330)
        self.assertEqual(event, {"test": 2432232314})

    def test_rejects_tampering_and_old_messages(self):
        with self.assertRaisesRegex(ValueError, "Invalid"):
            verify_webhook('{"test": 1}', self.HEADERS, self.SECRET, now=1614265330)
        with self.assertRaisesRegex(ValueError, "tolerance"):
            verify_webhook('{"test": 2432232314}', self.HEADERS, self.SECRET, now=1614265330 + 3600)

    def test_accepts_its_own_signature(self):
        key = base64.b64decode(self.SECRET.removeprefix("whsec_"))
        signature = base64.b64encode(hmac.new(key, b"evt_1.1614265330.{}", hashlib.sha256).digest()).decode()
        headers = {"Webhook-Id": "evt_1", "Webhook-Timestamp": "1614265330", "Webhook-Signature": f"v1,{signature}"}
        self.assertEqual(verify_webhook(b"{}", headers, self.SECRET, now=1614265330), {})


if __name__ == "__main__":
    unittest.main()
