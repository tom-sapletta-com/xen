"""Screen capture with metadata collection (mouse, keyboard, change detection)."""

import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict

import numpy as np
from PIL import Image

from xen.config import get_data_dir


@dataclass
class InputEvent:
    """Pojedyncze zdarzenie wejściowe."""
    ts: float  # timestamp (monotonic offset od startu)
    kind: str  # "mouse_move", "mouse_click", "key_press", "key_release"
    x: int = 0
    y: int = 0
    button: str = ""
    key: str = ""


@dataclass
class FrameMeta:
    """Metadane pojedynczej klatki."""
    index: int
    timestamp: float  # offset od startu sesji
    filename: str
    width: int
    height: int
    change_pct: float  # % zmiany vs poprzednia klatka
    mouse_x: int = 0
    mouse_y: int = 0
    suggested_center_x: int = 0  # wstępny środek na podstawie kursora
    suggested_center_y: int = 0
    input_events: list = field(default_factory=list)


class InputTracker:
    """Zbieranie zdarzeń myszy i klawiatury z częstotliwością 100ms."""

    def __init__(self):
        self.events: list[InputEvent] = []
        self.current_mouse_x = 0
        self.current_mouse_y = 0
        self._start_time = 0.0
        self._lock = threading.Lock()
        self._mouse_listener = None
        self._key_listener = None
        self._running = False
        self._last_move_ts = 0.0

    def start(self):
        self._start_time = time.monotonic()
        self._running = True

        try:
            from pynput import mouse, keyboard

            def on_move(x, y):
                if not self._running:
                    return False
                now = time.monotonic()
                # Ograniczenie do co 100ms
                if now - self._last_move_ts < 0.1:
                    self.current_mouse_x = int(x)
                    self.current_mouse_y = int(y)
                    return
                self._last_move_ts = now
                self.current_mouse_x = int(x)
                self.current_mouse_y = int(y)
                with self._lock:
                    self.events.append(InputEvent(
                        ts=round(now - self._start_time, 3),
                        kind="mouse_move",
                        x=int(x), y=int(y),
                    ))

            def on_click(x, y, button, pressed):
                if not self._running:
                    return False
                if pressed:
                    with self._lock:
                        self.events.append(InputEvent(
                            ts=round(time.monotonic() - self._start_time, 3),
                            kind="mouse_click",
                            x=int(x), y=int(y),
                            button=str(button),
                        ))

            def on_press(key):
                if not self._running:
                    return False
                key_str = ""
                try:
                    key_str = key.char or ""
                except AttributeError:
                    key_str = str(key)
                with self._lock:
                    self.events.append(InputEvent(
                        ts=round(time.monotonic() - self._start_time, 3),
                        kind="key_press",
                        x=self.current_mouse_x,
                        y=self.current_mouse_y,
                        key=key_str,
                    ))

            def on_release(key):
                if not self._running:
                    return False
                key_str = ""
                try:
                    key_str = key.char or ""
                except AttributeError:
                    key_str = str(key)
                with self._lock:
                    self.events.append(InputEvent(
                        ts=round(time.monotonic() - self._start_time, 3),
                        kind="key_release",
                        x=self.current_mouse_x,
                        y=self.current_mouse_y,
                        key=key_str,
                    ))

            self._mouse_listener = mouse.Listener(on_move=on_move, on_click=on_click)
            self._key_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._mouse_listener.start()
            self._key_listener.start()

        except Exception as e:
            print(f"  ⚠️  Input tracking niedostępny: {e}")
            print(f"     (na serwerze/Docker bez display — to normalne)")

    def stop(self):
        self._running = False
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._key_listener:
            self._key_listener.stop()

    def get_events_since(self, since_ts: float) -> list[dict]:
        """Pobierz zdarzenia od danego timestampa."""
        with self._lock:
            return [
                asdict(e) for e in self.events
                if e.ts >= since_ts
            ]

    def get_mouse_position(self) -> tuple[int, int]:
        return self.current_mouse_x, self.current_mouse_y


