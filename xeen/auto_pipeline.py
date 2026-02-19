"""xeen auto — zero-click pipeline: capture → deduplicate → center → crop → export.

Usage:
    xeen auto                           # capture 10s → widescreen MP4
    xeen auto --preset twitter_post     # capture → twitter format
    xeen auto -o demo.mp4              # capture → custom output path
    xeen auto --session existing_name   # skip capture, process existing session
"""

import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

from xeen.config import get_data_dir, CROP_PRESETS


def auto_pipeline(
    duration: float = 10.0,
    interval: float = 1.0,
    preset: str = "widescreen",
    output: str | None = None,
    fmt: str = "mp4",
    session_name: str | None = None,
    fps: int = 2,
    duration_per_frame: float = 2.0,
    monitor: int = 0,
    verbose: bool = True,
) -> dict:
    """Run full zero-click pipeline. Returns dict with output path and stats."""

    data = get_data_dir()
    exports_dir = data / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    # ─── Step 1: Capture (or use existing session) ────────────────────────
    if session_name:
        session_dir = data / "sessions" / session_name
        meta_file = session_dir / "session.json"
        if not meta_file.exists():
            raise FileNotFoundError(f"Sesja '{session_name}' nie istnieje")
        meta = json.loads(meta_file.read_text())
        if verbose:
            print(f"  📂 Używam istniejącej sesji: {session_name}")
    else:
        if verbose:
            print(f"  📹 Capture: {duration}s, interwał {interval}s...")
        from xeen.capture import CaptureSession
        from xeen.capture_backends import BrowserCaptureNeeded

        session = CaptureSession(
            duration=duration,
            interval=interval,
            min_interval=0.3,
            change_threshold=3.0,  # lower threshold for auto mode
            monitor=monitor,
        )
        try:
            session.run()
        except BrowserCaptureNeeded:
            print("  ❌ Brak dostępu do ekranu — uruchom xeen server i użyj przeglądarki")
            return {"error": "no_display"}

        summary = session.summary()
        session_name = summary["name"]
        session_dir = Path(summary["path"])
        meta = json.loads((session_dir / "session.json").read_text())

        if verbose:
            print(f"  ✅ {summary['frame_count']} klatek | {summary['duration']:.1f}s")

    frames = meta.get("frames", [])
    if not frames:
        print("  ❌ Brak klatek w sesji")
        return {"error": "no_frames"}

    # ─── Step 2: Deduplicate (remove frames with change_pct < 2%) ─────────
    if verbose:
        print(f"  🔍 Deduplikacja ({len(frames)} klatek)...")

    unique_indices = [0]  # always keep first
    for i in range(1, len(frames)):
        if frames[i].get("change_pct", 100) >= 2.0:
            unique_indices.append(i)

    # Always keep last frame
    if unique_indices[-1] != len(frames) - 1:
        unique_indices.append(len(frames) - 1)

    removed = len(frames) - len(unique_indices)
    if verbose and removed > 0:
        print(f"     Usunięto {removed} duplikatów → {len(unique_indices)} klatek")

    # ─── Step 3: Auto-center (from mouse cursor positions) ────────────────
    if verbose:
        print(f"  🎯 Auto-center z pozycji kursora...")

    custom_centers = {}
    for idx in unique_indices:
        f = frames[idx]
        mx = f.get("mouse_x", 0) or f.get("suggested_center_x", 0)
        my = f.get("mouse_y", 0) or f.get("suggested_center_y", 0)
        # Fallback to image center
        if mx <= 0:
            mx = f.get("width", 1920) // 2
        if my <= 0:
            my = f.get("height", 1080) // 2
        custom_centers[str(idx)] = {"x": mx, "y": my}

    # ─── Step 4: Crop to preset ───────────────────────────────────────────
    if preset not in CROP_PRESETS:
        print(f"  ⚠️  Nieznany preset '{preset}', używam 'widescreen'")
        preset = "widescreen"

    target_w = CROP_PRESETS[preset]["w"]
    target_h = CROP_PRESETS[preset]["h"]
    aspect = target_w / target_h

    if verbose:
        print(f"  ✂️  Crop: {CROP_PRESETS[preset]['label']} ({target_w}×{target_h})")

    crop_dir = session_dir / "auto_crop"
    crop_dir.mkdir(exist_ok=True)

    cropped_files = []
    for idx in unique_indices:
        f = frames[idx]
        filepath = session_dir / "frames" / f["filename"]
        if not filepath.exists():
            continue

        img = Image.open(filepath)
        iw, ih = img.size

        center = custom_centers.get(str(idx), {"x": iw // 2, "y": ih // 2})
        cx, cy = center["x"], center["y"]

        if iw / ih > aspect:
            crop_h = ih
            crop_w = int(ih * aspect)
        else:
            crop_w = iw
            crop_h = int(iw / aspect)

        left = max(0, min(cx - crop_w // 2, iw - crop_w))
        top = max(0, min(cy - crop_h // 2, ih - crop_h))

        cropped = img.crop((left, top, left + crop_w, top + crop_h))
        cropped = cropped.resize((target_w, target_h), Image.LANCZOS)

        # Apply watermark/branding if configured
        try:
            from xeen.branding import load_branding, apply_watermark
            branding = load_branding()
            if branding.get("logo") or branding.get("footer_text"):
                cropped = apply_watermark(cropped, branding)
        except Exception:
            pass

        out_name = f"auto_{idx:04d}.png"
        cropped.save(crop_dir / out_name, "PNG")
        cropped_files.append(crop_dir / out_name)

    if not cropped_files:
        print("  ❌ Brak klatek do eksportu")
        return {"error": "no_cropped_frames"}

    if verbose:
        print(f"     {len(cropped_files)} klatek przygotowanych")

    # ─── Step 5: Export ───────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if output:
        output_path = Path(output).resolve()
        # Detect format from extension
        ext = output_path.suffix.lower()
        if ext == ".gif":
            fmt = "gif"
        elif ext == ".webm":
            fmt = "webm"
        elif ext == ".zip":
            fmt = "zip"
        else:
            fmt = "mp4"
    else:
        ext = {"mp4": ".mp4", "gif": ".gif", "webm": ".webm", "zip": ".zip"}.get(fmt, ".mp4")
        output_path = exports_dir / f"{session_name}_{preset}_{timestamp}{ext}"

    if verbose:
        print(f"  📦 Eksport: {fmt.upper()} → {output_path.name}")

    if fmt == "gif":
        images = [Image.open(f) for f in cropped_files]
        images[0].save(
            output_path, save_all=True, append_images=images[1:],
            duration=int(duration_per_frame * 1000), loop=0, optimize=True,
        )

    elif fmt in ("mp4", "webm"):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
            for cf in cropped_files:
                tf.write(f"file '{cf}'\n")
                tf.write(f"duration {duration_per_frame}\n")
            if cropped_files:
                tf.write(f"file '{cropped_files[-1]}'\n")
            list_file = tf.name

        codec_args = (
            ["-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
            if fmt == "mp4"
            else ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "1M"]
        )

        try:
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-vf", f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                       f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2",
                *codec_args,
                "-r", str(fps),
                str(output_path),
            ]
            subprocess.run(cmd, capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to GIF if ffmpeg unavailable
            if verbose:
                print("     ⚠️  ffmpeg niedostępny — fallback do GIF")
            output_path = output_path.with_suffix(".gif")
            images = [Image.open(f) for f in cropped_files]
            images[0].save(
                output_path, save_all=True, append_images=images[1:],
                duration=int(duration_per_frame * 1000), loop=0,
            )
        finally:
            Path(list_file).unlink(missing_ok=True)

    elif fmt == "zip":
        import zipfile
        with zipfile.ZipFile(output_path, "w") as zf:
            for cf in cropped_files:
                zf.write(cf, cf.name)

    size_mb = round(output_path.stat().st_size / (1024 * 1024), 2)

    if verbose:
        print(f"\n  ✅ Gotowe: {output_path}")
        print(f"     {size_mb} MB | {len(cropped_files)} klatek | {preset}")

    # Cleanup temp crops
    shutil.rmtree(crop_dir, ignore_errors=True)

    return {
        "output": str(output_path),
        "session": session_name,
        "frames": len(cropped_files),
        "preset": preset,
        "size_mb": size_mb,
        "format": fmt,
    }
