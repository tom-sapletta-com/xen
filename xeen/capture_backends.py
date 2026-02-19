"""Capture backends with automatic fallback chain.

Priority order:
1. mss        — fast, cross-platform, requires X11/Wayland display
2. Pillow     — PIL.ImageGrab, works on some Linux (with xdisplay)
3. system     — scrot, gnome-screenshot, grim (Wayland), import (ImageMagick)
4. browser    — signals CLI to start server with Screen Capture API
"""

import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from PIL import Image


class CaptureBackend(ABC):
    """Base class for screenshot capture backends."""

    name: str = "base"

    @abstractmethod
    def grab(self, monitor: int = 0) -> Image.Image:
        """Capture a screenshot and return as PIL Image."""
        ...

    @classmethod
    def is_available(cls) -> bool:
        """Check if this backend can work in current environment."""
        return False

    def __repr__(self):
        return f"<{self.__class__.__name__}>"


class MssBackend(CaptureBackend):
    """Screenshot via mss library (X11/Wayland)."""

    name = "mss"

    def __init__(self):
        import mss
        self._sct = mss.mss()

    def grab(self, monitor: int = 0) -> Image.Image:
        monitors = self._sct.monitors
        mon = monitors[monitor] if monitor < len(monitors) else monitors[0]
        raw = self._sct.grab(mon)
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    @classmethod
    def is_available(cls) -> bool:
        try:
            import mss
            with mss.mss() as sct:
                sct.grab(sct.monitors[0])
            return True
        except Exception:
            return False

    def close(self):
        self._sct.close()


class PillowBackend(CaptureBackend):
    """Screenshot via PIL.ImageGrab."""

    name = "pillow"

    def grab(self, monitor: int = 0) -> Image.Image:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        if img is None:
            raise RuntimeError("ImageGrab.grab() returned None")
        return img

    @classmethod
    def is_available(cls) -> bool:
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            return img is not None
        except Exception:
            return False


class SystemToolBackend(CaptureBackend):
    """Screenshot via system tools: scrot, gnome-screenshot, grim, import."""

    name = "system"

    # Tools ordered by preference
    TOOLS = [
        {
            "name": "scrot",
            "cmd": ["scrot", "-o", "{path}"],
            "check": "scrot",
        },
        {
            "name": "gnome-screenshot",
            "cmd": ["gnome-screenshot", "-f", "{path}"],
            "check": "gnome-screenshot",
        },
        {
            "name": "grim",  # Wayland
            "cmd": ["grim", "{path}"],
            "check": "grim",
        },
        {
            "name": "import",  # ImageMagick
            "cmd": ["import", "-window", "root", "{path}"],
            "check": "import",
        },
        {
            "name": "xdotool+xwd",
            "cmd": ["bash", "-c", "xwd -root -silent | convert xwd:- {path}"],
            "check": "xwd",
        },
    ]

    def __init__(self):
        self._tool = self._find_tool()
        if not self._tool:
            raise RuntimeError("No system screenshot tool found")

    def grab(self, monitor: int = 0) -> Image.Image:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name

        try:
            cmd = [
                part.replace("{path}", path) for part in self._tool["cmd"]
            ]
            result = subprocess.run(
                cmd, capture_output=True, timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"{self._tool['name']} failed: {result.stderr.decode()[:200]}"
                )
            img = Image.open(path).convert("RGB")
            return img.copy()  # Copy so we can delete the temp file
        finally:
            Path(path).unlink(missing_ok=True)

    @classmethod
    def _find_tool(cls) -> Optional[dict]:
        for tool in cls.TOOLS:
            if shutil.which(tool["check"]):
                return tool
        return None

    @classmethod
    def is_available(cls) -> bool:
        return cls._find_tool() is not None


class BrowserCaptureNeeded(Exception):
    """Raised when all local backends fail — signals CLI to start browser capture."""
    pass


def detect_backend(verbose: bool = True) -> CaptureBackend:
    """Try backends in priority order and return first working one.

    Raises BrowserCaptureNeeded if no local backend works.
    """
    backends = [
        ("mss", MssBackend),
        ("pillow", PillowBackend),
        ("system", SystemToolBackend),
    ]

    errors = []
    for name, cls in backends:
        try:
            if verbose:
                print(f"  🔍 Próba backendu: {name}...", end=" ", flush=True)
            if cls.is_available():
                backend = cls()
                if verbose:
                    print(f"✅")
                return backend
            else:
                if verbose:
                    print(f"❌ niedostępny")
                errors.append(f"{name}: niedostępny")
        except Exception as e:
            if verbose:
                print(f"❌ {e}")
            errors.append(f"{name}: {e}")

    if verbose:
        print(f"\n  ⚠️  Żaden lokalny backend nie działa:")
        for err in errors:
            print(f"     - {err}")
        print(f"\n  🌐 Przełączam na przechwytywanie przez przeglądarkę...")

    raise BrowserCaptureNeeded(
        "Brak lokalnego backendu capture. "
        "Wymagane przechwytywanie przez przeglądarkę (Screen Capture API)."
    )


def list_available_backends() -> list[dict]:
    """Return info about all backends and their availability."""
    backends = [
        ("mss", MssBackend, "Fast X11/Wayland capture via mss library"),
        ("pillow", PillowBackend, "PIL.ImageGrab capture"),
        ("system", SystemToolBackend, "System tools: scrot, gnome-screenshot, grim, import"),
        ("browser", None, "Browser Screen Capture API (getDisplayMedia)"),
    ]

    results = []
    for name, cls, desc in backends:
        available = False
        detail = ""
        if cls is not None:
            try:
                available = cls.is_available()
                if name == "system" and available:
                    tool = SystemToolBackend._find_tool()
                    detail = f"tool: {tool['name']}" if tool else ""
            except Exception as e:
                detail = str(e)
        else:
            available = True  # Browser always available as last resort
            detail = "fallback — wymaga przeglądarki"

        results.append({
            "name": name,
            "available": available,
            "description": desc,
            "detail": detail,
        })
    return results
