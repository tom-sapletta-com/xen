"""FastAPI server for xeen web editor."""

import json
import io
import logging
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from PIL import Image

# Dodaj loguru dla lepszego logowania
try:
    from loguru import logger
    # Usuń domyślny handler i dodaj własny
    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),  # Drukuj bez dodatkowych newline
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )
    
    # Dekoratory do logowania
    def log_request(func):
        """Decorator do logowania requestów API"""
        import functools
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Pobierz nazwę sesji z args jeśli dostępna
            session_name = "unknown"
            if args and hasattr(args[0], '__name__') and 'session' in str(args):
                for arg in args:
                    if isinstance(arg, str) and len(arg) > 10:  # prawdopodobnie nazwa sesji
                        session_name = arg
                        break
            
            logger.info(f"🌐 **API Request**: `{func.__name__}` for session `{session_name}`")
            start_time = datetime.now()
            
            try:
                result = await func(*args, **kwargs)
                duration = (datetime.now() - start_time).total_seconds()
                logger.info(f"✅ **API Success**: `{func.__name__}` completed in `{duration:.3f}s`")
                return result
            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds()
                logger.error(f"❌ **API Error**: `{func.__name__}` failed in `{duration:.3f}s` - `{str(e)}`")
                raise
        return wrapper
    
    def log_process_step(step_name):
        """Decorator do logowania kroków procesowych"""
        def decorator(func):
            import functools
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                logger.info(f"⏳ **Process Step**: Starting `{step_name}`")
                start_time = datetime.now()
                
                try:
                    result = await func(*args, **kwargs)
                    duration = (datetime.now() - start_time).total_seconds()
                    logger.info(f"✅ **Process Step**: `{step_name}` completed in `{duration:.3f}s`")
                    return result
                except Exception as e:
                    duration = (datetime.now() - start_time).total_seconds()
                    logger.error(f"❌ **Process Step**: `{step_name}` failed in `{duration:.3f}s` - `{str(e)}`")
                    raise
            return wrapper
        return decorator
    
except ImportError:
    # Fallback do standardowego logging jeśli loguru nie jest zainstalowane
    logger = logging.getLogger("xeen.server")
    logging.basicConfig(
        format='%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.INFO
    )
    logger.info("⚠️  Zainstaluj 'loguru' dla lepszego formatowania logów: pip install loguru")
    
    # Puste dekoratory fallback
    def log_request(func):
        return func
    def log_process_step(step_name):
        def decorator(func):
            return func
        return decorator

from fastapi import FastAPI, HTTPException, UploadFile, File, Header
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

# Middleware do logowania wszystkich requestów
@app.middleware("http")
async def log_requests(request, call_next):
    """Log every HTTP request with detailed information."""
    start_time = datetime.now()
    
    # Pobierz informacje o requescie
    method = request.method
    url = str(request.url)
    path = request.url.path
    
    # Ekstrakcja nazwy sesji z URL jeśli dostępna
    session_name = "unknown"
    if "/api/sessions/" in path:
        parts = path.split("/")
        if len(parts) > 3:
            session_name = parts[3]
    
    # Loguj początek requestu
    logger.info(f"🌐 **HTTP Request**: `{method} {path}` for session `{session_name}`")
    
    try:
        response = await call_next(request)
        duration = (datetime.now() - start_time).total_seconds()
        
        # Loguj sukces
        logger.info(f"✅ **HTTP Response**: `{method} {path}` → `{response.status_code}` in `{duration:.3f}s`")
        
        return response
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        
        # Loguj błąd
        logger.error(f"❌ **HTTP Error**: `{method} {path}` failed in `{duration:.3f}s` - `{str(e)}`")
        raise

# Mount static files
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


def data_dir() -> Path:
    return get_data_dir()


# ─── Startup Event ────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    """Log startup information in Markdown style."""
    data_path = data_dir()
    
    logger.info("🚀 **xeen server starting up**")
    logger.info(f"📁 **Data directory**: `{data_path}`")
    logger.info(f"🌐 **Server URL**: `http://127.0.0.1:7600`")
    logger.info(f"📸 **Static files**: `{_static_dir}`")
    logger.info("✅ **Server ready to accept connections**")
    logger.info("---")


# ─── API: Branding ───────────────────────────────────────────────────────────

