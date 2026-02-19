"""FastAPI server for xeen web editor."""

import json
import io
import logging
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from PIL import Image

logger = logging.getLogger("xeen.server")

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from xeen.config import get_data_dir, CROP_PRESETS, SOCIAL_LINKS

app = FastAPI(title="xeen", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


def data_dir() -> Path:
    return get_data_dir()


# ─── API: Sessions ───────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions():
    """Lista wszystkich sesji nagrywania."""
    sessions_dir = data_dir() / "sessions"
    if not sessions_dir.exists():
        return []
    results = []
    for s in sorted(sessions_dir.iterdir(), reverse=True):
        meta_file = s / "session.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
            results.append({
                "name": meta.get("name", s.name),
                "created_at": meta.get("created_at", ""),
                "frame_count": meta.get("frame_count", 0),
                "duration": meta.get("duration", 0),
            })
    return results


@app.get("/api/sessions/{name}")
async def get_session(name: str):
    """Pobierz szczegóły sesji."""
    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404, "Session not found")
    meta = json.loads(meta_file.read_text())
    frames_dir = data_dir() / "sessions" / name / "frames"
    missing = []
    for f in meta.get("frames", []):
        fp = frames_dir / f["filename"]
        if not fp.exists():
            missing.append(f["filename"])
    if missing:
        logger.warning("Session %s: %d/%d frames missing on disk: %s",
                       name, len(missing), len(meta.get("frames", [])), missing)
        meta["_missing_frames"] = missing
    return meta


@app.get("/api/sessions/{name}/thumbnails")
async def get_session_thumbnails(name: str, limit: int = 9):
    """Pobierz pierwsze N klatek sesji jako thumbnails."""
    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404, "Session not found")
    meta = json.loads(meta_file.read_text())
    frames = meta.get("frames", [])[:limit]
    thumbs = []
    for f in frames:
        thumb_name = f["filename"].replace(".png", "_thumb.webp")
        thumbs.append({
            "index": f["index"],
            "filename": f["filename"],
            "thumb_url": f"/api/sessions/{name}/thumbs/{thumb_name}",
            "url": f"/api/sessions/{name}/frames/{f['filename']}",
        })
    return {"name": name, "thumbnails": thumbs}


@app.get("/api/sessions/{name}/thumbs/{filename}")
async def get_thumb_image(name: str, filename: str):
    """Serve cached thumbnail (WebP). Falls back to generating on-the-fly."""
    thumb_path = data_dir() / "sessions" / name / "thumbs" / filename
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/webp")

    # Fallback: generate from original frame
    base = filename.replace("_thumb.webp", ".png")
    frame_path = data_dir() / "sessions" / name / "frames" / base
    if not frame_path.exists():
        raise HTTPException(404, "Thumb not found")

    from PIL import Image as PILImage
    img = PILImage.open(frame_path)
    tw = 320
    th = int(img.height * (tw / img.width))
    thumb = img.resize((tw, th), PILImage.LANCZOS)

    thumb_dir = data_dir() / "sessions" / name / "thumbs"
    thumb_dir.mkdir(exist_ok=True)
    thumb.save(thumb_path, "WEBP", quality=75)
    return FileResponse(thumb_path, media_type="image/webp")


@app.get("/api/sessions/{name}/frames/{filename}")
async def get_frame_image(name: str, filename: str):
    """Zwróć obraz klatki."""
    filepath = data_dir() / "sessions" / name / "frames" / filename
    if not filepath.exists():
        raise HTTPException(404, "Frame not found")
    return FileResponse(filepath, media_type="image/png")


@app.delete("/api/sessions/{name}")
async def delete_session(name: str):
    """Usuń sesję."""
    session_dir = data_dir() / "sessions" / name
    if session_dir.exists():
        shutil.rmtree(session_dir)
    return {"ok": True}


@app.delete("/api/sessions/{name}/frames/{filename}")
async def delete_frame(name: str, filename: str):
    """Usuń pojedynczą klatkę z sesji i zaktualizuj session.json."""
    session_dir = data_dir() / "sessions" / name
    filepath = session_dir / "frames" / filename
    if not filepath.exists():
        raise HTTPException(404, "Frame not found")

    filepath.unlink()

    meta_file = session_dir / "session.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        meta["frames"] = [f for f in meta.get("frames", []) if f["filename"] != filename]
        meta["frame_count"] = len(meta["frames"])
        for i, f in enumerate(meta["frames"]):
            f["index"] = i
        if "selected_frames" in meta:
            meta["selected_frames"] = [
                i for i in range(len(meta["frames"]))
            ]
        meta_file.write_text(json.dumps(meta, indent=2))

    return {"ok": True}


