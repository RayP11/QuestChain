"""The approved specialist artwork follows the existing level progression."""

import hashlib
from pathlib import Path
import struct
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from questchain.gateway import server
from questchain.progression import ProgressionManager


STATIC = Path(server.__file__).resolve().parent.parent / "static"
SPECIALISTS = {
    "Explorer": "researcher",
    "Keeper": "workspace",
    "Builder": "builder",
    "Scheduler": "scheduler",
}
MAIN_IMAGES = ["Pixel_idle.png", "evolve2.png", "draft-evolve-3.png"]


@pytest.fixture
def image_client(monkeypatch):
    state = SimpleNamespace(class_name="Explorer", level=1)

    def get_agent(agent_id=""):
        if agent_id and agent_id != "test-agent":
            return None
        return {"id": "test-agent", "class_name": state.class_name}

    monkeypatch.setattr(
        server, "_agent_manager",
        SimpleNamespace(get=get_agent, get_active=get_agent),
    )
    monkeypatch.setattr(
        ProgressionManager, "load", lambda self: SimpleNamespace(level=state.level),
    )
    with TestClient(server.app, base_url="http://localhost") as client:
        yield client, state


@pytest.mark.parametrize("class_name,prefix", SPECIALISTS.items())
@pytest.mark.parametrize("level,stage", [(1, 1), (5, 1), (6, 2), (10, 2), (11, 3), (100, 3)])
def test_specialist_image_at_each_evolution_boundary(image_client, class_name, prefix, level, stage):
    client, state = image_client
    state.class_name, state.level = class_name, level
    response = client.get("/agent-image", params={"agent_id": "test-agent"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == (STATIC / f"{prefix}-stage-{stage}.png").read_bytes()


@pytest.mark.parametrize("class_name", ["Router", "Custom", "Unknown"])
@pytest.mark.parametrize("level,stage", [(1, 0), (6, 1), (11, 2)])
def test_main_custom_and_fallback_keep_original_artwork(image_client, class_name, level, stage):
    client, state = image_client
    state.class_name, state.level = class_name, level
    response = client.get("/agent-image", params={"agent_id": "test-agent"})
    assert response.status_code == 200
    assert response.content == (STATIC / MAIN_IMAGES[stage]).read_bytes()


def test_active_agent_and_repeated_stage_switches(image_client):
    client, state = image_client
    for class_name, prefix in [*SPECIALISTS.items(), *reversed(SPECIALISTS.items())]:
        state.class_name = class_name
        for level, stage in [(1, 1), (11, 3), (6, 2), (1, 1)]:
            state.level = level
            response = client.get("/agent-image")
            assert response.status_code == 200
            assert response.content == (STATIC / f"{prefix}-stage-{stage}.png").read_bytes()


def test_missing_agent_still_returns_404(image_client):
    client, _ = image_client
    assert client.get("/agent-image?agent_id=missing").status_code == 404


def test_missing_manager_still_returns_404(monkeypatch):
    monkeypatch.setattr(server, "_agent_manager", None)
    with TestClient(server.app, base_url="http://localhost") as client:
        assert client.get("/agent-image").status_code == 404


@pytest.mark.parametrize("prefix", SPECIALISTS.values())
@pytest.mark.parametrize("stage", [1, 2, 3])
def test_specialist_assets_are_square_rgba_pngs(prefix, stage):
    data = (STATIC / f"{prefix}-stage-{stage}.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", data[16:29],
    )
    assert width == height == 1254
    assert (depth, color, compression, filtering, interlace) == (8, 6, 0, 0, 0)


def test_original_main_artwork_bytes_are_preserved():
    expected = {
        "Pixel_idle.png": "82d3a70615d2537fd87342008c51e135fd9b02df217f51311723d1015f4d3536",
        "evolve2.png": "4988abd9c1c186aa20849b3530ad29d8f61f5d667f0fd1bdb0be96e07fbdd1a1",
        "draft-evolve-3.png": "96b21b7b5c1732f6beb76ddd94900fdcb8fb8630c780e0ed15440bde94df410b",
        "pixel_think.png": "f86dcec2a51a5caf8e8ed179d014ee81fbca3336241074fe4e4e4994affa7c46",
    }
    for filename, digest in expected.items():
        assert hashlib.sha256((STATIC / filename).read_bytes()).hexdigest() == digest
