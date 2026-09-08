"""Regressione download Drive sul percorso REALE (prima era sempre mockato):
MediaIoBaseDownload con HTTP finto a Range, size-cap preventivo, file vuoti,
errori HTTP mappati. Niente rete."""
import asyncio
import tempfile
from pathlib import Path

import pytest
from googleapiclient.errors import HttpError

from app.jobs import manager as jobs
from app.services import drive_client as dc


class FakeResp(dict):
    def __init__(self, status, **headers):
        super().__init__(**headers)
        self.status = status
        self.reason = "x"


class FakeHttp:
    def __init__(self, payload: bytes, mode="ranges"):
        self.payload = payload
        self.mode = mode
        self.calls = 0

    def request(self, uri, method="GET", body=None, headers=None):
        self.calls += 1
        if self.mode == "error401":
            return FakeResp(401), b"unauthorized"
        if self.mode == "empty":
            return FakeResp(416, **{"content-range": "bytes */0"}), b""
        total = len(self.payload)
        rng = (headers or {}).get("range", "")
        if self.mode == "full" or not rng.startswith("bytes="):
            return FakeResp(200, **{"content-length": str(total)}), self.payload
        lo, hi = rng[len("bytes="):].split("-")
        lo, hi = int(lo), min(int(hi), total - 1)
        return (FakeResp(206, **{"content-range": f"bytes {lo}-{hi}/{total}"}),
                self.payload[lo:hi + 1])


class FakeRequest:
    def __init__(self, http, uri="https://www.googleapis.com/drive/v3/files/x?alt=media"):
        self.http = http
        self.uri = uri
        self.headers = {}


class _Req:
    def __init__(self, p): self._p = p
    def execute(self): return self._p


def _svc_for(meta, http):
    class Files:
        def get(self, fileId, fields=None): return _Req(meta)
        def get_media(self, fileId): return FakeRequest(http)
    class Svc:
        def files(self): return Files()
    return Svc()


PAYLOAD = bytes(range(256)) * 20000      # ~5MB
BIG = bytes(range(256)) * 50000          # ~12.8MB -> 2 chunk da 10MB


def test_execute_download_ranges_and_full(tmp_path):
    d1 = tmp_path / "f1.bin"
    assert dc._execute_download(FakeRequest(FakeHttp(BIG)), d1) == len(BIG)
    assert d1.read_bytes() == BIG
    d2 = tmp_path / "f2.bin"
    assert dc._execute_download(FakeRequest(FakeHttp(PAYLOAD, mode="full")), d2) == len(PAYLOAD)
    assert d2.read_bytes() == PAYLOAD


def test_execute_download_http_error_propagates(tmp_path):
    with pytest.raises(HttpError):
        dc._execute_download(FakeRequest(FakeHttp(b"", mode="error401")), tmp_path / "f3.bin")


def test_download_file_end_to_end(tmp_path):
    meta = {"id": "f1", "name": "foto.jpg", "mimeType": "image/jpeg",
            "size": str(len(PAYLOAD))}
    dest = tmp_path / "foto.jpg"
    assert dc.download_file(_svc_for(meta, FakeHttp(PAYLOAD)), "f1", dest) == len(PAYLOAD)
    assert dest.read_bytes() == PAYLOAD


def test_download_file_empty_is_explicit_error(tmp_path):
    meta = {"id": "f1", "name": "foto.jpg", "mimeType": "image/jpeg"}
    dest = tmp_path / "vuoto.jpg"
    with pytest.raises(RuntimeError, match="vuoto"):
        dc.download_file(_svc_for(meta, FakeHttp(b"", mode="empty")), "f1", dest)
    assert not dest.exists()


def test_download_file_size_cap_before_network(tmp_path):
    http = FakeHttp(PAYLOAD)
    meta = {"id": "f9", "name": "huge.mp4", "mimeType": "video/mp4",
            "size": str(dc.MAX_DOWNLOAD_BYTES + 1)}
    with pytest.raises(ValueError, match="troppo grande"):
        dc.download_file(_svc_for(meta, http), "f9", tmp_path / "huge.mp4")
    assert http.calls == 0


