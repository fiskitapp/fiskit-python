"""Official Python client for the FisKit API: electronic invoices with ARCA (ex AFIP).

No dependencies: it uses only the standard library.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Mapping, Optional

__all__ = ["Fiskit", "FiskitError", "verify_webhook"]
__version__ = "0.1.3"

DEFAULT_BASE_URL = "https://api.fiskit.com.ar"
_RETRYABLE = {408, 409, 429, 500, 502, 503, 504}


class FiskitError(Exception):
    """An error answered by the API, or a network failure (status 0)."""

    def __init__(self, status: int, type: str, code: str, message: str, param: Optional[str] = None,
                 request_id: Optional[str] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.type = type
        self.code = code
        self.message = message
        self.param = param
        self.request_id = request_id
        self.body = body


class Fiskit:
    """Client of the FisKit API.

    >>> fiskit = Fiskit()  # reads FISKIT_API_KEY
    >>> invoice = fiskit.invoices.create({"voucher_type": "invoice_c", "amounts": {"total": 1500}},
    ...                                  idempotency_key="sale-8812")
    """

    def __init__(self, api_key: Optional[str] = None, *, base_url: str = DEFAULT_BASE_URL, max_retries: int = 2,
                 timeout: float = 60.0, opener: Any = None):
        self.api_key = api_key or os.environ.get("FISKIT_API_KEY")
        if not self.api_key:
            raise ValueError("Missing API key: pass it or set FISKIT_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self.invoices = _Invoices(self)
        self.taxpayers = _Taxpayers(self)

    def request(self, method: str, path: str, body: Any = None, idempotency_key: Optional[str] = None,
                binary: bool = False) -> Any:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/pdf" if binary else "application/json",
            "User-Agent": f"fiskit-python/{__version__}",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        retry_allowed = method == "GET" or bool(idempotency_key)

        attempt = 0
        while True:
            request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
            try:
                with self._open(request, timeout=self.timeout) as response:
                    content = response.read()
                    if binary:
                        return content
                    return json.loads(content) if content else None
            except urllib.error.HTTPError as error:
                if error.code in _RETRYABLE and retry_allowed and attempt < self.max_retries:
                    _wait(attempt, error.headers.get("Retry-After") if error.headers else None)
                    attempt += 1
                    continue
                raise _api_error(error) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                # Without an idempotency key a POST is not repeated: it might have been processed
                if retry_allowed and attempt < self.max_retries:
                    _wait(attempt, None)
                    attempt += 1
                    continue
                raise FiskitError(0, "connection_error", "network", str(error)) from None


class _Invoices:
    def __init__(self, client: Fiskit):
        self._client = client

    def create(self, body: Mapping[str, Any], idempotency_key: Optional[str] = None) -> dict:
        """Issues an invoice. Without idempotency_key one is generated, so retries never issue twice."""
        return self._client.request("POST", "/v1/invoices", body=dict(body),
                                    idempotency_key=idempotency_key or str(uuid.uuid4()))

    def retrieve(self, invoice_id: str) -> dict:
        return self._client.request("GET", f"/v1/invoices/{urllib.parse.quote(invoice_id)}")

    def pdf(self, invoice_id: str) -> bytes:
        """The voucher PDF as bytes."""
        return self._client.request("GET", f"/v1/invoices/{urllib.parse.quote(invoice_id)}/pdf", binary=True)

    def email(self, invoice_id: str, email: Optional[str] = None) -> dict:
        """Emails the PDF to the customer; without email, to receiver.email of the invoice."""
        return self._client.request("POST", f"/v1/invoices/{urllib.parse.quote(invoice_id)}/email",
                                    body={"email": email} if email else {})


class _Taxpayers:
    def __init__(self, client: Fiskit):
        self._client = client

    def retrieve(self, cuit: int | str) -> dict:
        """Name, address and VAT condition of a CUIT, from the ARCA registry."""
        return self._client.request("GET", f"/v1/taxpayers/{urllib.parse.quote(str(cuit))}")


def verify_webhook(raw_body: str | bytes, headers: Mapping[str, str], secret: str, *,
                   tolerance_seconds: int = 300, now: Optional[float] = None) -> dict:
    """Checks a webhook (Standard Webhooks) and returns the parsed event.

    Raises ValueError if the signature is wrong or too old. Pass the raw body as received.
    """
    lowered = {key.lower(): value for key, value in headers.items()}
    message_id = lowered.get("webhook-id")
    timestamp = lowered.get("webhook-timestamp")
    signatures = lowered.get("webhook-signature")
    if not message_id or not timestamp or not signatures:
        raise ValueError("Missing webhook headers")
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > tolerance_seconds:
        raise ValueError("Webhook timestamp out of tolerance")
    body = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
    key = base64.b64decode(secret.removeprefix("whsec_"))
    expected = base64.b64encode(
        hmac.new(key, f"{message_id}.{timestamp}.{body}".encode("utf-8"), hashlib.sha256).digest()).decode()
    for candidate in signatures.split(" "):
        if hmac.compare_digest(candidate.removeprefix("v1,"), expected):
            return json.loads(body)
    raise ValueError("Invalid webhook signature")


def _wait(attempt: int, retry_after: Optional[str]) -> None:
    try:
        seconds = float(retry_after) if retry_after else 0
    except ValueError:
        seconds = 0
    time.sleep(min(seconds, 30) if seconds > 0 else 0.5 * 2 ** attempt)


def _api_error(error: urllib.error.HTTPError) -> FiskitError:
    try:
        payload = json.loads(error.read() or b"null")
    except ValueError:
        payload = None
    details = payload.get("error", {}) if isinstance(payload, dict) else {}
    return FiskitError(
        status=error.code,
        type=details.get("type", "api_error"),
        code=details.get("code", f"http_{error.code}"),
        message=details.get("message", f"HTTP {error.code}"),
        param=details.get("param"),
        request_id=details.get("request_id") or (error.headers.get("Request-Id") if error.headers else None),
        body=payload,
    )
