"""
One HTTP fetch and one disk cache for the reference-data feeds.

The sovereign-yield and country-risk modules both pull small public files
(FRED CSVs, the ECB yield curve, Damodaran's spreadsheet). They share this so
that a test can switch the network off in one place, and so a basket of runs
on one host reads each file once rather than once per company.

The cache lives in VYNN_CACHE_DIR, or /data/.cache when the analysis volume is
mounted, or nowhere: a missing cache is a slower run, never a failed one.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Optional

# vynnai.com: vynn.ai is another company's domain.
_UA = "VYNN/1.0 (+https://vynnai.com; reference data)"
# The SEC asks automated clients to identify themselves with a contact email (sec.gov/os/accessing-edgar-data).
# The owner chose this address on 22 Nov 2026; SEC_CONTACT_EMAIL overrides it. Sent to sec.gov hosts only.
_SEC_CONTACT_EMAIL = "zanwen@vynnai.com"


def _user_agent(url: str) -> str:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if host == "sec.gov" or host.endswith(".sec.gov"):
        return f"VYNN AI {os.getenv('SEC_CONTACT_EMAIL', '').strip() or _SEC_CONTACT_EMAIL}"
    return _UA


def http_get(url: str, timeout: float = 8.0, max_bytes: Optional[int] = None) -> bytes:
    """Raw bytes of ``url`` (the first ``max_bytes`` when given); raises on any failure.

    Tests replace this.
    """
    import requests
    if max_bytes is None:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": _user_agent(url)})
        r.raise_for_status()
        return r.content
    with requests.get(url, timeout=timeout, headers={"User-Agent": _user_agent(url)}, stream=True) as r:
        r.raise_for_status()
        out = bytearray()
        for chunk in r.iter_content(65536):
            out += chunk
            if len(out) >= max_bytes:
                break
        return bytes(out[:max_bytes])


def http_post(url: str, body: bytes, timeout: float = 8.0) -> bytes:
    """POST a JSON body; raw bytes back; raises on any failure. Tests replace this."""
    import requests
    r = requests.post(url, data=body, timeout=timeout,
                      headers={"User-Agent": _user_agent(url), "Content-Type": "application/json"})
    r.raise_for_status()
    return r.content


def cache_dir() -> Optional[str]:
    d = os.getenv("VYNN_CACHE_DIR")
    if not d:
        if not os.path.isdir("/data"):
            return None
        d = "/data/.cache"
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    return d if os.access(d, os.W_OK) else None


def cache_get(name: str, max_age_seconds: float) -> Optional[Any]:
    d = cache_dir()
    if not d:
        return None
    path = os.path.join(d, name + ".json")
    try:
        if time.time() - os.path.getmtime(path) > max_age_seconds:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def cache_put(name: str, obj: Any) -> None:
    """Atomic write, so two concurrent runs never leave a half-written file."""
    d = cache_dir()
    if not d:
        return
    path = os.path.join(d, name + ".json")
    try:
        fd, tmp = tempfile.mkstemp(dir=d, prefix=name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        os.replace(tmp, path)
    except OSError:
        pass