def test_download_file_native_google_doc_rejected(tmp_path):
    meta = {"id": "d", "name": "doc", "mimeType": "application/vnd.google-apps.document"}
    with pytest.raises(ValueError, match="nativo Google"):
        dc.download_file(_svc_for(meta, FakeHttp(PAYLOAD)), "d", tmp_path / "doc")


def test_download_file_401_is_friendly(tmp_path):
    meta = {"id": "f1", "name": "a.jpg", "mimeType": "image/jpeg"}
    with pytest.raises(RuntimeError, match="401"):
        dc.download_file(_svc_for(meta, FakeHttp(b"", mode="error401")), "f1", tmp_path / "a.jpg")


async def test_worker_survives_unexpected_error(monkeypatch):
    """Il worker non deve mai morire: altrimenti i job restano in coda all'infinito."""
    calls = {"n": 0}

    def flaky_claim():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disco illeggibile")
        return None

    monkeypatch.setattr(jobs, "_claim", flaky_claim)
    task = asyncio.create_task(jobs.worker_loop(poll_sec=0.01))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls["n"] >= 2


async def _run_import_with(state, monkeypatch, **timeouts):
    from app.agents import drive_import
    for k, v in timeouts.items():
        monkeypatch.setattr(dc, k, v)
    return await drive_import.run(state)


def _base_state(pid="p1"):
    return {"project_id": pid, "media": [], "media_staging": [],
            "errors": [], "pipeline_log": []}


async def test_import_service_timeout_is_explicit(monkeypatch):
    """Stallo in get_drive_service -> errore chiaro, non hang infinito."""
    import time as _t

    def slow_service():
        _t.sleep(5)

    monkeypatch.setattr(dc, "get_drive_service", slow_service)
    state = _base_state()
    state["drive_import_request"] = {"file_ids": ["x"], "folder_ids": []}
    with pytest.raises(TimeoutError, match="connessione a Google Drive"):
        await _run_import_with(state, monkeypatch, SERVICE_TIMEOUT_SEC=0.2)
    assert any("connessione a Google Drive" in e["message"] for e in state["errors"])


async def test_import_expand_timeout_is_explicit(monkeypatch):
    """Stallo nell'esplorazione cartelle -> errore chiaro, non hang infinito."""
    import time as _t

    def slow_expand(service, file_ids, folder_ids):
        _t.sleep(5)
        return [], []

    monkeypatch.setattr(dc, "get_drive_service", lambda: object())
    monkeypatch.setattr(dc, "expand_selection", slow_expand)
    state = _base_state()
    state["drive_import_request"] = {"file_ids": [], "folder_ids": ["A"]}
    with pytest.raises(TimeoutError, match="esplorazione Drive"):
        await _run_import_with(state, monkeypatch, EXPAND_TIMEOUT_SEC=0.2)
    assert any("esplorazione Drive" in e["message"] for e in state["errors"])


def test_is_transient_error_classification():
    import ssl
    from googleapiclient.errors import HttpError

    def http_error(status):
        import types
        return HttpError(types.SimpleNamespace(status=status, reason="x"), b"no")

    assert dc.is_transient_error(ssl.SSLError("wrong version")) is True
    assert dc.is_transient_error(ConnectionResetError("reset")) is True
    assert dc.is_transient_error(http_error(500)) is True
    assert dc.is_transient_error(http_error(429)) is True
    assert dc.is_transient_error(http_error(401)) is False
    assert dc.is_transient_error(http_error(404)) is False
    assert dc.is_transient_error(dc.DriveDownloadError("x", transient=True)) is True
    assert dc.is_transient_error(dc.DriveDownloadError("x", transient=False)) is False
    assert dc.is_transient_error(ValueError("file troppo grande")) is False


