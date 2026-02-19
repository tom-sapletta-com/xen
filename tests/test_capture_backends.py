"""Tests for capture_backends.py — fallback chain logic."""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xeen.capture_backends import (
    CaptureBackend,
    MssBackend,
    PillowBackend,
    SystemToolBackend,
    BrowserCaptureNeeded,
    detect_backend,
    list_available_backends,
)


# ─── CaptureBackend base class ──────────────────────────────────────────────

class TestCaptureBackendBase:
    def test_abstract_grab_raises(self):
        with pytest.raises(TypeError):
            CaptureBackend()

    def test_is_available_default_false(self):
        assert CaptureBackend.is_available() is False


# ─── MssBackend ──────────────────────────────────────────────────────────────

class TestMssBackend:
    def test_is_available_returns_bool(self):
        result = MssBackend.is_available()
        assert isinstance(result, bool)

    @patch("mss.mss")
    def test_grab_returns_pil_image(self, mock_mss_cls):
        """Test that grab returns a PIL Image when mss works."""
        # Create a fake mss screenshot
        fake_raw = MagicMock()
        fake_raw.size = (100, 100)
        fake_raw.bgra = b"\x00\x00\xff\xff" * (100 * 100)  # red pixels in BGRX

        fake_sct = MagicMock()
        fake_sct.monitors = [{"top": 0, "left": 0, "width": 100, "height": 100}]
        fake_sct.grab.return_value = fake_raw

        mock_mss_cls.return_value = fake_sct

        backend = MssBackend.__new__(MssBackend)
        backend._sct = fake_sct

        img = backend.grab(monitor=0)
        assert isinstance(img, Image.Image)

    def test_name(self):
        assert MssBackend.name == "mss"


# ─── PillowBackend ──────────────────────────────────────────────────────────

class TestPillowBackend:
    def test_is_available_returns_bool(self):
        result = PillowBackend.is_available()
        assert isinstance(result, bool)

    def test_name(self):
        assert PillowBackend.name == "pillow"

    @patch("xeen.capture_backends.ImageGrab", create=True)
    def test_grab_with_mock(self, mock_grab_module):
        """Test grab when ImageGrab works."""
        fake_img = Image.new("RGB", (100, 100), "red")
        # We need to patch at the import location inside the method
        with patch("PIL.ImageGrab.grab", return_value=fake_img):
            backend = PillowBackend()
            img = backend.grab()
            assert isinstance(img, Image.Image)


# ─── SystemToolBackend ───────────────────────────────────────────────────────

class TestSystemToolBackend:
    def test_is_available_returns_bool(self):
        result = SystemToolBackend.is_available()
        assert isinstance(result, bool)

    def test_name(self):
        assert SystemToolBackend.name == "system"

    def test_find_tool_returns_dict_or_none(self):
        result = SystemToolBackend._find_tool()
        assert result is None or isinstance(result, dict)

    @patch("shutil.which")
    def test_find_tool_with_scrot(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/scrot" if x == "scrot" else None
        tool = SystemToolBackend._find_tool()
        assert tool is not None
        assert tool["name"] == "scrot"

    @patch("shutil.which")
    def test_find_tool_with_grim(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/grim" if x == "grim" else None
        tool = SystemToolBackend._find_tool()
        assert tool is not None
        assert tool["name"] == "grim"

    @patch("shutil.which")
    def test_find_tool_none_available(self, mock_which):
        mock_which.return_value = None
        tool = SystemToolBackend._find_tool()
        assert tool is None

    @patch("shutil.which")
    def test_is_available_when_no_tools(self, mock_which):
        mock_which.return_value = None
        assert SystemToolBackend.is_available() is False


# ─── BrowserCaptureNeeded ────────────────────────────────────────────────────

class TestBrowserCaptureNeeded:
    def test_is_exception(self):
        assert issubclass(BrowserCaptureNeeded, Exception)

    def test_message(self):
        exc = BrowserCaptureNeeded("test message")
        assert "test message" in str(exc)


# ─── detect_backend ─────────────────────────────────────────────────────────

class TestDetectBackend:
    @patch.object(MssBackend, "is_available", return_value=True)
    def test_returns_mss_when_available(self, _mock):
        backend = detect_backend(verbose=False)
        assert backend.name == "mss"

    @patch.object(MssBackend, "is_available", return_value=False)
    @patch.object(PillowBackend, "is_available", return_value=True)
    def test_falls_back_to_pillow(self, _p, _m):
        backend = detect_backend(verbose=False)
        assert backend.name == "pillow"

    @patch.object(MssBackend, "is_available", return_value=False)
    @patch.object(PillowBackend, "is_available", return_value=False)
    @patch.object(SystemToolBackend, "is_available", return_value=True)
    @patch.object(SystemToolBackend, "_find_tool", return_value={"name": "scrot", "cmd": ["scrot", "-o", "{path}"], "check": "scrot"})
    def test_falls_back_to_system(self, _ft, _s, _p, _m):
        backend = detect_backend(verbose=False)
        assert backend.name == "system"

    @patch.object(MssBackend, "is_available", return_value=False)
    @patch.object(PillowBackend, "is_available", return_value=False)
    @patch.object(SystemToolBackend, "is_available", return_value=False)
    def test_raises_browser_capture_needed(self, _s, _p, _m):
        with pytest.raises(BrowserCaptureNeeded):
            detect_backend(verbose=False)


# ─── list_available_backends ─────────────────────────────────────────────────

class TestListAvailableBackends:
    def test_returns_list(self):
        result = list_available_backends()
        assert isinstance(result, list)
        assert len(result) >= 4  # mss, pillow, system, browser

    def test_each_entry_has_required_keys(self):
        for entry in list_available_backends():
            assert "name" in entry
            assert "available" in entry
            assert "description" in entry
            assert isinstance(entry["available"], bool)

    def test_browser_always_available(self):
        result = list_available_backends()
        browser = [b for b in result if b["name"] == "browser"]
        assert len(browser) == 1
        assert browser[0]["available"] is True

    def test_names_in_order(self):
        result = list_available_backends()
        names = [b["name"] for b in result]
        assert names == ["mss", "pillow", "system", "browser"]
