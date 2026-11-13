"""HTTP-Client mit Retries und Datei-Cache."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

USER_AGENT = "konjunkturwolf/0.1 (+https://github.com/wfhungerland/konjunkturwolf)"


class FetchError(RuntimeError):
    """Abruf fehlgeschlagen (Netz, HTTP-Status oder Inhalt)."""


@dataclass
class Response:
    text: str
    url: str
    retrieved_at: datetime
    from_cache: bool
    content_type: str = ""
    raw: bytes = b""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class HttpClient:
    def __init__(
        self,
        cache_dir: str | Path,
        ttl_hours: float = 20,
        use_cache: bool = True,
        offline: bool = False,
        timeout: float = 60,
        retries: int = 4,
        pause: float = 0.3,
    ):
        self.cache_dir = Path(cache_dir)
        self.ttl = timedelta(hours=ttl_hours)
        self.use_cache = use_cache
        self.offline = offline
        self.timeout = timeout
        self.pause = pause
        self._memo: dict[Path, Response] = {}  # gleiche Anfrage nur einmal je Lauf
        self._down: set[str] = set()  # Hosts ohne Antwort in diesem Lauf: weitere Abrufe dort sofort überspringen
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        retry = Retry(
            total=retries,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    # -- Cache -----------------------------------------------------------
    def _cache_paths(self, method: str, url: str, params: Any, data: Any, accept: str) -> tuple[Path, Path]:
        key = json.dumps([method, url, params or {}, data or {}, accept], sort_keys=True)
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
        return self.cache_dir / f"{digest}.body", self.cache_dir / f"{digest}.json"

    def _read_cache(self, body: Path, meta: Path) -> Response | None:
        if not (body.exists() and meta.exists()):
            return None
        info = json.loads(meta.read_text(encoding="utf-8"))
        raw = body.read_bytes()
        return Response(
            text=raw.decode("utf-8", errors="replace"),
            url=info["url"],
            retrieved_at=datetime.fromisoformat(info["retrieved_at"]),
            from_cache=True,
            content_type=info.get("content_type", ""),
            raw=raw,
        )

    def _write_cache(self, body: Path, meta: Path, resp: Response) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        body.write_bytes(resp.raw or resp.text.encode("utf-8"))
        meta.write_text(
            json.dumps(
                {"url": resp.url, "retrieved_at": resp.retrieved_at.isoformat(), "content_type": resp.content_type}
            ),
            encoding="utf-8",
        )

    # -- Abruf -----------------------------------------------------------
    def request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        accept: str = "",
    ) -> Response:
        """Ruft eine URL ab. Zugangsdaten gehören in 'headers' (nie im Cache-Schlüssel)."""
        body_path, meta_path = self._cache_paths(method, url, params, data, accept)
        if body_path in self._memo:
            return self._memo[body_path]
        cached = self._read_cache(body_path, meta_path) if (self.use_cache or self.offline) else None
        if cached and (self.offline or _now() - cached.retrieved_at < self.ttl):
            return cached
        if self.offline:
            raise FetchError("Offline-Modus und kein Cache vorhanden.")

        host = urlparse(url).netloc
        if host in self._down:
            if cached:
                return cached
            raise FetchError(f"Netzwerkfehler: {host} antwortete in diesem Lauf nicht; Abruf übersprungen")
        hdrs = dict(headers or {})
        if accept:
            hdrs["Accept"] = accept
        try:
            time.sleep(self.pause)
            r = self.session.request(method, url, params=params, data=data, headers=hdrs, timeout=self.timeout)
        except requests.RequestException as exc:
            if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
                self._down.add(host)  # ein Ausfall kostet mit allen Wiederholungen Minuten; nicht für jede Reihe erneut
            if cached:
                log.warning("Abruf fehlgeschlagen, nutze veralteten Cache: %s", exc)
                return cached
            raise FetchError(f"Netzwerkfehler: {exc.__class__.__name__}: {exc}") from exc

        if r.status_code >= 400:
            snippet = " ".join(r.text[:300].split())
            if cached and r.status_code >= 500:
                log.warning("HTTP %s, nutze veralteten Cache", r.status_code)
                return cached
            raise FetchError(f"HTTP {r.status_code} für {r.url}: {snippet}")

        r.encoding = r.encoding or "utf-8"
        if r.encoding.lower() == "iso-8859-1" and "csv" in r.headers.get("Content-Type", ""):
            r.encoding = "utf-8"
        resp = Response(
            text=r.text,
            url=_public_url(r.url),
            retrieved_at=_now(),
            from_cache=False,
            content_type=r.headers.get("Content-Type", ""),
            raw=r.content,
        )
        if self.use_cache:
            self._write_cache(body_path, meta_path, resp)
        self._memo[body_path] = resp
        return resp

    def get(self, url: str, params: dict[str, Any] | None = None, accept: str = "", headers: dict[str, str] | None = None) -> Response:
        return self.request("GET", url, params=params, accept=accept, headers=headers)

    def post(self, url: str, data: dict[str, Any] | None = None, headers: dict[str, str] | None = None, accept: str = "") -> Response:
        return self.request("POST", url, data=data, headers=headers, accept=accept)


def get_bytes(client: "HttpClient", url: str) -> tuple[bytes, datetime, bool]:
    """Lädt eine Binärdatei (z.B. xlsx) mit Retries und Datei-Cache."""
    key = hashlib.sha256(("BYTES " + url).encode()).hexdigest()[:24]
    body, meta = client.cache_dir / f"{key}.bin", client.cache_dir / f"{key}.json"
    if (client.use_cache or client.offline) and body.exists() and meta.exists():
        when = datetime.fromisoformat(json.loads(meta.read_text(encoding="utf-8"))["retrieved_at"])
        if client.offline or _now() - when < client.ttl:
            return body.read_bytes(), when, True
    if client.offline:
        raise FetchError("Offline-Modus und kein Cache vorhanden.")
    host = urlparse(url).netloc
    if host in client._down:
        raise FetchError(f"Netzwerkfehler: {host} antwortete in diesem Lauf nicht; Abruf übersprungen")
    try:
        r = client.session.get(url, timeout=client.timeout * 3)
    except requests.RequestException as exc:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            client._down.add(host)
        raise FetchError(f"Netzwerkfehler: {exc.__class__.__name__}: {exc}") from exc
    if r.status_code >= 400:
        raise FetchError(f"HTTP {r.status_code} für {url}")
    when = _now()
    client.cache_dir.mkdir(parents=True, exist_ok=True)
    body.write_bytes(r.content)
    meta.write_text(json.dumps({"url": url, "retrieved_at": when.isoformat()}), encoding="utf-8")
    return r.content, when, False


def _public_url(url: str) -> str:
    """Entfernt eventuelle Zugangsdaten aus Query-Strings."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in {"username", "password", "token"}]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