async def test_download_retries_transient_then_succeeds(monkeypatch, tmp_path):
    """2 fallimenti SSL e poi ok: l'import riesce (niente attesa infinita, niente errore)."""
    import ssl
    from app.agents import drive_import

    calls = {"n": 0}

    def flaky(service, file_id, dest):
        calls["n"] += 1
        if calls["n"] < 3:
            raise dc.DriveDownloadError("connessione interrotta", transient=True)
        dest.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        return 103

    monkeypatch.setattr(dc, "download_file", flaky)
    monkeypatch.setattr(drive_import, "_retry_wait", lambda attempt: 0)
    r = await drive_import._download_one(
        lambda: object(), {"id": "f1", "name": "a.jpg"}, tmp_path, asyncio.Semaphore(2))
    assert "path" in r and calls["n"] == 3


async def test_download_gives_up_after_max_attempts(monkeypatch, tmp_path):
    """Errore transitorio persistente: errore esplicito con conteggio, senza doppio prefisso."""
    import ssl
    from app.agents import drive_import

    calls = {"n": 0}

    def always_ssl(service, file_id, dest):
        calls["n"] += 1
        raise dc.DriveDownloadError("PB080105.JPG: connessione sicura interrotta",
                                    transient=True)

    monkeypatch.setattr(dc, "download_file", always_ssl)
    monkeypatch.setattr(drive_import, "_retry_wait", lambda attempt: 0)
    monkeypatch.setattr(dc, "DOWNLOAD_MAX_ATTEMPTS", 3)
    r = await drive_import._download_one(
        lambda: object(), {"id": "f1", "name": "PB080105.JPG"}, tmp_path, asyncio.Semaphore(2))
    assert calls["n"] == 3
    msg = r["error"]["message"]
    assert "(dopo 3 tentativi)" in msg
    assert msg.count("download fallito") <= 1  # niente doppio prefisso


async def test_download_no_retry_on_permanent_error(monkeypatch, tmp_path):
    """401/404: un solo tentativo, messaggio chiaro subito."""
    from app.agents import drive_import

    calls = {"n": 0}

    def denied(service, file_id, dest):
        calls["n"] += 1
        raise dc.DriveDownloadError("a.jpg: sessione Google scaduta (HTTP 401)",
                                    transient=False)

    monkeypatch.setattr(dc, "download_file", denied)
    r = await drive_import._download_one(
        lambda: object(), {"id": "f1", "name": "a.jpg"}, tmp_path, asyncio.Semaphore(2))
    assert calls["n"] == 1 and "401" in r["error"]["message"]


async def test_download_no_retry_on_timeout(monkeypatch, tmp_path):
    """Timeout: niente secondo tentativo parallelo sullo stesso file."""
    import time as _t
    from app.agents import drive_import

    calls = {"n": 0}

    def slow(service, file_id, dest):
        calls["n"] += 1
        _t.sleep(5)

    monkeypatch.setattr(dc, "download_file", slow)
    monkeypatch.setattr(dc, "DOWNLOAD_TIMEOUT_SEC", 0.2)
    r = await drive_import._download_one(
        lambda: object(), {"id": "f1", "name": "lento.mp4"}, tmp_path, asyncio.Semaphore(2))
    assert calls["n"] == 1 and "timeout" in r["error"]["message"].lower()


async def test_each_download_gets_own_service(monkeypatch, tmp_path):
    """Regressione race httplib2: ogni download deve costruire il proprio
    service nel suo thread (mai condividere un Http tra thread paralleli)."""
    from app.agents import drive_import

    made = []
    seen_in_thread = []

    class FakeSvc:
        _n = 0

        def __init__(self):
            FakeSvc._n += 1
            self.n = FakeSvc._n

    def factory():
        svc = FakeSvc()
        made.append(svc.n)
        return svc

    def dl(service, file_id, dest):
        import threading
        seen_in_thread.append((service.n, threading.get_ident()))
        dest.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
        return 13

    monkeypatch.setattr(dc, "download_file", dl)
    sem = asyncio.Semaphore(6)
    results = await asyncio.gather(*[
        drive_import._download_one(factory, {"id": f"f{i}", "name": f"{i}.jpg"},
                                   tmp_path, sem)
        for i in range(6)
    ])
    assert all("path" in r for r in results)
    # un service fresco per ognuno dei 6 download
    assert sorted(made) == [1, 2, 3, 4, 5, 6]
    assert len({n for n, _t in seen_in_thread}) == 6
