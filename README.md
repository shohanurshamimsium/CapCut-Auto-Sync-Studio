# CapCut Auto Sync Studio

A small local web app that automatically places your images on a CapCut timeline, timed to your narration, with optional zoom and pan motion. Give it a folder of numbered images and an `.srt` subtitle file (and optionally a voiceover and an AI-made motion file), and it writes the clips straight into a CapCut draft.

## Features

- **Auto timing from SRT:** each image is matched to a subtitle cue and given the right start time and duration
- **Smart image distribution:** if you have more images than subtitle cues, the extra images are split across the longest cues
- **Motion effects:** slow zoom in, zoom out, pan left/right, alternating zoom, or a random mix, with adjustable strength. They are added as native CapCut keyframes, so you can still edit them inside CapCut
- **AI motion file:** let an AI choose the effect for each image from your script, save it as `.json`, and load it into the app (see below)
- **Optional voiceover:** add an audio file (`.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`) and it is placed on the audio track
- **Preview before syncing:** "Analyze & Match Timing" shows the full plan (image, start, end, duration, effect, narration) before anything is written
- **Duplicate warnings:** if two images start with the same number, the app tells you which one is skipped
- **CapCut auto-detect:** finds your CapCut projects folder and lists existing drafts
- **Safe writes:** your existing `draft_content.json` is backed up to `draft_content.json.bak` before it is changed
- **Local only:** runs on your PC at `http://localhost:8765`, and nothing is uploaded

## Requirements

- Windows 10/11
- [Python 3.9+](https://www.python.org/downloads/) (tick **Add Python to PATH** during install)
- CapCut desktop installed

## Installation

```bash
git clone https://github.com/shohanurshamimsium/CapCut-Auto-Sync-Studio.git
cd CapCut-Auto-Sync-Studio
pip install -r requirements.txt
```

## Usage

**Quick start:** double-click `run.bat`. It installs the dependencies, opens your browser, and starts the app.

**Or run manually:**

```bash
python app.py
```

Then open [http://localhost:8765](http://localhost:8765).

### Step by step

1. **Close CapCut** before syncing, so it doesn't overwrite the draft.
2. **Choose your images folder.** File names should start with a number, e.g. `01.jpg`, `02_scene.png`, `03.webp`. The number decides the order. Supported formats: PNG, JPG, JPEG, WEBP, BMP.
3. **Choose your SRT file** (the subtitles or narration timing).
4. **Choose a voiceover** (optional).
5. **Choose a motion file** (optional, see below).
6. Click **Analyze & Match Timing** to preview the plan.
7. Choose a default **Image Motion Effect** and zoom strength. This is used for any image the motion file doesn't cover.
8. Pick the **target CapCut draft** from the list, or type a project name. Use **Auto Detect** to find your CapCut projects folder.
9. Click **Sync into Target Draft**, then open CapCut to see your timeline.

Default CapCut projects folder:

```
%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft
```

## Motion file (optional)

Instead of one effect for every image, give the app a JSON file that sets the effect per image. Ask an AI to generate it from your SRT and image list, save it as `.json`, then click **Choose Motion** in the app. See `example_motion.json`.

```json
[
  {"image": 1, "effect": "zoom_in",  "strength": 0.15},
  {"image": 2, "effect": "pan_left", "strength": 0.10},
  {"image": "03.jpg", "effect": "zoom_out", "strength": 0.20}
]
```

- `image`: the image number (`1` matches `01.jpg`) or the full file name
- `effect`: `zoom_in`, `zoom_out`, `pan_left`, `pan_right`, or `none`
- `strength`: optional, `0.05` to `0.6` (default `0.15`)
- Images not listed in the file use the dropdown effect. Invalid entries are skipped with a warning in the log.
- JSON wrapped in a markdown code fence (as AI tools often output) is accepted.

## Suggested workflow with AI tools

1. Write your script and make an `.srt` subtitle file (or export one from your voiceover).
2. Generate one image per scene and save them as `01.jpg`, `02.jpg`, `03.jpg` ... in script order. Every number must be unique.
3. (Optional) Give your SRT and image list to an AI and ask it for a motion file in the JSON format shown above.
4. Close CapCut, run the app, load your images, SRT, voiceover and motion file, then sync into a CapCut draft.
5. Open CapCut, review the timeline, and export.

## Limitations

- Only still images are supported (no video clips).
- Effects are keyframe-based (zoom and pan). CapCut Pro effects, transitions, filters and animations are not applied by this tool.
- Subtitles are used for timing only and are not added as caption text.
- Windows only (the file pickers and CapCut folder detection are built for Windows).

## How timing works

| Situation | Behavior |
|---|---|
| Images = subtitle cues | One image per cue, shown until the next cue starts |
| More images than cues | Every cue gets one image, and the extra images are given to the longest cues, splitting their time evenly |
| Voiceover added | Placed on the audio track from the start |

## Project structure

```
CapCut-Auto-Sync-Studio/
├── static/
│   └── index.html          # Web interface
├── app.py                  # FastAPI backend (SRT parsing, timing, motion, draft writing)
├── example_motion.json     # Sample motion file
├── requirements.txt        # fastapi, uvicorn, pandas
├── run.bat                 # Windows one-click launcher
└── .gitignore
```

## Troubleshooting

- **`python` is not recognized:** reinstall Python and tick "Add Python to PATH".
- **Page won't open:** go to `http://localhost:8765` manually and check the terminal for errors. Make sure nothing else is using port 8765.
- **No drafts listed:** CapCut may store projects elsewhere. Type your drafts folder into the "CapCut Projects Folder" field.
- **An image is missing from the timeline:** check the log for a "Duplicate number" warning. Two files starting with the same number can't both be used.
- **Motion doesn't show in CapCut:** fully close and reopen CapCut after syncing, and check the log for motion file warnings.
- **Something went wrong:** rename `draft_content.json.bak` back to `draft_content.json` in the draft folder.

## Notes

- This tool edits CapCut's draft files directly, which is not an official feature, so a CapCut update could change the draft format. Back up important projects first.
- Not affiliated with or endorsed by CapCut or ByteDance.

## Author

Made by [shohanurshamimsium](https://github.com/shohanurshamimsium)

## License

MIT License. See [LICENSE](LICENSE) for details.