class BrandingRequest(BaseModel):
    logo_data: str | None = None          # base64 data URL
    logo_position: str = "bottom_right"   # preset or "custom"
    logo_position_x: float | None = None  # 0.0-1.0 if custom
    logo_position_y: float | None = None
    logo_size: int = 64
    logo_opacity: float = 0.8
    footer_text: str | None = None
    footer_font_size: int = 18
    footer_color: str = "#ffffff"
    footer_bg: str = "#00000099"


@app.get("/api/branding")
async def get_branding():
    """Zwróć aktualną konfigurację branding.json."""
    from xeen.branding import load_branding
    return load_branding()


@app.post("/api/branding")
async def save_branding(req: BrandingRequest):
    """Zapisz konfigurację znaku wodnego do ~/.xeen/branding.json."""
    import base64, io as _io
    config_path = data_dir() / "branding.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    logo_path = None
    if req.logo_data and req.logo_data.startswith("data:image"):
        # Decode base64 and save as logo.png
        header, b64 = req.logo_data.split(",", 1)
        logo_bytes = base64.b64decode(b64)
        logo_path = str(data_dir() / "logo.png")
        with open(logo_path, "wb") as f:
            f.write(logo_bytes)
        logger.info(f"🖼️ **Logo saved**: `{logo_path}`")

    branding = {
        "logo": logo_path,
        "logo_position": req.logo_position,
        "logo_position_x": req.logo_position_x,
        "logo_position_y": req.logo_position_y,
        "logo_size": req.logo_size,
        "logo_opacity": req.logo_opacity,
        "footer_text": req.footer_text or None,
        "footer_font_size": req.footer_font_size,
        "footer_color": req.footer_color,
        "footer_bg": req.footer_bg,
    }
    config_path.write_text(json.dumps(branding, indent=2))
    logger.info(f"💾 **Branding saved** to `{config_path}`")
    return {"ok": True, "path": str(config_path)}


# ─── API: Sessions ───────────────────────────────────────────────────────────

