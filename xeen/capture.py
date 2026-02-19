"""Screen capture with metadata collection (mouse, keyboard, change detection).

Uses automatic backend fallback chain:
mss → Pillow → system tools → browser Screen Capture API
"""

import json
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict

import numpy as np
from PIL import Image

from xeen.config import get_data_dir
from xeen.capture_backends import detect_backend, BrowserCaptureNeeded, CaptureBackend


def _ensure_package(pip_name: str, import_name: str | None = None) -> bool:
    """Try to import a package; auto-install via pip if missing. Returns True on success."""
    import_name = import_name or pip_name
    try:
        __import__(import_name)
        return True
    except ImportError:
        print(f"  📦  Brak '{pip_name}' — instaluję automatycznie...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", pip_name],
                stdout=subprocess.DEVNULL,
            )
            __import__(import_name)
            print(f"  ✅  '{pip_name}' zainstalowany pomyślnie")
            return True
        except Exception as e:
            print(f"  ❌  Nie udało się zainstalować '{pip_name}': {e}")
            return False


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
    ocr_text: str = ""           # tekst wyekstrahowany przez OCR
    ocr_words: int = 0           # liczba słów
    ocr_available: bool = False  # czy tesseract był dostępny


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


def analyze_frame(arr: np.ndarray) -> dict:
    """Analyze image quality. Returns dict with flags and stats."""
    # Work on grayscale for most checks
    if arr.ndim == 3:
        gray = arr.mean(axis=2).astype(np.float32)  # shape (H, W)
    else:
        gray = arr.astype(np.float32)

    mean_brightness = float(gray.mean())
    std_brightness  = float(gray.std())

    # Per-channel stats (for color uniformity)
    if arr.ndim == 3:
        ch_means = arr.mean(axis=(0, 1))   # [R, G, B]
        ch_stds  = arr.std(axis=(0, 1))    # std per channel
    else:
        ch_means = np.array([mean_brightness])
        ch_stds  = np.array([std_brightness])

    # Thresholds
    BLACK_THRESH      = 15    # mean brightness below → black frame
    WHITE_THRESH      = 240   # mean brightness above → white frame
    UNIFORM_STD       = 8     # global std below → uniform/solid color
    CHANNEL_STD       = 10    # ALL per-channel stds below → solid color (any hue)
    LOW_CONTRAST_STD  = 20    # std below → very low contrast

    is_black   = mean_brightness < BLACK_THRESH
    is_white   = mean_brightness > WHITE_THRESH
    # Uniform: either global std is tiny, OR every channel is individually flat
    # (catches solid red/green/blue/any-hue that might have moderate global std)
    is_uniform = (std_brightness < UNIFORM_STD) or bool(np.all(ch_stds < CHANNEL_STD))
    is_low_contrast = std_brightness < LOW_CONTRAST_STD

    # Rough blur estimate: variance of Laplacian (downsampled)
    step = max(1, gray.shape[0] // 200)
    g = gray[::step, ::step]
    lap = (np.roll(g, 1, 0) + np.roll(g, -1, 0) +
           np.roll(g, 1, 1) + np.roll(g, -1, 1) - 4 * g)
    blur_score = float(lap.var())   # higher = sharper

    # Histogram: % of pixels that are near-black or near-white
    flat = gray.flatten()
    pct_black_pixels = float((flat < 20).mean() * 100)
    pct_white_pixels = float((flat > 235).mean() * 100)

    # Dominant-color reason string for logging
    if is_black:
        reason = "czarna"
    elif is_white:
        reason = "biała"
    elif is_uniform:
        reason = f"jednolity kolor (ch_stds={[round(float(v),1) for v in ch_stds]})"
    else:
        reason = ""

    return {
        "mean":             round(mean_brightness, 1),
        "std":              round(std_brightness, 1),
        "blur_score":       round(blur_score, 1),
        "pct_black_pixels": round(pct_black_pixels, 1),
        "pct_white_pixels": round(pct_white_pixels, 1),
        "ch_means":         [round(float(v), 1) for v in ch_means],
        "ch_stds":          [round(float(v), 1) for v in ch_stds],
        "is_black":         is_black,
        "is_white":         is_white,
        "is_uniform":       is_uniform,
        "is_low_contrast":  is_low_contrast,
        "bad":              is_black or is_white or is_uniform,
        "reason":           reason,
    }


# ─── OCR ──────────────────────────────────────────────────────────────────────
_OCR_AVAILABLE: bool | None = None  # None = not yet checked


def run_ocr(img: Image.Image) -> tuple[str, int, bool]:
    """Run tesseract OCR on image. Returns (text, word_count, ocr_available)."""
    global _OCR_AVAILABLE

    if _OCR_AVAILABLE is False:
        return "", 0, False

    try:
        import pytesseract
        # First call: verify tesseract binary is present
        if _OCR_AVAILABLE is None:
            pytesseract.get_tesseract_version()
            _OCR_AVAILABLE = True

        # Upscale small images for better OCR accuracy
        w, h = img.size
        if w < 1280:
            scale = 1280 / w
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        # PSM 3 = fully automatic page segmentation
        config = "--psm 3 --oem 1"
        text = pytesseract.image_to_string(img, lang="pol+eng", config=config)
        text = text.strip()
        words = len(text.split()) if text else 0
        return text, words, True

    except ImportError:
        if _OCR_AVAILABLE is None:
            if _ensure_package("pytesseract"):
                # Retry after auto-install
                return run_ocr(img)
            else:
                print("  ℹ️  OCR wyłączony: nie można zainstalować pytesseract")
        _OCR_AVAILABLE = False
        return "", 0, False
    except Exception as e:
        if _OCR_AVAILABLE is None:
            print(f"  ℹ️  OCR niedostępny: {e}")
            print(f"     Zainstaluj tesseract: sudo apt install tesseract-ocr tesseract-ocr-pol")
        _OCR_AVAILABLE = False
        return "", 0, False


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
        """Uruchom sesję nagrywania z automatycznym fallback backendów."""
        print("  🔄 Wykrywanie backendu capture...")
        backend = detect_backend(verbose=True)  # raises BrowserCaptureNeeded
        print(f"  ✅ Backend: {backend.name}\n")

        self._running = True
        self._start_time = time.monotonic()
        self.tracker.start()

        last_capture_ts = 0.0
        last_event_ts = 0.0
        skipped_black = 0
        skipped_white = 0
        skipped_uniform = 0

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

            # Zrób screenshot przez wykryty backend
            try:
                img = backend.grab(self.monitor)
                arr = np.array(img)
            except Exception as e:
                print(f"\n  ⚠️  Błąd capture: {e}")
                # Próbuj ponownie wykryć backend (może się coś zmieniło)
                try:
                    backend = detect_backend(verbose=False)
                    continue
                except BrowserCaptureNeeded:
                    raise

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

                # ── Image quality analysis ──────────────────────────────────
                qa = analyze_frame(arr)
                qa_tag = ""
                if qa["bad"]:
                    qa_tag = f"  ❌ Klatka odrzucona [{qa['reason']}] — pomijam"

                if qa_tag:
                    print(qa_tag)
                    if qa["is_black"]:
                        skipped_black += 1
                    elif qa["is_white"]:
                        skipped_white += 1
                    else:
                        skipped_uniform += 1
                    print(f"     Szczegóły: mean={qa['mean']} std={qa['std']} ch_stds={qa['ch_stds']}")
                    # Still advance time so we don't spin on bad frames
                    last_capture_ts = now
                    continue

                # ── Save frame ──────────────────────────────────────────────
                try:
                    img.save(filepath, "PNG", optimize=True)
                    file_size = filepath.stat().st_size
                    if file_size == 0:
                        print(f"  ❌ BŁĄD: Plik {filename} zapisany ale ma 0 bajtów! ({filepath})")
                        continue
                except Exception as save_err:
                    print(f"  ❌ BŁĄD ZAPISU klatki {frame_idx+1}: {save_err}")
                    print(f"     Ścieżka: {filepath}")
                    print(f"     Katalog istnieje: {filepath.parent.exists()}")
                    print(f"     Rozmiar obrazu: {img.width}x{img.height}")
                    continue

                mx, my = self.tracker.get_mouse_position()

                # Zbierz events od ostatniego zapisu
                events = self.tracker.get_events_since(last_event_ts)
                last_event_ts = elapsed

                # ── OCR ──────────────────────────────────────────────────
                ocr_text, ocr_words, ocr_ok = run_ocr(img)

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
                    ocr_text=ocr_text,
                    ocr_words=ocr_words,
                    ocr_available=ocr_ok,
                )
                self.frames.append(frame)
                self._prev_array = arr
                last_capture_ts = now

                # ── Quality summary for log line ────────────────────────────
                contrast_warn = " ⚠️ nisk.kontrast" if qa["is_low_contrast"] else ""
                blur_warn     = " 🔵 rozmyta" if qa["blur_score"] < 50 else ""
                ocr_info      = f" | OCR: {ocr_words}sw" if ocr_ok else ""
                indicator = "🔴" if change > 20 else "🟡" if change > 5 else "🟢"
                print(
                    f"  {indicator} Klatka {frame_idx+1:>2} | {elapsed:5.1f}s"
                    f" | zmiana: {change:5.1f}%"
                    f" | mysz: ({mx},{my})"
                    f" | {file_size//1024}KB"
                    f" | jasność: {qa['mean']:.0f} std: {qa['std']:.0f}"
                    f" | blur: {qa['blur_score']:.0f}"
                    f"{ocr_info}{contrast_warn}{blur_warn}"
                )
                if ocr_ok and ocr_text:
                    preview = ocr_text[:120].replace('\n', ' ')
                    print(f"     📝 OCR: \"{preview}{'...' if len(ocr_text) > 120 else ''}\"")

            time.sleep(0.05)

        # ── Session quality summary ──────────────────────────────────────
        skipped_total = skipped_black + skipped_white + skipped_uniform
        if skipped_total > 0:
            parts = []
            if skipped_black:   parts.append(f"{skipped_black} czarnych")
            if skipped_white:   parts.append(f"{skipped_white} białych")
            if skipped_uniform: parts.append(f"{skipped_uniform} jednolitych")
            print(f"  ⚠️  Pominięto {skipped_total} klatek złej jakości: {', '.join(parts)}")
        else:
            print(f"  ✅ Wszystkie klatki przeszły kontrolę jakości")

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