def compute_change_pct(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """Oblicz % zmiany między dwoma obrazami (downsampled dla szybkości)."""
    if img_a is None or img_b is None:
        return 100.0
    # Downsample do ~100x100 dla szybkości
    h, w = img_a.shape[:2]
    step_h = max(1, h // 100)
    step_w = max(1, w // 100)
    a = img_a[::step_h, ::step_w].astype(np.float32)
    b = img_b[::step_h, ::step_w].astype(np.float32)
    if a.shape != b.shape:
        return 100.0
    diff = np.abs(a - b)
    # Piksel się "zmienił" jeśli średnia zmiana kanałów > 30
    changed = np.mean(diff, axis=-1) > 30
    return float(np.mean(changed) * 100)


class CaptureSession:
    """Sesja nagrywania ekranu ze zbieraniem metadanych."""

    def __init__(
        self,
        duration: float = 10.0,
        interval: float = 1.0,
        min_interval: float = 0.5,
        change_threshold: float = 5.0,
        name: str | None = None,
        monitor: int = 0,
    ):
        self.duration = min(duration, 30.0)  # Hard limit 30s
        self.interval = interval
        self.min_interval = max(min_interval, 0.1)
        self.change_threshold = change_threshold
        self.monitor = monitor

        self.name = name or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = get_data_dir() / "sessions" / self.name
        self.session_dir.mkdir(parents=True, exist_ok=True)
        (self.session_dir / "frames").mkdir(exist_ok=True)

        self.frames: list[FrameMeta] = []
        self.tracker = InputTracker()
        self._running = False
        self._prev_array: np.ndarray | None = None
        self._start_time = 0.0

    def run(self):
        """Uruchom sesję nagrywania."""
        import mss

        self._running = True
        self._start_time = time.monotonic()
        self.tracker.start()

        last_capture_ts = 0.0
        last_event_ts = 0.0

        with mss.mss() as sct:
            monitors = sct.monitors
            mon = monitors[self.monitor] if self.monitor < len(monitors) else monitors[0]

            while self._running:
                now = time.monotonic()
                elapsed = now - self._start_time

                if elapsed >= self.duration:
                    break

                time_since_last = now - last_capture_ts

                # Minimalna przerwa
                if time_since_last < self.min_interval:
                    time.sleep(0.05)
                    continue

                # Zrób screenshot
                raw = sct.grab(mon)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                arr = np.array(img)

                change = compute_change_pct(self._prev_array, arr)

                # Decyzja: zapisać klatkę?
                should_save = False
                if len(self.frames) == 0:
                    should_save = True  # Zawsze pierwsza klatka
                elif change >= self.change_threshold:
                    should_save = True  # Zmiana na ekranie
                elif time_since_last >= self.interval:
                    should_save = True  # Minął interwał

                if should_save and len(self.frames) < 15:  # Max 15 klatek
                    frame_idx = len(self.frames)
                    filename = f"frame_{frame_idx:04d}.png"
                    filepath = self.session_dir / "frames" / filename
                    img.save(filepath, "PNG", optimize=True)

                    mx, my = self.tracker.get_mouse_position()

                    # Zbierz events od ostatniego zapisu
                    events = self.tracker.get_events_since(last_event_ts)
                    last_event_ts = elapsed

                    frame = FrameMeta(
                        index=frame_idx,
                        timestamp=round(elapsed, 3),
                        filename=filename,
                        width=img.width,
                        height=img.height,
                        change_pct=round(change, 2),
                        mouse_x=mx,
                        mouse_y=my,
                        suggested_center_x=mx if mx > 0 else img.width // 2,
                        suggested_center_y=my if my > 0 else img.height // 2,
                        input_events=events,
                    )
                    self.frames.append(frame)
                    self._prev_array = arr
                    last_capture_ts = now

                    indicator = "🔴" if change > 20 else "🟡" if change > 5 else "🟢"
                    print(f"  {indicator} Klatka {frame_idx+1:>2} | {elapsed:5.1f}s | zmiana: {change:5.1f}% | mysz: ({mx},{my})")

                time.sleep(0.05)

        self.stop()

    def stop(self):
        """Zakończ sesję i zapisz metadane."""
        self._running = False
        self.tracker.stop()
        self._save_session_meta()

    def _save_session_meta(self):
        """Zapisz metadane sesji do pliku JSON."""
        meta = {
            "name": self.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "duration": round(time.monotonic() - self._start_time, 3) if self._start_time else 0,
            "frame_count": len(self.frames),
            "settings": {
                "max_duration": self.duration,
                "interval": self.interval,
                "min_interval": self.min_interval,
                "change_threshold": self.change_threshold,
                "monitor": self.monitor,
            },
            "frames": [asdict(f) for f in self.frames],
            "input_log": [asdict(e) for e in self.tracker.events],
        }

        meta_path = self.session_dir / "session.json"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    def summary(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.session_dir),
            "frame_count": len(self.frames),
            "duration": round(time.monotonic() - self._start_time, 3) if self._start_time else 0,
        }