# ─── API: Frame Similarity ────────────────────────────────────────────────────

@app.get("/api/sessions/{name}/similarity")
async def get_frame_similarity(name: str, threshold: float = 90.0):
    """Compute pairwise similarity between frames using perceptual hashing."""
    import imagehash
    from PIL import Image

    session_dir = data_dir() / "sessions" / name
    meta_file = session_dir / "session.json"
    if not meta_file.exists():
        raise HTTPException(404, "Session not found")

    meta = json.loads(meta_file.read_text())
    frames = meta.get("frames", [])
    frames_dir = session_dir / "frames"

    # Compute perceptual hashes
    hashes = []
    for f in frames:
        fp = frames_dir / f["filename"]
        if fp.exists():
            try:
                img = Image.open(fp)
                h = imagehash.phash(img, hash_size=16)
                hashes.append({"index": f["index"], "filename": f["filename"], "hash": str(h), "hash_obj": h})
            except Exception as e:
                logger.warning("Failed to hash frame %s: %s", f["filename"], e)
                hashes.append({"index": f["index"], "filename": f["filename"], "hash": None, "hash_obj": None})
        else:
            hashes.append({"index": f["index"], "filename": f["filename"], "hash": None, "hash_obj": None})

    # Pairwise comparison
    max_hash_bits = 16 * 16  # hash_size=16 → 256 bits
    duplicates = []   # list of (i, j, similarity%)
    dup_indices = set()

    for a_idx in range(len(hashes)):
        for b_idx in range(a_idx + 1, len(hashes)):
            ha = hashes[a_idx]["hash_obj"]
            hb = hashes[b_idx]["hash_obj"]
            if ha is None or hb is None:
                continue
            distance = ha - hb  # Hamming distance
            similarity = round((1 - distance / max_hash_bits) * 100, 1)
            if similarity >= threshold:
                duplicates.append({
                    "frame_a": hashes[a_idx]["index"],
                    "frame_b": hashes[b_idx]["index"],
                    "similarity": similarity,
                })
                dup_indices.add(hashes[b_idx]["index"])  # mark the later one

    return {
        "threshold": threshold,
        "total_frames": len(frames),
        "duplicate_pairs": duplicates,
        "duplicate_indices": sorted(dup_indices),
        "duplicate_count": len(dup_indices),
    }


# ─── API: Upload external screenshots ────────────────────────────────────────

@app.post("/api/sessions/upload")
async def upload_screenshots(files: list[UploadFile] = File(...)):
    """Upload zewnętrznych screenshotów jako nowa sesja."""

    name = datetime.now().strftime("upload_%Y%m%d_%H%M%S")
    session_dir = data_dir() / "sessions" / name
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "frames").mkdir(exist_ok=True)

    frames = []
    for i, f in enumerate(sorted(files, key=lambda x: x.filename)):
        content = await f.read()
        img = Image.open(io.BytesIO(content))
        filename = f"frame_{i:04d}.png"
        img.save(session_dir / "frames" / filename, "PNG")
        frames.append({
            "index": i,
            "timestamp": i * 1.0,
            "filename": filename,
            "width": img.width,
            "height": img.height,
            "change_pct": 100.0 if i == 0 else 0.0,
            "mouse_x": img.width // 2,
            "mouse_y": img.height // 2,
            "suggested_center_x": img.width // 2,
            "suggested_center_y": img.height // 2,
            "input_events": [],
        })

    meta = {
        "name": name,
        "created_at": datetime.utcnow().isoformat(),
        "duration": len(frames),
        "frame_count": len(frames),
        "settings": {"source": "upload"},
        "frames": frames,
        "input_log": [],
    }
    (session_dir / "session.json").write_text(json.dumps(meta, indent=2))
    return {"name": name, "frame_count": len(frames)}


# ─── API: Tab 1 - Frame Selection ────────────────────────────────────────────

class FrameSelection(BaseModel):
    selected_indices: list[int]


@app.post("/api/sessions/{name}/select")
async def save_frame_selection(name: str, selection: FrameSelection):
    """Zapisz wybór klatek."""
    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404)
    meta = json.loads(meta_file.read_text())
    meta["selected_frames"] = selection.selected_indices
    meta_file.write_text(json.dumps(meta, indent=2))
    return {"ok": True, "selected": len(selection.selected_indices)}


