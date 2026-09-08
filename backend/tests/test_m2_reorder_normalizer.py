"""Test M2: Media Normalizer + riordino timeline + settings + anteprime file."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.pipeline import state as state_store
from app.agents import normalizer


@pytest.fixture()
def isolated_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _upload_image(client: TestClient, pid: str, name: str, size, color="red"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    buf.seek(0)
    resp = client.post(
        f"/api/projects/{pid}/media", files=[("files", (name, buf, "image/jpeg"))]
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_project_with_3(client: TestClient):
    proj = client.post("/api/projects").json()
    pid = proj["project_id"]
    data = _upload_image(client, pid, "wide.jpg", (1920, 1080), "red")
    assert data["media"][-1]["orientation"] == "landscape"
    data = _upload_image(client, pid, "tall.jpg", (1080, 1920), "blue")
    assert data["media"][-1]["orientation"] == "portrait"
    data = _upload_image(client, pid, "sq.jpg", (800, 800), "green")
    assert data["media"][-1]["orientation"] == "square"
    return pid, data


@pytest.mark.asyncio
async def test_normalizer_fit_rules():
    state = state_store.new_project_state()
    state["media"] = [
        {"id": "a", "orientation": "landscape", "width": 1920, "height": 1080, "order_index": 5},
        {"id": "b", "orientation": "portrait", "width": 1080, "height": 1920, "order_index": 2},
        {"id": "c", "orientation": "square", "width": 800, "height": 800, "order_index": 9},
    ]
    out = await normalizer.run(state)
    by_id = {m["id"]: m for m in out["media"]}
    # order_index rinormalizzati contigui preservando l'ordine relativo (b, a, c)
    assert [m["id"] for m in out["media"]] == ["b", "a", "c"]
    assert [m["order_index"] for m in out["media"]] == [0, 1, 2]
    # fit rules: landscape/square cover senza sfondo, portrait contain + blur default
    assert by_id["a"]["fit_mode"] == "cover" and by_id["a"]["background_fill"] is None
    assert by_id["c"]["fit_mode"] == "cover" and by_id["c"]["background_fill"] is None
    assert by_id["b"]["fit_mode"] == "contain" and by_id["b"]["background_fill"] == "blur"


@pytest.mark.asyncio
async def test_normalizer_respects_output_spec_and_item_override():
    state = state_store.new_project_state()
    state["output_spec"]["background_fill"] = "solid_color"
    state["media"] = [
        {"id": "p1", "orientation": "portrait", "width": 100, "height": 200, "order_index": 0},
        {"id": "p2", "orientation": "portrait", "width": 100, "height": 200,
         "order_index": 1, "background_fill": "blur"},
    ]
    out = await normalizer.run(state)
    by_id = {m["id"]: m for m in out["media"]}
    assert by_id["p1"]["background_fill"] == "solid_color"  # default di progetto
    assert by_id["p2"]["background_fill"] == "blur"  # override per-item preservato
    for m in out["media"]:
        assert m["fit_mode"] == "contain"


def test_upload_applies_normalizer(isolated_projects):
    client = TestClient(app)
    pid, data = _make_project_with_3(client)
    by_orient = {m["orientation"]: m for m in data["media"]}
    assert by_orient["landscape"]["fit_mode"] == "cover"
    assert by_orient["landscape"]["background_fill"] is None
    assert by_orient["portrait"]["fit_mode"] == "contain"
    assert by_orient["portrait"]["background_fill"] == "blur"
    assert by_orient["square"]["fit_mode"] == "cover"
    assert sorted(m["order_index"] for m in data["media"]) == [0, 1, 2]


def test_reorder_ok_and_persisted(isolated_projects):
    client = TestClient(app)
    pid, data = _make_project_with_3(client)
    ids = [m["id"] for m in sorted(data["media"], key=lambda m: m["order_index"])]
    reversed_ids = list(reversed(ids))
    resp = client.put(f"/api/projects/{pid}/media/order", json={"media_ids": reversed_ids})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [m["id"] for m in sorted(body["media"], key=lambda m: m["order_index"])] == reversed_ids
    assert sorted(m["order_index"] for m in body["media"]) == [0, 1, 2]
    # persistenza: GET conferma il nuovo ordine
    got = client.get(f"/api/projects/{pid}").json()
    assert [m["id"] for m in sorted(got["media"], key=lambda m: m["order_index"])] == reversed_ids


def test_reorder_rejects_bad_payloads(isolated_projects):
    client = TestClient(app)
    pid, data = _make_project_with_3(client)
    ids = [m["id"] for m in data["media"]]
    # id mancante
    assert client.put(f"/api/projects/{pid}/media/order",
                      json={"media_ids": ids[:2]}).status_code == 400
    # id sconosciuto
    assert client.put(f"/api/projects/{pid}/media/order",
                      json={"media_ids": [ids[0], ids[1], "zzz"]}).status_code == 400
    # duplicati
    assert client.put(f"/api/projects/{pid}/media/order",
                      json={"media_ids": [ids[0], ids[0], ids[2]]}).status_code == 400
    # progetto inesistente
    assert client.put("/api/projects/inesistente/media/order",
                      json={"media_ids": ids}).status_code == 404


def test_update_media_background_fill(isolated_projects):
    client = TestClient(app)
    pid, data = _make_project_with_3(client)
    portrait = next(m for m in data["media"] if m["orientation"] == "portrait")
    landscape = next(m for m in data["media"] if m["orientation"] == "landscape")

    resp = client.patch(f"/api/projects/{pid}/media/{portrait['id']}",
                        json={"background_fill": "solid_color"})
    assert resp.status_code == 200, resp.text
    upd = next(m for m in resp.json()["media"] if m["id"] == portrait["id"])
    assert upd["background_fill"] == "solid_color"
    assert upd["fit_mode"] == "contain"

    # landscape: la preferenza viene normalizzata a None (cover riempie il frame)
    resp2 = client.patch(f"/api/projects/{pid}/media/{landscape['id']}",
                         json={"background_fill": "solid_color"})
    assert resp2.status_code == 200, resp2.text
    upd2 = next(m for m in resp2.json()["media"] if m["id"] == landscape["id"])
    assert upd2["fit_mode"] == "cover" and upd2["background_fill"] is None

    assert client.patch(f"/api/projects/{pid}/media/inesistente",
                        json={"background_fill": "blur"}).status_code == 404


def test_update_settings_propagates_and_validates(isolated_projects):
    client = TestClient(app)
    pid, data = _make_project_with_3(client)
    resp = client.patch(f"/api/projects/{pid}/settings",
                        json={"background_fill": "solid_color",
                              "resolution": "3840x2160", "fps": 60})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["output_spec"]["background_fill"] == "solid_color"
    assert body["output_spec"]["resolution"] == "3840x2160"
    assert body["output_spec"]["fps"] == 60
    portrait = next(m for m in body["media"] if m["orientation"] == "portrait")
    assert portrait["background_fill"] == "solid_color"

    assert client.patch(f"/api/projects/{pid}/settings",
                        json={"resolution": "ciao"}).status_code == 400
    assert client.patch(f"/api/projects/{pid}/settings",
                        json={"fps": 123}).status_code == 400


def test_media_file_serving(isolated_projects):
    client = TestClient(app)
    pid, data = _make_project_with_3(client)
    mid = data["media"][0]["id"]
    resp = client.get(f"/api/projects/{pid}/media/{mid}/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
    assert len(resp.content) > 0
    assert client.get(f"/api/projects/{pid}/media/inesistente/file").status_code == 404
