import os
import re
import json
import uuid
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="CapCut Sync Studio")
app.mount("/static", StaticFiles(directory="static"), name="static")

DEFAULT_CAPCUT_PATH = os.path.expandvars(r"%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft")
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

class ScanRequest(BaseModel):
    images_dir: str
    srt_path: str
    audio_path: Optional[str] = ""
    motion_path: Optional[str] = ""

class SyncDraftRequest(BaseModel):
    images_dir: str
    srt_path: str
    audio_path: Optional[str] = ""
    draft_name: Optional[str] = ""
    project_name: Optional[str] = ""
    draft_root: Optional[str] = ""
    fps: Optional[int] = 30
    width: Optional[int] = 1920
    height: Optional[int] = 1080
    effect: Optional[str] = "none"
    zoom_strength: Optional[float] = 0.15
    motion_path: Optional[str] = ""

def choose_folder_dialog(title="Select Folder"):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        path = filedialog.askdirectory(title=title)
        root.destroy()
        return path or ""
    except Exception:
        return ""

def choose_file_dialog(filetypes, title="Select File"):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        root.destroy()
        return path or ""
    except Exception:
        return ""

def parse_time_to_us(ts_str: str) -> int:
    ts_str = str(ts_str).strip().replace(',', '.')
    parts = ts_str.split(':')
    h = float(parts[0])
    m = float(parts[1])
    s = float(parts[2])
    return int(round((h * 3600 + m * 60 + s) * 1_000_000))