@app.get("/api/sessions")
@log_request
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

        # Oblicz region przycinania — zawsze zachowuj target aspect ratio
        # zoom_level > 1 = mniejszy wycinek (bardziej przybliżony)
        aspect = target_w / target_h
        if req.focus_mode == "mouse":
            # Bazuj na mouse_padding jako połowie krótszego boku, skaluj przez zoom
            base = min(req.mouse_padding * 2, min(iw, ih))
            base_zoomed = base / req.zoom_level
            # Dopasuj do aspect ratio targetu
            if aspect >= 1:  # szerszy niż wysoki
                crop_h = int(base_zoomed)
                crop_w = int(crop_h * aspect)
            else:
                crop_w = int(base_zoomed)
                crop_h = int(crop_w / aspect)
        else:
            if iw / ih > aspect:
                crop_h = int(ih / req.zoom_level)
                crop_w = int(crop_h * aspect)
            else:
                crop_w = int(iw / req.zoom_level)
                crop_h = int(crop_w / aspect)

        # Ogranicz do rozmiarów obrazu (zachowując aspect ratio)
        if crop_w > iw:
            crop_w = iw
            crop_h = int(crop_w / aspect)
        if crop_h > ih:
            crop_h = ih
            crop_w = int(crop_h * aspect)
        crop_w = max(1, crop_w)
        crop_h = max(1, crop_h)

        # Wyśrodkuj na wybranym punkcie, nie wychodź poza obraz
        left = max(0, min(cx - crop_w // 2, iw - crop_w))
        top = max(0, min(cy - crop_h // 2, ih - crop_h))

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
@log_request
@log_process_step("video_preview_generation")
async def generate_video_preview(name: str, req: CropRequest):
    """Generuj podgląd pierwszej klatki wideo z ustawieniami focus/zoom - szybka miniatura."""
    start_time = datetime.now()
    logger.info(f"🎬 **Generating video preview** for session `{name}`")
    logger.info(f"   - **Focus mode**: `{req.focus_mode}`")
    logger.info(f"   - **Zoom level**: `{req.zoom_level}x`")
    logger.info(f"   - **Mouse padding**: `{req.mouse_padding}px`")
    
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

    # Pobierz dane klatki
    frame = meta["frames"][first_frame_idx]
    frame_path = data_dir() / "sessions" / name / "frames" / frame["filename"]
    
    if not frame_path.exists():
        raise HTTPException(404, "Frame file not found")

    # Twórz miniaturę z 10x mniejszą rozdzielczością
    preview_dir = data_dir() / "sessions" / name / "preview"
    preview_dir.mkdir(exist_ok=True)
    
    # Użyj mniejszych wymiarów dla podglądu (10x mniej niż target)
    preset = CROP_PRESETS.get(req.preset, CROP_PRESETS["instagram_post"])
    small_target_w = preset["w"] // 10
    small_target_h = preset["h"] // 10
    
    # Upewnij się, że wymiary są co najmniej 100px
    small_target_w = max(small_target_w, 100)
    small_target_h = max(small_target_h, 100)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    preview_filename = f"preview_{first_frame_idx}_{req.preset}_{timestamp}.jpg"
    preview_path = preview_dir / preview_filename

    # Szybkie generowanie miniatury
    img = Image.open(frame_path)
    iw, ih = img.size

    # Wybierz środek w zależności od focus_mode
    if req.focus_mode == "mouse":
        cx = frame.get("mouse_x", iw // 2)
        cy = frame.get("mouse_y", ih // 2)
    elif req.focus_mode == "keyboard":
        cx = frame.get("suggested_center_x", iw // 2)
        cy = int(ih * 0.75)
    elif req.focus_mode == "application":
        cx = frame.get("suggested_center_x", iw // 2)
        cy = int(ih * 0.25)
    else:  # screen
        cx = frame.get("suggested_center_x", iw // 2)
        cy = frame.get("suggested_center_y", ih // 2)

    # Oblicz region przycinania — zawsze zachowuj target aspect ratio
    aspect = small_target_w / small_target_h
    if req.focus_mode == "mouse":
        base = min(req.mouse_padding * 2, min(iw, ih))
        base_zoomed = base / req.zoom_level
        if aspect >= 1:
            crop_h = int(base_zoomed)
            crop_w = int(crop_h * aspect)
        else:
            crop_w = int(base_zoomed)
            crop_h = int(crop_w / aspect)
        logger.info(f"   - **Crop base**: `{base}px` → zoomed `{base_zoomed:.0f}px`")
        logger.info(f"   - **Screen size**: `{iw}x{ih}px`")
    else:
        if iw / ih > aspect:
            crop_h = int(ih / req.zoom_level)
            crop_w = int(crop_h * aspect)
        else:
            crop_w = int(iw / req.zoom_level)
            crop_h = int(crop_w / aspect)

    # Ogranicz do rozmiarów obrazu (zachowując aspect ratio)
    if crop_w > iw:
        crop_w = iw
        crop_h = int(crop_w / aspect)
    if crop_h > ih:
        crop_h = ih
        crop_w = int(crop_h * aspect)
    crop_w = max(1, crop_w)
    crop_h = max(1, crop_h)

    # Wyśrodkuj na wybranym punkcie, nie wychodź poza obraz
    left = max(0, min(cx - crop_w // 2, iw - crop_w))
    top = max(0, min(cy - crop_h // 2, ih - crop_h))

    # Wytnij i zmniejsz szybko (bez LANCZOS dla szybkości)
    cropped = img.crop((left, top, left + crop_w, top + crop_h))
    cropped = cropped.resize((small_target_w, small_target_h), Image.BILINEAR)  # Szybsze niż LANCZOS
    
    # Zapisz z umiarkowaną jakością dla szybkości
    cropped.save(preview_path, "JPEG", quality=85, optimize=True)
    
    # Log performance metrics
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    file_size = preview_path.stat().st_size
    
    logger.info(f"✅ **Preview generated successfully**")
    logger.info(f"   - **Frame**: #{first_frame_idx + 1}")
    logger.info(f"   - **Size**: `{small_target_w}x{small_target_h}px` (10x smaller)")
    logger.info(f"   - **File size**: `{file_size} bytes`")
    logger.info(f"   - **Generation time**: `{duration:.3f}s`")
    logger.info(f"   - **Center**: `({cx}, {cy})`")

    preview_url = f"/api/sessions/{name}/preview/{preview_filename}"
    
    return {
        "preview_url": preview_url,
        "frame_index": first_frame_idx,
        "focus_mode": req.focus_mode,
        "zoom_level": req.zoom_level,
        "center": {"x": cx, "y": cy},
        "crop": {"left": left, "top": top, "w": crop_w, "h": crop_h},
        "target": {"w": small_target_w, "h": small_target_h},
        "settings": {
            "preset": req.preset,
            "focus_mode": req.focus_mode,
            "zoom_level": req.zoom_level,
            "mouse_padding": req.mouse_padding,
        }
    }


@app.get("/api/sessions/{name}/preview/{filename}")
async def get_preview_image(
    name: str,
    filename: str,
    watermark: int = 0,
    quality: int = 85,
    # inline watermark config (overrides branding.json when watermark=1)
    wm_pos: str | None = None,
    wm_px: float | None = None,
    wm_py: float | None = None,
    wm_text: str | None = None,
    wm_tc: str | None = None,
    wm_fs: int | None = None,
    wm_bg: str | None = None,
):
    filepath = data_dir() / "sessions" / name / "preview" / filename
    if not filepath.exists():
        raise HTTPException(404)

    # Fast path: no processing needed
    if not watermark and quality >= 95:
        return FileResponse(filepath, media_type="image/jpeg" if filename.endswith(".jpg") else "image/png")

    import io
    img = Image.open(filepath).convert("RGB")

    if watermark:
        try:
            from xeen.branding import load_branding, apply_watermark
            branding = load_branding()
            # Override with inline params if provided
            if wm_pos is not None:
                branding["logo_position"] = wm_pos
            if wm_px is not None:
                branding["logo_position_x"] = wm_px
            if wm_py is not None:
                branding["logo_position_y"] = wm_py
            if wm_text is not None:
                branding["footer_text"] = wm_text or None
            if wm_tc is not None:
                branding["footer_color"] = wm_tc
            if wm_fs is not None:
                branding["footer_font_size"] = wm_fs
            if wm_bg is not None:
                branding["footer_bg"] = wm_bg
            img = apply_watermark(img, branding)
        except Exception:
            pass

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=max(10, min(95, quality)), optimize=True)
    buf.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(buf, media_type="image/jpeg")


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


# ─── API: Captions (Napisy) ───────────────────────────────────────────────────

class Caption(BaseModel):
    id: str
    frame_start: int
    frame_end: int
    text: str
    x: float = 50.0       # % from left
    y: float = 85.0       # % from top
    font_size: int = 32
    color: str = "#ffffff"
    bg_color: str = "#000000"
    bg_opacity: float = 0.5
    bold: bool = False
    italic: bool = False
    align: str = "center"  # left | center | right


class CaptionsPayload(BaseModel):
    captions: list[Caption]


class CaptionGenerateRequest(BaseModel):
    frame_indices: list[int] | None = None
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    language: str = "pl"
    style: str = "tutorial"  # tutorial | social | minimal | descriptive


@app.get("/api/sessions/{name}/captions")
async def get_captions(name: str):
    """Pobierz napisy sesji."""
    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404)
    meta = json.loads(meta_file.read_text())
    return {"captions": meta.get("captions", [])}


@app.post("/api/sessions/{name}/captions")
async def save_captions(name: str, payload: CaptionsPayload):
    """Zapisz napisy sesji."""
    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404)
    meta = json.loads(meta_file.read_text())
    meta["captions"] = [c.dict() for c in payload.captions]
    meta_file.write_text(json.dumps(meta, indent=2))
    logger.info(f"💬 **Captions saved**: `{len(payload.captions)}` for session `{name}`")
    return {"ok": True, "count": len(payload.captions)}


@app.post("/api/sessions/{name}/captions/generate")
async def generate_captions(name: str, req: CaptionGenerateRequest, x_llm_api_key: str | None = Header(default=None)):
    """Generuj napisy przez LLM (liteLLM)."""
    import os
    import base64

    meta_file = data_dir() / "sessions" / name / "session.json"
    if not meta_file.exists():
        raise HTTPException(404)
    meta = json.loads(meta_file.read_text())
    frames = meta.get("frames", [])
    selected = req.frame_indices or list(range(len(frames)))

    style_prompts = {
        "tutorial":     "Opisz krok po kroku co widać na ekranie, używając czasu teraźniejszego. Max 10 słów.",
        "social":       "Napisz angażujący, krótki opis dla social media. Max 8 słów.",
        "minimal":      "Opisz akcję jednym zdaniem. Max 6 słów.",
        "descriptive":  "Opisz szczegółowo co dzieje się na ekranie. Max 15 słów.",
    }
    style_hint = style_prompts.get(req.style, style_prompts["tutorial"])
    lang_hint = "Odpowiedź po polsku." if req.language == "pl" else f"Answer in {req.language}."

    try:
        import litellm
        litellm.set_verbose = False
    except ImportError:
        raise HTTPException(500, "liteLLM not installed. Run: pip install litellm")

    # Map provider to env var names and apply API key from header or env
    env_var_map = {
        "openai":    "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini":    "GEMINI_API_KEY",
        "ollama":    None,
    }
    env_var = env_var_map.get(req.provider)
    if x_llm_api_key and env_var:
        os.environ[env_var] = x_llm_api_key
        logger.info(f"🔑 **API key set** from request header for provider `{req.provider}`")
    elif env_var and not os.environ.get(env_var):
        logger.warning(f"⚠️ **No API key** found for `{req.provider}` — set `{env_var}` env var")

    captions = []
    for idx in selected[:20]:  # limit do 20 klatek
        frame = frames[idx] if idx < len(frames) else None
        if not frame:
            continue

        frame_path = data_dir() / "sessions" / name / "frames" / frame["filename"]
        if not frame_path.exists():
            continue

        # Encode image as base64
        with open(frame_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        try:
            response = await litellm.acompletion(
                model=f"{req.provider}/{req.model}" if req.provider != "openai" else req.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"{style_hint} {lang_hint}"
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        },
                    ],
                }],
                max_tokens=60,
            )
            text = response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"⚠️ LLM failed for frame {idx}: {e}")
            text = f"Klatka #{idx + 1}"

        captions.append({
            "id": f"cap_{idx}",
            "frame_start": idx,
            "frame_end": idx,
            "text": text,
            "x": 50.0,
            "y": 85.0,
            "font_size": 32,
            "color": "#ffffff",
            "bg_color": "#000000",
            "bg_opacity": 0.5,
            "bold": False,
            "italic": False,
            "align": "center",
        })

    logger.info(f"💬 **Captions generated**: `{len(captions)}` frames via `{req.model}`")
    return {"captions": captions, "model": req.model, "style": req.style}


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
    watermark: bool = False


@app.post("/api/sessions/{name}/export")
@log_request
@log_process_step("export_generation")
async def export_session(name: str, req: ExportRequest):
    """Eksportuj jako wideo, GIF, WebM lub ZIP."""
    start_time = datetime.now()
    logger.info(f"📦 **Starting export** for session `{name}`")
    logger.info(f"   - **Format**: `{req.format.upper()}`")
    logger.info(f"   - **Preset**: `{req.preset}`")
    logger.info(f"   - **Frames**: `{len(req.frame_indices) if req.frame_indices else 'all'}`")
    logger.info(f"   - **Duration/frame**: `{req.duration_per_frame}s`")
    logger.info(f"   - **FPS**: `{req.fps}`")
    logger.info(f"   - **Quality**: `{req.quality}%`")
    logger.info(f"   - **Focus mode**: `{req.focus_mode}`")
    logger.info(f"   - **Zoom level**: `{req.zoom_level}x`")

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

    # Apply watermark to preview frames in-place if requested
    if req.watermark:
        try:
            from xeen.branding import load_branding, apply_watermark
            branding = load_branding()
            if branding.get("logo") or branding.get("footer_text"):
                for p in crop_result["previews"]:
                    fpath = preview_dir / p["filename"]
                    if fpath.exists():
                        wm_img = apply_watermark(Image.open(fpath), branding)
                        wm_img.save(fpath, "PNG")
                logger.info(f"🌊 **Watermark applied** to `{len(crop_result['previews'])}` frames")
        except Exception as e:
            logger.warning(f"⚠️ Watermark failed: {e}")

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

    # Log export completion
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    file_size = output_path.stat().st_size
    size_mb = round(file_size / (1024*1024), 2)
    
    logger.info(f"✅ **Export completed successfully**")
    logger.info(f"   - **File**: `{output_name}`")
    logger.info(f"   - **Size**: `{size_mb} MB`")
    logger.info(f"   - **Duration**: `{duration:.2f}s`")
    logger.info(f"   - **Target resolution**: `{tw}x{th}px`")
    logger.info("---")

    return {
        "filename": output_name,
        "size_mb": size_mb,
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
