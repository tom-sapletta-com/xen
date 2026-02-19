"""Integration tests for xeen server API endpoints."""

import os
import sys
import json
import base64
import shutil
import tempfile
from pathlib import Path
from io import BytesIO

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set test data dir before importing server
_test_data_dir = tempfile.mkdtemp(prefix="xeen_test_")
os.environ["XEEN_DATA_DIR"] = _test_data_dir

from fastapi.testclient import TestClient
from xeen.server import app


@pytest.fixture(autouse=True)
def clean_test_data():
    """Clean test data between tests."""
    sessions_dir = Path(_test_data_dir) / "sessions"
    if sessions_dir.exists():
        shutil.rmtree(sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    yield
    # Cleanup after all tests
    if Path(_test_data_dir).exists():
        shutil.rmtree(_test_data_dir, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


def _create_test_image(width=100, height=100, color="red") -> bytes:
    """Create a test PNG image in memory."""
    img = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def _create_test_session(name="test_session"):
    """Create a minimal test session with frames."""
    session_dir = Path(_test_data_dir) / "sessions" / name
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "frames").mkdir(exist_ok=True)

    # Create 3 test frames
    for i in range(3):
        img = Image.new("RGB", (100, 100), ["red", "green", "blue"][i])
        img.save(session_dir / "frames" / f"frame_{i:04d}.png", "PNG")

    meta = {
        "name": name,
        "created_at": "2025-01-01T00:00:00",
        "duration": 3.0,
        "frame_count": 3,
        "settings": {"source": "test"},
        "frames": [
            {
                "index": i,
                "timestamp": float(i),
                "filename": f"frame_{i:04d}.png",
                "width": 100,
                "height": 100,
                "change_pct": 100.0 if i == 0 else 50.0,
                "mouse_x": 50,
                "mouse_y": 50,
                "suggested_center_x": 50,
                "suggested_center_y": 50,
                "input_events": [],
            }
            for i in range(3)
        ],
        "input_log": [],
    }
    (session_dir / "session.json").write_text(json.dumps(meta, indent=2))
    return name


# ─── Sessions API ────────────────────────────────────────────────────────────

class TestSessionsAPI:
    def test_list_sessions_empty(self, client):
        res = client.get("/api/sessions")
        assert res.status_code == 200
        assert res.json() == []

    def test_list_sessions_with_data(self, client):
        _create_test_session("sess1")
        res = client.get("/api/sessions")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["name"] == "sess1"

    def test_get_session(self, client):
        _create_test_session("sess1")
        res = client.get("/api/sessions/sess1")
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "sess1"
        assert data["frame_count"] == 3

    def test_get_session_not_found(self, client):
        res = client.get("/api/sessions/nonexistent")
        assert res.status_code == 404

    def test_get_frame_image(self, client):
        _create_test_session("sess1")
        res = client.get("/api/sessions/sess1/frames/frame_0000.png")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"

    def test_get_frame_not_found(self, client):
        _create_test_session("sess1")
        res = client.get("/api/sessions/sess1/frames/nonexistent.png")
        assert res.status_code == 404

    def test_delete_session(self, client):
        _create_test_session("sess1")
        res = client.delete("/api/sessions/sess1")
        assert res.status_code == 200
        assert res.json()["ok"] is True
        # Verify deleted
        res2 = client.get("/api/sessions/sess1")
        assert res2.status_code == 404


# ─── Upload API ──────────────────────────────────────────────────────────────

class TestUploadAPI:
    def test_upload_screenshots(self, client):
        img_bytes = _create_test_image()
        res = client.post(
            "/api/sessions/upload",
            files=[
                ("files", ("test1.png", img_bytes, "image/png")),
                ("files", ("test2.png", img_bytes, "image/png")),
            ],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["frame_count"] == 2
        assert data["name"].startswith("upload_")


# ─── Frame Selection API ─────────────────────────────────────────────────────

class TestFrameSelectionAPI:
    def test_save_selection(self, client):
        _create_test_session("sess1")
        res = client.post(
            "/api/sessions/sess1/select",
            json={"selected_indices": [0, 2]},
        )
        assert res.status_code == 200
        assert res.json()["selected"] == 2

    def test_save_selection_not_found(self, client):
        res = client.post(
            "/api/sessions/nonexistent/select",
            json={"selected_indices": [0]},
        )
        assert res.status_code == 404


# ─── Center Marking API ─────────────────────────────────────────────────────

class TestCenterMarkingAPI:
    def test_save_centers(self, client):
        _create_test_session("sess1")
        res = client.post(
            "/api/sessions/sess1/centers",
            json={"marks": [{"frame_index": 0, "center_x": 30, "center_y": 40}]},
        )
        assert res.status_code == 200
        assert res.json()["ok"] is True

        # Verify saved
        meta = client.get("/api/sessions/sess1").json()
        assert meta["custom_centers"]["0"]["x"] == 30
        assert meta["custom_centers"]["0"]["y"] == 40


# ─── Crop Preview API ───────────────────────────────────────────────────────

class TestCropPreviewAPI:
    def test_crop_preview(self, client):
        _create_test_session("sess1")
        res = client.post(
            "/api/sessions/sess1/crop-preview",
            json={"preset": None, "custom_w": 50, "custom_h": 50},
        )
        assert res.status_code == 200
        data = res.json()
        assert "previews" in data
        assert len(data["previews"]) == 3  # all frames


# ─── Browser Capture API ────────────────────────────────────────────────────

class TestBrowserCaptureAPI:
    def test_capture_frame(self, client):
        img = Image.new("RGB", (100, 100), "red")
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        image_data = f"data:image/png;base64,{b64}"

        res = client.post(
            "/api/capture/frame",
            json={
                "session_name": "browser_test",
                "frame_index": 0,
                "image_data": image_data,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["width"] == 100
        assert data["height"] == 100

    def test_capture_finalize(self, client):
        # First create a frame
        img = Image.new("RGB", (100, 100), "blue")
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        client.post(
            "/api/capture/frame",
            json={
                "session_name": "browser_final",
                "frame_index": 0,
                "image_data": f"data:image/png;base64,{b64}",
            },
        )

        # Finalize
        res = client.post(
            "/api/capture/finalize",
            json={
                "session_name": "browser_final",
                "frame_count": 1,
                "duration": 2.0,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "browser_final"
        assert data["frame_count"] == 1

        # Verify session exists
        res2 = client.get("/api/sessions/browser_final")
        assert res2.status_code == 200
        meta = res2.json()
        assert meta["settings"]["source"] == "browser_capture"

    def test_get_backends(self, client):
        res = client.get("/api/capture/backends")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        names = [b["name"] for b in data]
        assert "browser" in names


# ─── Frontend Routes ────────────────────────────────────────────────────────

class TestFrontendRoutes:
    def test_capture_page(self, client):
        res = client.get("/capture")
        assert res.status_code == 200
        assert "getDisplayMedia" in res.text
        assert "xeen" in res.text
