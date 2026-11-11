# FisKit para Python

Cliente oficial de la API de [FisKit](https://fiskit.com.ar): facturas electrónicas de ARCA (ex AFIP) con un solo pedido. Sin dependencias, para Python 3.10 o superior.

```bash
pip install fiskit
```

## Tu primera factura

```python
from fiskit import Fiskit

fiskit = Fiskit()  # lee FISKIT_API_KEY

invoice = fiskit.invoices.create(
    {"voucher_type": "invoice_c", "amounts": {"total": 1500}},
    idempotency_key="venta-8812",  # el id de tu venta: un reintento nunca duplica la factura
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

Si ARCA no responde o se corta la conexión, el cliente reintenta solo con la misma `Idempotency-Key`. Si no pasás una, se genera automáticamente.

Los errores llegan como `FiskitError`, con `status`, `type`, `code`, `message`, `param` y `request_id`.

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
