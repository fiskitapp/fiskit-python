# FisKit para Python

[English below](#english)

Cliente oficial de la API de [FisKit](https://fiskit.com.ar): facturas electrónicas de ARCA (ex AFIP) con un solo pedido. Sin dependencias, para Python 3.10 o superior.

```bash
pip install fiskit
```

## Tu primera factura

```python
from fiskit import Fiskit

fiskit = Fiskit()  # lee FISKIT_API_KEY

# Con el id de tu venta como clave, un reintento nunca duplica la factura
invoice = fiskit.invoices.create(
    {"voucher_type": "invoice_c", "amounts": {"total": 1500}},
    idempotency_key="venta-8812",
)

print(invoice["number"], invoice["cae"])
```

Las claves `sk_test_...` emiten en la homologación de ARCA, sin validez fiscal. Las `sk_live_...` emiten facturas reales. Las dos se crean en el panel.

## Qué podés hacer

```python
fiskit.invoices.retrieve(invoice_id)                  # estado actual
pdf = fiskit.invoices.pdf(invoice_id)                 # bytes del PDF con el QR de ARCA
fiskit.invoices.email(invoice_id, "cliente@example.com")
fiskit.taxpayers.retrieve(30712345671)                # nombre, domicilio y condición frente al IVA
```

Si ARCA no responde o se corta la conexión, el cliente reintenta solo con la misma `Idempotency-Key`. Si no pasás una, se genera automáticamente. Los errores llegan como `FiskitError`, con `status`, `type`, `code`, `message`, `param` y `request_id`.

## Webhooks

```python
from fiskit import verify_webhook

# Flask: usá el cuerpo crudo, antes de parsearlo
@app.post("/webhooks/fiskit")
def webhook():
    event = verify_webhook(request.get_data(), request.headers, os.environ["FISKIT_WEBHOOK_SECRET"])
    if event["type"] == "invoice.authorized":
        ...  # event["data"]["object"] es la factura
    return "", 200
```

Documentación completa: https://fiskit.com.ar/developers

---

## English

Official client of the [FisKit](https://fiskit.com.ar) API: Argentine electronic invoices with ARCA (formerly AFIP) in a single request. No dependencies, Python 3.10 or later.

```python
from fiskit import Fiskit, verify_webhook

fiskit = Fiskit()  # reads FISKIT_API_KEY

# Your sale id as the key: a retry never issues a second invoice
invoice = fiskit.invoices.create(
    {"voucher_type": "invoice_c", "amounts": {"total": 1500}},
    idempotency_key="sale-8812",
)

fiskit.invoices.pdf(invoice["id"])                   # PDF with ARCA's QR code, as bytes
fiskit.invoices.email(invoice["id"], "customer@example.com")
fiskit.taxpayers.retrieve(30712345671)               # name, address and VAT condition of a CUIT
```

`sk_test_...` keys issue against ARCA's homologation environment (no fiscal value); `sk_live_...` keys issue real invoices. Outages and dropped connections are retried with the same idempotency key, generated when you do not pass one. Errors are `FiskitError` instances with `status`, `type`, `code`, `message`, `param` and `request_id`. `verify_webhook(raw_body, headers, secret)` checks Standard Webhooks signatures.

Full documentation: https://fiskit.com.ar/developers
