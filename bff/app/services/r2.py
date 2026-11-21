"""Link de leitura do R2 do meuWatt (o orto das usinas), assinado aqui. Cópia do `presign` do mw-api
(`src/plant_map/service.py`): SigV4 de query, como o `generate_presigned_url` do boto3."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from app.core.config import get_settings

LINK_S = 7200  # assinado na hora cheia: o link é o mesmo dentro da hora e o navegador reaproveita o cache


def _q(s: str, safe: str = "-_.~") -> str:
    return quote(s, safe=safe)


def presign_get(chave: str, now: datetime | None = None) -> str | None:
    s = get_settings()
    if not (s.meuwatt_r2_endpoint and s.meuwatt_r2_bucket and s.meuwatt_r2_access_key_id
            and s.meuwatt_r2_secret_access_key):
        return None
    hora = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    t = hora.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{t[:8]}/auto/s3/aws4_request"
    host = urlsplit(s.meuwatt_r2_endpoint).netloc
    uri = _q(f"/{s.meuwatt_r2_bucket}/{chave}", safe="/-_.~")
    q = {"X-Amz-Algorithm": "AWS4-HMAC-SHA256", "X-Amz-Credential": f"{s.meuwatt_r2_access_key_id}/{scope}",
         "X-Amz-Date": t, "X-Amz-Expires": str(LINK_S), "X-Amz-SignedHeaders": "host"}
    qs = "&".join(f"{_q(k)}={_q(v)}" for k, v in sorted(q.items()))
    canonical = "\n".join(["GET", uri, qs, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", t, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = ("AWS4" + s.meuwatt_r2_secret_access_key).encode()
    for part in (t[:8], "auto", "s3", "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    return f"https://{host}{uri}?{qs}&X-Amz-Signature={hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()}"