# ─── API: Tab 2 - Center Marking ─────────────────────────────────────────────

class CenterMark(BaseModel):
    frame_index: int
    center_x: int
    center_y: int


class CenterMarks(BaseModel):
    marks: list[CenterMark]


@app.post("/api/sessions/{name}/centers")
async def save_centers(name: str, marks: CenterMarks):
    """Zapisz oznaczenia środków."""
    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404)
    meta = json.loads(meta_file.read_text())
    centers = {}
    for m in marks.marks:
        centers[str(m.frame_index)] = {"x": m.center_x, "y": m.center_y}
    meta["custom_centers"] = centers
    meta_file.write_text(json.dumps(meta, indent=2))
    return {"ok": True}


# ─── API: Tab 3 - Crop & Generate ────────────────────────────────────────────

@app.get("/api/presets")
async def get_crop_presets():
    """Lista presetów przycinania."""
    return CROP_PRESETS


class CropRequest(BaseModel):
    preset: str | None = None
    custom_w: int | None = None
    custom_h: int | None = None
    frame_indices: list[int] | None = None  # None = wszystkie zaznaczone
    focus_mode: str = "screen"  # "screen" | "mouse" | "keyboard" | "application"
    zoom_level: float = 1.0  # 1.0 - 10.0
    mouse_padding: int = 100  # piksele wokół myszy


