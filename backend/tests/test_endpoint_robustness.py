"""Dayanıklılık: hiçbir API ucu bozuk/boş girdide 5xx (sunucu hatası) vermemeli.

Tüm /api/ rotaları gezilir; GET ve yazma yöntemleri (POST/PATCH/PUT/DELETE) boş, tür hatalı ve
anlamsız gövdelerle üç farklı rolle çağrılır. Geri yükleme/oturum kapatma gibi süreci bozan uçlar hariç.
"""
import re

import pytest
from django.urls import get_resolver

SKIP = re.compile(r"restore|logout|lock|backup/run|wipe|reset|shutdown|update/apply|install")
PAYLOADS = [{}, {"id": None, "qty": "abc", "amount": -1, "method": 5}, {"product": 10**12, "ticket": "x", "items": "not-a-list"}, []]


def _routes():
    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern)

    out = set()
    for r in walk(get_resolver().url_patterns):
        r = re.sub(r"\(\?P<\w+>[^)]*\)", "1", r)
        r = re.sub(r"<(?:int:|str:|uuid:|slug:)?\w+>", "1", r)
        r = r.replace("^", "").replace("$", "").replace("?", "")
        if r.startswith("api/") and "\\" not in r and "format" not in r and not SKIP.search(r):
            out.add("/" + r.rstrip("/") + "/")
    return sorted(out)


ROUTES = _routes()


@pytest.mark.parametrize("who", ["owner", "cashier", "waiter"])
def test_no_server_errors_on_junk_input(api, env, open_cash, who):
    user = {"owner": env.owner, "cashier": env.cashier, "waiter": env.waiter}[who]
    c = api(user)
    c.raise_request_exception = False
    failures = []
    for url in ROUTES:
        for method in ("get", "post", "patch", "delete"):
            for body in ([None] if method in ("get", "delete") else PAYLOADS):
                kw = {} if body is None else {"data": body, "format": "json"}
                resp = getattr(c, method)(url, **kw)
                if resp.status_code >= 500:
                    failures.append(f"{method.upper()} {url} {body!r} -> {resp.status_code}")
    assert not failures, "\n".join(failures[:40])
