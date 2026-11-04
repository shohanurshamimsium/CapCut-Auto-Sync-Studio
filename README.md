# CapCut Auto Sync Studio

Auto sync tool for CapCut, with a simple web interface you run locally on your PC.

## Features

- Automatically syncs your media for CapCut projects
- Simple browser-based interface (served from the `static` folder)
- One-click launch on Windows with `run.bat`
- Lightweight Python app with minimal dependencies

> Edit this list to match exactly what your app does.

## Requirements

- Windows 10/11
- [Python 3.9+](https://www.python.org/downloads/) (tick **Add Python to PATH** during install)
- [CapCut](https://www.capcut.com/) installed (if your workflow needs it)

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/shohanurshamimsium/CapCut-Auto-Sync-Studio.git
   cd CapCut-Auto-Sync-Studio
   ```

2. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

**Quick start (Windows):** double-click `run.bat`.

**Or run manually:**

```bash
python app.py
```

Then open the address shown in the terminal (usually `http://127.0.0.1:5000`) in your browser.

## Project Structure

```
CapCut-Auto-Sync-Studio/
├── static/            # Front-end files (HTML, CSS, JS)
├── app.py             # Main application
├── requirements.txt   # Python dependencies
├── run.bat            # Windows launcher
└── .gitignore
```

## Troubleshooting

- **`python` is not recognized:** reinstall Python and make sure "Add Python to PATH" is ticked.
- **Missing module errors:** run `pip install -r requirements.txt` again.
- **Page won't load:** check the terminal for the correct address and port.

## Contributing

Issues and pull requests are welcome. For major changes, please open an issue first to discuss what you'd like to change.

## Author

Made by [shohanurshamimsium](https://github.com/shohanurshamimsium)

## License

No license has been added yet. Consider adding one (for example MIT) if you want others to be able to reuse your code.