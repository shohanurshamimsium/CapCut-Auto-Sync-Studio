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
    
    total_duration_us = plan[-1]["end_us"] if plan else 0
    preview_rows = []
    for item in plan:
        preview_rows.append({
            "image_idx": item["image_idx"],
            "file_name": item["file_name"],
            "start": format_us(item["start_us"]),
            "end": format_us(item["end_us"]),
            "duration": f"{item['duration_us'] / 1_000_000:.2f}s",
            "narration": item["narration"]
        })
        
    return {
        "status": "success",
        "srt_cues_count": len(cues),
        "images_found": len(images),
        "total_matched": len(plan),
        "total_duration": format_us(total_duration_us),
        "plan_preview": preview_rows
    }

def execute_sync(draft_root: str, target_name: str, images_dir: str, srt_path: str, audio_path: str = ""):
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
        # Check if 1103 exists to copy structure
        template_p = os.path.join(draft_root, "1103", "draft_content.json")
        if os.path.exists(template_p):
            with open(template_p, 'r', encoding='utf-8') as f:
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

    for item in plan:
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
            "volume": 1.0
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

    return len(new_video_segments), project_duration

@app.post("/api/sync-existing")
def sync_existing_route(req: SyncDraftRequest):
    root = (req.draft_root or "").strip() or DEFAULT_CAPCUT_PATH
    target = req.draft_name or req.project_name or "1103"
    clips, duration = execute_sync(root, target, req.images_dir, req.srt_path, req.audio_path or "")
    return {
        "status": "success",
        "draft_name": target,
        "clips_synced": clips,
        "total_duration": f"{duration / 1_000_000:.2f}s",
        "message": f"Successfully synced {clips} clips into project '{target}'! Open CapCut to view."
    }

@app.post("/api/build")
def build_route(req: SyncDraftRequest):
    return sync_existing_route(req)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
