"""Ein Host, der nicht antwortet, wird im selben Lauf nur einmal versucht."""
import pytest
import requests

from konjunkturwolf.http import FetchError, HttpClient


def test_host_ohne_antwort_wird_uebersprungen(tmp_path, monkeypatch):
    c = HttpClient(tmp_path, use_cache=False, pause=0)
    calls = []

    def boom(*a, **k):
        calls.append(a[1])
        raise requests.ConnectionError("Read timed out")

    monkeypatch.setattr(c.session, "request", boom)
    with pytest.raises(FetchError):
        c.get("https://langsam.example/a")
    with pytest.raises(FetchError, match="übersprungen"):
        c.get("https://langsam.example/b")
    assert calls == ["https://langsam.example/a"]


def test_http_fehler_sperrt_host_nicht(tmp_path, monkeypatch):
    c = HttpClient(tmp_path, use_cache=False, pause=0)

    class R:
        status_code, text, url = 404, "fehlt", "https://da.example/a"

    monkeypatch.setattr(c.session, "request", lambda *a, **k: R())
    for u in ("https://da.example/a", "https://da.example/b"):
        with pytest.raises(FetchError, match="HTTP 404"):
            c.get(u)
    assert not c._down