def format_us(us: int) -> str:
    total_sec = us / 1_000_000
    m = int(total_sec // 60)
    s = total_sec % 60
    return f"{m:02d}:{s:06.3f}"

def parse_srt_file(path: str) -> List[Dict]:
    content = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\n(.*?)(?=\n\n|\n*$)', re.DOTALL)
    matches = pattern.findall(content.strip())
    cues = []
    for m in matches:
        cues.append({
            "index": int(m[0]),
            "start_str": m[1],
            "end_str": m[2],
            "start_us": parse_time_to_us(m[1]),
            "end_us": parse_time_to_us(m[2]),
            "text": m[3].replace("\n", " ").strip()
        })
    return cues

def scan_images(folder: str) -> Dict[int, Path]:
    found = {}
    p_folder = Path(folder)
    if not p_folder.is_dir():
        return found
    for p in sorted(p_folder.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMG_EXT:
            nums = re.findall(r'\d+', p.stem)
            if nums:
                m = re.match(r'^(\d+)', p.stem)
                n = int(m.group(1)) if m else int(nums[-1])
                if n not in found:
                    found[n] = p
    return found

def find_duplicate_numbers(folder: str) -> List[str]:
    """Warn when two image files start with the same number (only the first one is used)."""
    seen: Dict[int, str] = {}
    warns = []
    p_folder = Path(folder)
    if not p_folder.is_dir():
        return warns
    for p in sorted(p_folder.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMG_EXT:
            m = re.match(r'^(\d+)', p.stem)
            if not m:
                continue
            n = int(m.group(1))
            if n in seen:
                warns.append(f"Duplicate number {n}: '{p.name}' is skipped (using '{seen[n]}').")
            else:
                seen[n] = p.name
    return warns

def calculate_plan(cues: List[Dict], images: Dict[int, Path]):
    total_images = len(images)
    total_cues = len(cues)
    plan = []
    if total_images == 0:
        return plan

    if total_cues == total_images:
        for idx in sorted(images.keys()):
            if idx <= len(cues):
                c = cues[idx - 1]
                nxt = cues[idx]["start_us"] if idx < len(cues) else c["end_us"]
                plan.append({
                    "image_idx": idx,
                    "file_name": images[idx].name,
                    "file_path": str(images[idx].resolve()),
                    "start_us": c["start_us"] if idx > 1 else 0,
                    "end_us": nxt,
                    "duration_us": nxt - (c["start_us"] if idx > 1 else 0),
                    "narration": c["text"]
                })
    else:
        slots_needed = sorted(images.keys())
        total_slots = len(slots_needed)
        cue_durations = []
        for i, c in enumerate(cues):
            nxt = cues[i+1]["start_us"] if i+1 < len(cues) else c["end_us"]
            dur = nxt - (c["start_us"] if i > 0 else 0)
            cue_durations.append((i, dur))
        
        allocations = [1] * total_cues
        remaining = total_slots - total_cues
        if remaining > 0:
            sorted_by_len = sorted(cue_durations, key=lambda x: x[1], reverse=True)
            for i in range(min(remaining, total_cues)):
                idx = sorted_by_len[i][0]
                allocations[idx] += 1
                
        img_counter = 0
        for i, c in enumerate(cues):
            k = allocations[i]
            nxt = cues[i+1]["start_us"] if i+1 < len(cues) else c["end_us"]
            step = (nxt - (c["start_us"] if i > 0 else 0)) / k
            base_s = (c["start_us"] if i > 0 else 0)
            
            for j in range(k):
                if img_counter < total_slots:
                    img_num = slots_needed[img_counter]
                    s = int(base_s + j * step)
                    e = int(base_s + (j + 1) * step)
                    plan.append({
                        "image_idx": img_num,
                        "file_name": images[img_num].name,
                        "file_path": str(images[img_num].resolve()),
                        "start_us": s,
                        "end_us": e,
                        "duration_us": e - s,
                        "narration": c["text"]
                    })
                    img_counter += 1
    return plan

EFFECTS = ["none", "zoom_in", "zoom_out", "pan_left", "pan_right", "alternate", "random"]

def _keyframe(prop: str, start_val: float, end_val: float, duration_us: int) -> Dict[str, Any]:
    """One CapCut keyframe track (value animates linearly from start to end)."""
    def point(offset, val):
        return {
            "curveType": "Line",
            "graphID": "",
            "id": str(uuid.uuid4()).upper(),
            "left_control": {"x": 0.0, "y": 0.0},
            "right_control": {"x": 0.0, "y": 0.0},
            "time_offset": offset,
            "values": [val],
        }
    return {
        "id": str(uuid.uuid4()).upper(),
        "material_id": "",
        "property_type": prop,
        "keyframe_list": [point(0, start_val), point(duration_us, end_val)],
    }

VALID_EFFECTS = {"none", "zoom_in", "zoom_out", "pan_left", "pan_right"}

def load_motion_file(path: str):
    """
    Reads an AI-made motion file (JSON). Each entry: {"image": 1 or "01.jpg", "effect": "zoom_in", "strength": 0.15}
    Returns (by_number, by_name, warnings).
    """
    by_num: Dict[int, Dict] = {}
    by_name: Dict[str, Dict] = {}
    warnings: List[str] = []
    if not path:
        return by_num, by_name, warnings
    if not os.path.exists(path):
        warnings.append(f"Motion file not found: {path}")
        return by_num, by_name, warnings

    raw = Path(path).read_text(encoding="utf-8-sig").strip()
    # AI tools often wrap JSON in ```json fences
    raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except Exception as e:
        warnings.append(f"Motion file is not valid JSON: {e}")
        return by_num, by_name, warnings

    if isinstance(data, dict):
        data = data.get("images") or data.get("motions") or data.get("items") or []
    if not isinstance(data, list):
        warnings.append("Motion file must be a list of entries.")
        return by_num, by_name, warnings

    for i, entry in enumerate(data, start=1):
        if not isinstance(entry, dict) or "image" not in entry:
            warnings.append(f"Entry {i}: missing 'image' - skipped.")
            continue
        effect = str(entry.get("effect", "none")).strip().lower()
        if effect not in VALID_EFFECTS:
            warnings.append(f"Entry {i} (image {entry['image']}): unknown effect '{effect}' - skipped.")
            continue
        try:
            strength = float(entry.get("strength", 0.15))
        except Exception:
            strength = 0.15
        spec = {"effect": effect, "strength": max(0.02, min(strength, 0.6))}
        key = entry["image"]
        if isinstance(key, int) or (isinstance(key, str) and key.strip().isdigit()):
            by_num[int(str(key).strip())] = spec
        else:
            name = str(key).strip().lower()
            by_name[name] = spec
            by_name[Path(name).stem] = spec
    return by_num, by_name, warnings

def motion_for(item: Dict, by_num: Dict, by_name: Dict):
    """Find the motion-file entry for a plan item (filename first, then number)."""
    fname = item["file_name"].lower()
    return by_name.get(fname) or by_name.get(Path(fname).stem) or by_num.get(item["image_idx"])

def resolve_effect(effect: str, index: int) -> str:
    import random
    if effect == "alternate":
        return ["zoom_in", "zoom_out"][index % 2]
    if effect == "random":
        return random.choice(["zoom_in", "zoom_out", "pan_left", "pan_right"])
    return effect

def build_motion(effect: str, duration_us: int, strength: float) -> List[Dict[str, Any]]:
    """Returns CapCut keyframes (Ken Burns style) for a still image segment."""
    if effect == "none" or duration_us <= 0:
        return []
    z = 1.0 + max(0.02, min(strength, 1.0))
    if effect == "zoom_in":
        return [_keyframe("KFTypeScaleX", 1.0, z, duration_us), _keyframe("KFTypeScaleY", 1.0, z, duration_us)]
    if effect == "zoom_out":
        return [_keyframe("KFTypeScaleX", z, 1.0, duration_us), _keyframe("KFTypeScaleY", z, 1.0, duration_us)]
    # pans need the image slightly enlarged so no black edges appear
    shift = strength / 2
    if effect == "pan_left":
        return [_keyframe("KFTypeScaleX", z, z, duration_us), _keyframe("KFTypeScaleY", z, z, duration_us),
                _keyframe("KFTypePositionX", shift, -shift, duration_us)]
    if effect == "pan_right":
        return [_keyframe("KFTypeScaleX", z, z, duration_us), _keyframe("KFTypeScaleY", z, z, duration_us),
                _keyframe("KFTypePositionX", -shift, shift, duration_us)]
    return []

@app.get("/")
def get_index():
    return FileResponse("static/index.html")

def get_draft_list():
    exists = os.path.exists(DEFAULT_CAPCUT_PATH)
    drafts = []
    if exists:
        try:
            for item in os.listdir(DEFAULT_CAPCUT_PATH):
                full_p = os.path.join(DEFAULT_CAPCUT_PATH, item)
                content_p = os.path.join(full_p, "draft_content.json")
                if os.path.isdir(full_p) and os.path.exists(content_p):
                    drafts.append(item)
        except Exception:
            pass
    return sorted(drafts, reverse=True)

@app.get("/api/detect-capcut")
def detect_capcut():
    exists = os.path.exists(DEFAULT_CAPCUT_PATH)
    drafts = get_draft_list()
    return {
        "path": DEFAULT_CAPCUT_PATH,
        "detected": exists,
        "drafts": drafts,
        "existing_projects": drafts
    }

@app.get("/api/get-drafts")
def get_drafts():
    return detect_capcut()

@app.get("/api/pick-folder")
def pick_folder():
    path = choose_folder_dialog("Select Images Folder")
    return {"path": path}

@app.get("/api/pick-file")
def pick_file(kind: str = "srt"):
    if kind == "audio":
        types = [("Audio Files", "*.mp3 *.wav *.m4a *.aac *.flac"), ("All Files", "*.*")]
        title = "Select Voiceover Audio"
    elif kind == "motion":
        types = [("Motion File", "*.json *.txt"), ("All Files", "*.*")]
        title = "Select Image Motion File"
    else:
        types = [("SRT Subtitles", "*.srt"), ("All Files", "*.*")]
        title = "Select SRT Subtitle File"
    path = choose_file_dialog(types, title=title)
    return {"path": path}

@app.post("/api/scan")
def scan_project(req: ScanRequest):
    if not os.path.exists(req.srt_path):
        raise HTTPException(status_code=400, detail=f"SRT file not found: {req.srt_path}")
    if not os.path.exists(req.images_dir):
        raise HTTPException(status_code=400, detail=f"Images folder not found: {req.images_dir}")
        
    cues = parse_srt_file(req.srt_path)
    images = scan_images(req.images_dir)
    plan = calculate_plan(cues, images)
    by_num, by_name, warnings = load_motion_file((req.motion_path or "").strip())
    warnings += find_duplicate_numbers(req.images_dir)

    total_duration_us = plan[-1]["end_us"] if plan else 0
    preview_rows = []
    for item in plan:
        preview_rows.append({
            "image_idx": item["image_idx"],
            "file_name": item["file_name"],
            "start": format_us(item["start_us"]),
            "end": format_us(item["end_us"]),
            "duration": f"{item['duration_us'] / 1_000_000:.2f}s",
            "narration": item["narration"],
            "effect": (motion_for(item, by_num, by_name) or {}).get("effect", "default")
        })

    return {
        "warnings": warnings,
        "status": "success",
        "srt_cues_count": len(cues),
        "images_found": len(images),
        "total_matched": len(plan),
        "total_duration": format_us(total_duration_us),
        "plan_preview": preview_rows
    }

def execute_sync(draft_root: str, target_name: str, images_dir: str, srt_path: str, audio_path: str = "", effect: str = "none", zoom_strength: float = 0.15, motion_path: str = ""):
    project_dir = os.path.join(draft_root, target_name)
    os.makedirs(project_dir, exist_ok=True)
    content_file = os.path.join(project_dir, "draft_content.json")

    cues = parse_srt_file(srt_path)
    images = scan_images(images_dir)
    plan = calculate_plan(cues, images)

    if not plan:
        raise HTTPException(status_code=400, detail="No matching images to sync.")

    project_duration = plan[-1]["end_us"]

    # If draft_content.json doesn't exist in target folder, find template from any existing project or create basic
    if os.path.exists(content_file):
        shutil.copyfile(content_file, content_file + ".bak")
        with open(content_file, 'r', encoding='utf-8') as f:
            draft = json.load(f)
    else:
        draft = {
            "id": str(uuid.uuid4()).upper(),
            "draft_type": "video",
            "name": target_name,
            "duration": project_duration,
            "fps": 30,
            "canvas_config": {"width": 1920, "height": 1080, "ratio": "original"},
            "materials": {"videos": [], "audios": [], "speeds": [], "canvases": []},
            "tracks": []
        }

    by_num, by_name, motion_warnings = load_motion_file(motion_path)
    if motion_warnings:
        print("[Motion file warnings]", *motion_warnings, sep="\n  - ")
    motion_used = 0

    tracks = draft.get("tracks", [])
    video_track = None
    audio_track = None

    for t in tracks:
        if t.get("type") == "video" and video_track is None:
            video_track = t
        elif t.get("type") == "audio" and audio_track is None:
            audio_track = t

    if not video_track:
        video_track = {"id": str(uuid.uuid4()).upper(), "type": "video", "segments": []}
        tracks.insert(0, video_track)

    if "materials" not in draft:
        draft["materials"] = {}
    if "videos" not in draft["materials"]:
        draft["materials"]["videos"] = []

    canvas_w = draft.get("canvas_config", {}).get("width", 1920)
    canvas_h = draft.get("canvas_config", {}).get("height", 1080)

    existing_videos = draft["materials"]["videos"]
    new_video_segments = []

    for seg_i, item in enumerate(plan):
        spec = motion_for(item, by_num, by_name)
        if spec:
            motion_used += 1
            seg_keyframes = build_motion(spec["effect"], item["duration_us"], spec["strength"])
        else:
            seg_keyframes = build_motion(resolve_effect(effect, seg_i), item["duration_us"], zoom_strength)
        m_id = str(uuid.uuid4()).upper()
        s_id = str(uuid.uuid4()).upper()

        existing_videos.append({
            "id": m_id,
            "type": "photo",
            "material_name": item["file_name"],
            "path": item["file_path"],
            "duration": item["duration_us"],
            "width": canvas_w,
            "height": canvas_h
        })

        new_video_segments.append({
            "id": s_id,
            "material_id": m_id,
            "source_timerange": {"start": 0, "duration": item["duration_us"]},
            "target_timerange": {"start": item["start_us"], "duration": item["duration_us"]},
            "speed": 1.0,
            "volume": 1.0,
            "clip": {
                "alpha": 1.0,
                "flip": {"horizontal": False, "vertical": False},
                "rotation": 0.0,
                "scale": {"x": 1.0, "y": 1.0},
                "transform": {"x": 0.0, "y": 0.0}
            },
            "common_keyframes": seg_keyframes
        })

    video_track["segments"] = new_video_segments
    draft["tracks"] = tracks
    draft["duration"] = max(draft.get("duration", 0), project_duration)

    if audio_path and os.path.exists(audio_path):
        if "audios" not in draft["materials"]:
            draft["materials"]["audios"] = []
        a_mid = str(uuid.uuid4()).upper()
        a_sid = str(uuid.uuid4()).upper()
        draft["materials"]["audios"].append({
            "id": a_mid,
            "type": "audio",
            "material_name": os.path.basename(audio_path),
            "path": os.path.abspath(audio_path),
            "duration": project_duration
        })
        if not audio_track:
            audio_track = {"id": str(uuid.uuid4()).upper(), "type": "audio", "segments": []}
            tracks.append(audio_track)
        audio_track["segments"] = [{
            "id": a_sid,
            "material_id": a_mid,
            "source_timerange": {"start": 0, "duration": project_duration},
            "target_timerange": {"start": 0, "duration": project_duration},
            "speed": 1.0,
            "volume": 1.0
        }]

    with open(content_file, 'w', encoding='utf-8') as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    return len(new_video_segments), project_duration, motion_used, motion_warnings

@app.post("/api/sync-existing")
def sync_existing_route(req: SyncDraftRequest):
    root = (req.draft_root or "").strip() or DEFAULT_CAPCUT_PATH
    target = (req.draft_name or req.project_name or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="Please choose or type a target project name.")
    clips, duration, motion_used, motion_warnings = execute_sync(
        root, target, req.images_dir, req.srt_path, req.audio_path or "",
        req.effect or "none", req.zoom_strength or 0.15, (req.motion_path or "").strip())
    return {
        "status": "success",
        "draft_name": target,
        "clips_synced": clips,
        "total_duration": f"{duration / 1_000_000:.2f}s",
        "effect": req.effect,
        "motion_file_used": motion_used,
        "warnings": motion_warnings,
        "message": f"Successfully synced {clips} clips into project '{target}'! Open CapCut to view."
    }

@app.post("/api/build")
def build_route(req: SyncDraftRequest):
    return sync_existing_route(req)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)