@app.post("/api/sessions/{name}/crop-preview")
async def crop_preview(name: str, req: CropRequest):
    """Generuj podgląd przyciętych klatek."""

    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404)
    meta = json.loads(meta_file.read_text())

    # Rozmiar docelowy
    if req.preset and req.preset in CROP_PRESETS:
        target_w = CROP_PRESETS[req.preset]["w"]
        target_h = CROP_PRESETS[req.preset]["h"]
    elif req.custom_w and req.custom_h:
        target_w = req.custom_w
        target_h = req.custom_h
    else:
        target_w, target_h = 1920, 1080

    # Które klatki
    selected = req.frame_indices or meta.get("selected_frames", list(range(meta["frame_count"])))
    custom_centers = meta.get("custom_centers", {})
    frames = meta.get("frames", [])

    preview_dir = data_dir() / "sessions" / name / "preview"
    preview_dir.mkdir(exist_ok=True)

    results = []
    for idx in selected:
        if idx >= len(frames):
            continue
        frame = frames[idx]
        filepath = data_dir() / "sessions" / name / "frames" / frame["filename"]
        if not filepath.exists():
            continue

        img = Image.open(filepath)
        iw, ih = img.size

        # Wybierz środek w zależności od focus_mode
        if req.focus_mode == "mouse":
            # Użyj pozycji myszy z nagrania
            cx = frame.get("mouse_x", iw // 2)
            cy = frame.get("mouse_y", ih // 2)
        elif req.focus_mode == "keyboard":
            # Dla klawiatury użyj środka dolnej części ekranu (typowa pozycja klawiatury)
            cx = frame.get("suggested_center_x", iw // 2)
            cy = int(ih * 0.75)  # 75% wysokości
        elif req.focus_mode == "application":
            # Dla aplikacji użyj środka górnej części (typowa pozycja okien)
            cx = frame.get("suggested_center_x", iw // 2)
            cy = int(ih * 0.25)  # 25% wysokości
        else:  # screen
            # Użyj custom lub suggested
            center = custom_centers.get(str(idx))
            if center:
                cx, cy = center["x"], center["y"]
            else:
                cx = frame.get("suggested_center_x", iw // 2)
                cy = frame.get("suggested_center_y", ih // 2)

        # Oblicz region przycinania z zoomem
        if req.focus_mode == "mouse":
            # Dla myszy użyj paddingu wokół kursora
            crop_w = int((req.mouse_padding * 2) / req.zoom_level)
            crop_h = int((req.mouse_padding * 2) / req.zoom_level)
        else:
            # Dla innych trybów użyj target dimensions
            aspect = target_w / target_h
            if iw / ih > aspect:
                crop_h = int(ih / req.zoom_level)
                crop_w = int(crop_h * aspect)
            else:
                crop_w = int(iw / req.zoom_level)
                crop_h = int(crop_w / aspect)

        # Ogranicz do rozmiarów obrazu
        crop_w = min(crop_w, iw)
        crop_h = min(crop_h, ih)

        # Wyśrodkuj na wybranym punkcie
        left = max(0, min(cx - crop_w // 2, iw - crop_w))
        top = max(0, min(cy - crop_h // 2, ih - crop_h))

        # Jeśli region wychodzi poza obraz, przesuń
        if left + crop_w > iw:
            left = iw - crop_w
        if top + crop_h > ih:
            top = ih - crop_h

        cropped = img.crop((left, top, left + crop_w, top + crop_h))
        cropped = cropped.resize((target_w, target_h), Image.LANCZOS)

        preview_name = f"crop_{idx:04d}_{target_w}x{target_h}.png"
        cropped.save(preview_dir / preview_name, "PNG")

        results.append({
            "index": idx,
            "filename": preview_name,
            "crop": {"left": left, "top": top, "w": crop_w, "h": crop_h},
            "center": {"x": cx, "y": cy},
            "target": {"w": target_w, "h": target_h},
            "focus_mode": req.focus_mode,
            "zoom_level": req.zoom_level,
        })

    return {"previews": results, "target": {"w": target_w, "h": target_h}}


@app.post("/api/sessions/{name}/video-preview")
async def generate_video_preview(name: str, req: CropRequest):
    """Generuj podgląd pierwszej klatki wideo z ustawieniami focus/zoom."""
    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404, "Session not found")
    meta = json.loads(meta_file.read_text())

    # Użyj tylko pierwszej zaznaczonej klatki
    selected = req.frame_indices or meta.get("selected_frames", [0])
    if not selected:
        selected = [0]
    first_frame_idx = selected[0]
    
    if first_frame_idx >= len(meta.get("frames", [])):
        raise HTTPException(404, "No frames available")

    # Generuj crop preview tylko dla pierwszej klatki
    req.frame_indices = [first_frame_idx]
    crop_result = await crop_preview(name, req)
    
    if not crop_result["previews"]:
        raise HTTPException(404, "Failed to generate preview")
    
    preview = crop_result["previews"][0]
    preview_url = f"/api/sessions/{name}/preview/{preview['filename']}"
    
    return {
        "preview_url": preview_url,
        "frame_index": preview["index"],
        "focus_mode": preview["focus_mode"],
        "zoom_level": preview["zoom_level"],
        "center": preview["center"],
        "crop": preview["crop"],
        "target": preview["target"],
        "settings": {
            "preset": req.preset,
            "focus_mode": req.focus_mode,
            "zoom_level": req.zoom_level,
            "mouse_padding": req.mouse_padding,
        }
    }


@app.get("/api/sessions/{name}/preview/{filename}")
async def get_preview_image(name: str, filename: str):
    filepath = data_dir() / "sessions" / name / "preview" / filename
    if not filepath.exists():
        raise HTTPException(404)
    return FileResponse(filepath, media_type="image/png")


# ─── API: Tab 4 - Multi-version generation ───────────────────────────────────

class MultiVersionRequest(BaseModel):
    presets: list[str]
    frame_indices: list[int] | None = None


@app.post("/api/sessions/{name}/generate-versions")
async def generate_versions(name: str, req: MultiVersionRequest):
    """Generuj wiele wersji (presetów) naraz."""
    results = {}
    for preset in req.presets:
        if preset not in CROP_PRESETS:
            continue
        crop_req = CropRequest(preset=preset, frame_indices=req.frame_indices)
        preview = await crop_preview(name, crop_req)
        results[preset] = {
            "label": CROP_PRESETS[preset]["label"],
            "previews": preview["previews"],
            "target": preview["target"],
        }
    return results


# ─── API: Tab 5 - Export & Publish ────────────────────────────────────────────

class ExportRequest(BaseModel):
    preset: str
    frame_indices: list[int] | None = None
    format: str = "video"  # "video" | "gif" | "webm" | "zip"
    duration_per_frame: float = 2.0
    transition: float = 0.3
    fps: int = 2
    quality: int = 70
    focus_mode: str = "screen"  # "screen" | "mouse" | "keyboard" | "application"
    zoom_level: float = 1.0  # 1.0 - 10.0
    mouse_padding: int = 100  # piksele wokół myszy


@app.post("/api/sessions/{name}/export")
async def export_session(name: str, req: ExportRequest):
    """Eksportuj jako wideo, GIF, WebM lub ZIP."""

    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404)

    # Najpierw generuj przycięte klatki z focus mode i zoom
    crop_req = CropRequest(
        preset=req.preset, 
        frame_indices=req.frame_indices,
        focus_mode=req.focus_mode,
        zoom_level=req.zoom_level,
        mouse_padding=req.mouse_padding
    )
    crop_result = await crop_preview(name, crop_req)

    preview_dir = data_dir() / "sessions" / name / "preview"
    export_dir = data_dir() / "exports"
    export_dir.mkdir(exist_ok=True)

    preset_info = CROP_PRESETS.get(req.preset, {"w": 1920, "h": 1080})
    tw, th = preset_info["w"], preset_info["h"]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if req.format == "gif":
        # Generuj GIF
        output_name = f"{name}_{req.preset}_{timestamp}.gif"
        output_path = export_dir / output_name
        images = []
        for p in crop_result["previews"]:
            img = Image.open(preview_dir / p["filename"])
            images.append(img)
        if images:
            # Calculate quality for GIF (1-100, where 100 is best)
            gif_quality = max(1, min(100, req.quality))
            images[0].save(
                output_path, save_all=True, append_images=images[1:],
                duration=int(req.duration_per_frame * 1000), loop=0, optimize=True,
                quality=gif_quality
            )

    elif req.format == "webm":
        # Generuj WebM
        output_name = f"{name}_{req.preset}_{timestamp}.webm"
        output_path = export_dir / output_name

        # Użyj ffmpeg do złożenia WebM
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
            for p in crop_result["previews"]:
                fpath = preview_dir / p["filename"]
                f.write(f"file '{fpath}'\n")
                f.write(f"duration {req.duration_per_frame}\n")
            # Powtórz ostatni aby uniknąć obcięcia
            if crop_result["previews"]:
                last = preview_dir / crop_result["previews"][-1]["filename"]
                f.write(f"file '{last}'\n")
            list_file = f.name

        try:
            # Calculate CRF based on quality (lower CRF = higher quality)
            # Quality 10-100 -> CRF 50-10 (inverted scale)
            crf = max(10, min(50, 60 - req.quality // 2))
            bitrate = f"{max(500, req.quality * 20)}k"
            
            cmd = [
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', list_file,
                '-vf', f'scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2',
                '-c:v', 'libvpx-vp9', '-crf', str(crf), '-b:v', bitrate,
                '-r', str(req.fps),
                str(output_path),
            ]
            subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError:
            # Fallback: GIF jeśli ffmpeg nie dostępny
            output_name = output_name.replace('.webm', '.gif')
            output_path = export_dir / output_name
            images = [Image.open(preview_dir / p["filename"]) for p in crop_result["previews"]]
            if images:
                images[0].save(
                    output_path, save_all=True, append_images=images[1:],
                    duration=int(req.duration_per_frame * 1000), loop=0,
                )
        finally:
            Path(list_file).unlink(missing_ok=True)

    elif req.format == "zip":
        output_name = f"{name}_{req.preset}_{timestamp}.zip"
        output_path = export_dir / output_name
        import zipfile
        with zipfile.ZipFile(output_path, 'w') as zf:
            for p in crop_result["previews"]:
                fpath = preview_dir / p["filename"]
                zf.write(fpath, p["filename"])

    else:  # video
        output_name = f"{name}_{req.preset}_{timestamp}.mp4"
        output_path = export_dir / output_name

        # Użyj ffmpeg do złożenia wideo
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
            for p in crop_result["previews"]:
                fpath = preview_dir / p["filename"]
                f.write(f"file '{fpath}'\n")
                f.write(f"duration {req.duration_per_frame}\n")
            # Powtórz ostatni aby uniknąć obcięcia
            if crop_result["previews"]:
                last = preview_dir / crop_result["previews"][-1]["filename"]
                f.write(f"file '{last}'\n")
            list_file = f.name

        try:
            # Calculate CRF based on quality (lower CRF = higher quality)
            # Quality 10-100 -> CRF 40-18 (inverted scale)
            crf = max(18, min(40, 50 - req.quality // 3))
            
            cmd = [
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', list_file,
                '-vf', f'scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2',
                '-c:v', 'libx264', '-crf', str(crf), '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', '-r', str(req.fps),
                str(output_path),
            ]
            subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError:
            # Fallback: GIF jeśli ffmpeg nie dostępny
            output_name = output_name.replace('.mp4', '.gif')
            output_path = export_dir / output_name
            images = [Image.open(preview_dir / p["filename"]) for p in crop_result["previews"]]
            if images:
                images[0].save(
                    output_path, save_all=True, append_images=images[1:],
                    duration=int(req.duration_per_frame * 1000), loop=0,
                )
        finally:
            Path(list_file).unlink(missing_ok=True)

    return {
        "filename": output_name,
        "size_mb": round(output_path.stat().st_size / (1024*1024), 2),
        "download_url": f"/api/exports/{output_name}",
    }


@app.get("/api/exports/{filename}")
async def download_export(filename: str):
    filepath = data_dir() / "exports" / filename
    if not filepath.exists():
        raise HTTPException(404)
    return FileResponse(filepath, filename=filename)


@app.get("/api/social-links")
async def get_social_links():
    return SOCIAL_LINKS


# ─── API: Browser Screen Capture ─────────────────────────────────────────────

class BrowserCaptureFrame(BaseModel):
    session_name: str
    frame_index: int
    image_data: str  # base64 PNG


@app.post("/api/capture/frame")
async def capture_frame_from_browser(frame: BrowserCaptureFrame):
    """Receive a single frame from browser Screen Capture API."""
    import base64

    session_dir = data_dir() / "sessions" / frame.session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "frames").mkdir(exist_ok=True)

    # Decode base64 image
    img_data = frame.image_data.split(",", 1)[-1]  # strip data:image/png;base64,
    img_bytes = base64.b64decode(img_data)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    filename = f"frame_{frame.frame_index:04d}.png"
    img.save(session_dir / "frames" / filename, "PNG")

    return {
        "ok": True,
        "filename": filename,
        "width": img.width,
        "height": img.height,
    }


class BrowserCaptureFinalize(BaseModel):
    session_name: str
    frame_count: int
    duration: float


@app.post("/api/capture/finalize")
async def finalize_browser_capture(req: BrowserCaptureFinalize):
    """Finalize a browser capture session — write session.json."""
    session_dir = data_dir() / "sessions" / req.session_name
    frames_dir = session_dir / "frames"

    frames = []
    for i in range(req.frame_count):
        filename = f"frame_{i:04d}.png"
        fpath = frames_dir / filename
        if fpath.exists():
            img = Image.open(fpath)
            frames.append({
                "index": i,
                "timestamp": round(i * (req.duration / max(req.frame_count, 1)), 3),
                "filename": filename,
                "width": img.width,
                "height": img.height,
                "change_pct": 100.0 if i == 0 else 0.0,
                "mouse_x": img.width // 2,
                "mouse_y": img.height // 2,
                "suggested_center_x": img.width // 2,
                "suggested_center_y": img.height // 2,
                "input_events": [],
            })

    meta = {
        "name": req.session_name,
        "created_at": datetime.utcnow().isoformat(),
        "duration": req.duration,
        "frame_count": len(frames),
        "settings": {"source": "browser_capture"},
        "frames": frames,
        "input_log": [],
    }
    (session_dir / "session.json").write_text(json.dumps(meta, indent=2))
    return {"name": req.session_name, "frame_count": len(frames)}


@app.get("/api/capture/backends")
async def get_capture_backends():
    """Return available capture backends."""
    from xeen.capture_backends import list_available_backends
    return list_available_backends()


# ─── Frontend ─────────────────────────────────────────────────────────────────

@app.get("/capture", response_class=HTMLResponse)
async def capture_page():
    """Browser-based screen capture page."""
    template = Path(__file__).parent / "templates" / "capture.html"
    return HTMLResponse(template.read_text())


@app.get("/", response_class=HTMLResponse)
async def index():
    """Session selection page - grid of last 9 sessions with thumbnails."""
    template = Path(__file__).parent / "templates" / "sessions.html"
    return HTMLResponse(template.read_text())


@app.get("/session/{name}", response_class=HTMLResponse)
async def session_page(name: str):
    """Editor page for a specific session."""
    template = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(template.read_text())


@app.get("/session/{name}/tab/{tab_name}", response_class=HTMLResponse)
async def session_tab_page(name: str, tab_name: str):
    """Editor page for a specific session and tab."""
    template = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(template.read_text())


@app.get("/session/{name}/frame/{frame_index}", response_class=HTMLResponse)
async def session_frame_page(name: str, frame_index: int):
    """Editor page focused on a specific frame."""
    template = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(template.read_text())


@app.get("/session/{name}/export/{export_id}", response_class=HTMLResponse)
async def session_export_page(name: str, export_id: str):
    """Export page for a specific session."""
    template = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(template.read_text())
