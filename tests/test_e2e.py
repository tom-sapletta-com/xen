"""End-to-end tests for xeen: capture → edit → export pipeline."""

import os
import sys
import json
import shutil
import tempfile
import base64
from pathlib import Path
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_test_data_dir = tempfile.mkdtemp(prefix="xeen_e2e_")
os.environ["XEEN_DATA_DIR"] = _test_data_dir

from fastapi.testclient import TestClient
from xeen.server import app
from xeen.capture_backends import (
    BrowserCaptureNeeded,
    MssBackend,
    PillowBackend,
    SystemToolBackend,
    detect_backend,
)


@pytest.fixture(autouse=True)
def clean_test_data():
    sessions_dir = Path(_test_data_dir) / "sessions"
    exports_dir = Path(_test_data_dir) / "exports"
    for d in [sessions_dir, exports_dir]:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    yield
    if Path(_test_data_dir).exists():
        shutil.rmtree(_test_data_dir, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


def _make_b64_image(width=200, height=150, color="red"):
    img = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


# ─── E2E: Browser capture → select → center → crop → export ─────────────────

class TestBrowserCaptureE2E:
    """Full pipeline using browser capture API."""

    def test_full_pipeline_browser_capture_to_gif_export(self, client):
        session_name = "e2e_browser_test"

        # 1. Capture 3 frames via browser API
        colors = ["red", "green", "blue"]
        for i, color in enumerate(colors):
            res = client.post(
                "/api/capture/frame",
                json={
                    "session_name": session_name,
                    "frame_index": i,
                    "image_data": _make_b64_image(200, 150, color),
                },
            )
            assert res.status_code == 200
            assert res.json()["ok"] is True

        # 2. Finalize capture session
        res = client.post(
            "/api/capture/finalize",
            json={
                "session_name": session_name,
                "frame_count": 3,
                "duration": 3.0,
            },
        )
        assert res.status_code == 200
        assert res.json()["frame_count"] == 3

        # 3. Verify session appears in list
        res = client.get("/api/sessions")
        assert res.status_code == 200
        names = [s["name"] for s in res.json()]
        assert session_name in names

        # 4. Select frames (pick frame 0 and 2)
        res = client.post(
            f"/api/sessions/{session_name}/select",
            json={"selected_indices": [0, 2]},
        )
        assert res.status_code == 200
        assert res.json()["selected"] == 2

        # 5. Mark centers
        res = client.post(
            f"/api/sessions/{session_name}/centers",
            json={
                "marks": [
                    {"frame_index": 0, "center_x": 100, "center_y": 75},
                    {"frame_index": 2, "center_x": 100, "center_y": 75},
                ]
            },
        )
        assert res.status_code == 200

        # 6. Crop preview
        res = client.post(
            f"/api/sessions/{session_name}/crop-preview",
            json={"custom_w": 100, "custom_h": 100, "frame_indices": [0, 2]},
        )
        assert res.status_code == 200
        previews = res.json()["previews"]
        assert len(previews) == 2

        # 7. Export as GIF
        res = client.post(
            f"/api/sessions/{session_name}/export",
            json={
                "preset": "ig_square",
                "frame_indices": [0, 2],
                "format": "gif",
                "duration_per_frame": 1.0,
            },
        )
        assert res.status_code == 200
        export = res.json()
        assert export["filename"].endswith(".gif")
        assert export["size_mb"] > 0

        # 8. Download export
        res = client.get(export["download_url"])
        assert res.status_code == 200

    def test_full_pipeline_upload_to_zip_export(self, client):
        """E2E using file upload instead of browser capture."""

        # 1. Upload 2 images
        imgs = []
        for color in ["yellow", "cyan"]:
            img = Image.new("RGB", (200, 150), color)
            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            imgs.append(buf.getvalue())

        res = client.post(
            "/api/sessions/upload",
            files=[
                ("files", ("img1.png", imgs[0], "image/png")),
                ("files", ("img2.png", imgs[1], "image/png")),
            ],
        )
        assert res.status_code == 200
        session_name = res.json()["name"]
        assert res.json()["frame_count"] == 2

        # 2. Crop preview
        res = client.post(
            f"/api/sessions/{session_name}/crop-preview",
            json={"custom_w": 100, "custom_h": 100},
        )
        assert res.status_code == 200

        # 3. Export as ZIP
        res = client.post(
            f"/api/sessions/{session_name}/export",
            json={
                "preset": "ig_square",
                "format": "zip",
            },
        )
        assert res.status_code == 200
        assert res.json()["filename"].endswith(".zip")


# ─── E2E: Fallback detection logic ──────────────────────────────────────────

class TestFallbackDetection:
    """Test the fallback chain logic in different environments."""

    @patch.object(MssBackend, "is_available", return_value=True)
    def test_mss_environment_uses_mss(self, _):
        backend = detect_backend(verbose=False)
        assert backend.name == "mss"

    @patch.object(MssBackend, "is_available", return_value=False)
    @patch.object(PillowBackend, "is_available", return_value=False)
    @patch.object(SystemToolBackend, "is_available", return_value=False)
    def test_headless_environment_raises_browser_needed(self, _s, _p, _m):
        with pytest.raises(BrowserCaptureNeeded):
            detect_backend(verbose=False)

    @patch.object(MssBackend, "is_available", return_value=False)
    @patch.object(PillowBackend, "is_available", return_value=False)
    @patch("shutil.which")
    def test_system_tool_fallback_with_scrot(self, mock_which, _p, _m):
        mock_which.side_effect = lambda x: "/usr/bin/scrot" if x == "scrot" else None
        # SystemToolBackend.is_available() uses _find_tool which uses shutil.which
        # We need to let the real is_available run
        with patch.object(SystemToolBackend, "is_available", return_value=True):
            with patch.object(SystemToolBackend, "_find_tool",
                              return_value={"name": "scrot", "cmd": ["scrot", "-o", "{path}"], "check": "scrot"}):
                backend = detect_backend(verbose=False)
                assert backend.name == "system"


# ─── E2E: CaptureSession with mock backend ──────────────────────────────────

class TestCaptureSessionWithMockBackend:
    """Test CaptureSession using a mocked backend."""

    def test_capture_session_saves_frames(self):
        from xeen.capture import CaptureSession
        import numpy as np

        # Create a non-uniform image (gradient) to avoid solid-color rejection
        arr = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        fake_img = Image.fromarray(arr, "RGB")

        # Mock detect_backend to return a fake backend
        fake_backend = MagicMock()
        fake_backend.name = "mock"
        fake_backend.grab.return_value = fake_img

        with patch("xeen.capture.detect_backend", return_value=fake_backend):
            session = CaptureSession(
                duration=0.3,
                interval=0.1,
                min_interval=0.05,
                change_threshold=0.0,
                name="mock_test_session",
            )
            session.run()

        summary = session.summary()
        assert summary["frame_count"] > 0
        assert Path(summary["path"]).exists()

        # Verify session.json exists
        meta_path = Path(summary["path"]) / "session.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["name"] == "mock_test_session"
        assert len(meta["frames"]) > 0

    def test_capture_session_browser_fallback_on_failure(self):
        """When detect_backend raises BrowserCaptureNeeded, it should propagate."""
        from xeen.capture import CaptureSession

        with patch("xeen.capture.detect_backend", side_effect=BrowserCaptureNeeded("no display")):
            session = CaptureSession(duration=1.0, name="fail_test")
            with pytest.raises(BrowserCaptureNeeded):
                session.run()


# ─── E2E: CLI integration ───────────────────────────────────────────────────

class TestCLIIntegration:
    """Test CLI argument parsing and command dispatch."""

    def test_cli_parses_capture_args(self):
        from xeen.cli import main
        import argparse

        # Test that argparse is correctly set up
        with patch("sys.argv", ["xeen", "capture", "-d", "5", "-i", "0.5"]):
            with patch("xeen.cli.run_capture") as mock_capture:
                main()
                args = mock_capture.call_args[0][0]
                assert args.duration == 5.0
                assert args.interval == 0.5
                assert args.command == "capture"

    def test_cli_default_is_capture(self):
        from xeen.cli import main

        with patch("sys.argv", ["xeen"]):
            with patch("xeen.cli.run_capture") as mock_capture:
                main()
                args = mock_capture.call_args[0][0]
                assert args.command == "capture"
                assert args.duration == 10.0

    def test_cli_server_command(self):
        from xeen.cli import main

        with patch("sys.argv", ["xeen", "server", "--no-browser"]):
            with patch("xeen.cli.run_server") as mock_server:
                main()
                args = mock_server.call_args[0][0]
                assert args.command == "server"
                assert args.no_browser is True

    def test_cli_list_command(self):
        from xeen.cli import main

        with patch("sys.argv", ["xeen", "list"]):
            with patch("xeen.cli.run_list") as mock_list:
                main()
                mock_list.assert_called_once()
