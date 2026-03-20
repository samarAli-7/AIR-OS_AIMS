# GestureOS — Windows Edition

Control your Windows PC with hand gestures using your webcam and deep learning.

---

## Quick Start (Windows)

### 1. Install Python (if not already)
Download from https://python.org — check **"Add Python to PATH"** during install.

### 2. Install dependencies
Open a Command Prompt in this folder and run:

```bat
pip install flask flask-socketio opencv-python mediapipe scikit-learn eventlet pyautogui pycaw comtypes screen-brightness-control Pillow
```

Or just **double-click `start.bat`** — it installs everything automatically.

### 3. Run
Double-click **`start.bat`**, or in Command Prompt:
```bat
python app.py
```

### 4. Open browser
Go to **http://localhost:5000**

---

## How to Use

### Step 1 — Record Gestures
1. Click **START CAMERA** — your webcam turns on
2. Type a gesture name (e.g. `thumbs_up`, `open_palm`, `fist`)
3. Click **⏺ START REC** — show that gesture to the camera
4. Hold it steady for 3–5 seconds (captures ~90–150 samples)
5. Click **⏹ STOP REC**
6. Repeat for each gesture — need **at least 2**

### Step 2 — Train
Click **⚡ TRAIN** in the Gesture Library panel.
Training takes ~2 seconds. Accuracy is shown when done.

### Step 3 — Assign Actions
Click **⚡** next to any gesture → pick a system action from the dropdown → **ASSIGN**.
Use **▶ TEST** in the dialog to fire the action immediately and confirm it works.

### Step 4 — Control
With camera on and model trained, perform gestures — the system fires actions automatically.

---

## Supported Actions (23 total)

| Category    | Actions                                                   |
|-------------|-----------------------------------------------------------|
| Volume      | Volume Up/Down/Mute                                       |
| Brightness  | Brightness Up/Down                                        |
| Screenshot  | Screenshot → saved to Desktop                             |
| Cursor      | Move Left / Right / Up / Down                             |
| Click       | Left Click / Right Click / Double Click                   |
| Scroll      | Scroll Up / Scroll Down                                   |
| Media       | Play/Pause / Next Track / Previous Track                  |
| Window      | Show Desktop / Alt+Tab / Close Window / Zoom In / Zoom Out|

---

## Dependencies Explained

| Package                   | Purpose                                          |
|---------------------------|--------------------------------------------------|
| `flask` + `flask-socketio`| Web server + real-time WebSocket communication   |
| `opencv-python`           | Camera capture, frame processing                  |
| `mediapipe`               | Hand landmark detection (21 points per hand)      |
| `scikit-learn`            | Random Forest classifier for gesture recognition  |
| `pyautogui`               | Cursor movement, mouse clicks, scrolling, hotkeys |
| `pycaw`                   | Windows Core Audio API — precise volume control   |
| `screen-brightness-control`| Monitor brightness control via WMI               |
| `comtypes`                | COM interface (required by pycaw)                 |
| `Pillow`                  | Screenshot capture via pyautogui                  |
| `eventlet`                | Async socket handling for flask-socketio          |

All features work even if pycaw or screen-brightness-control aren't installed — they fall back to Windows virtual key presses.

---

## How the ML Works

```
Webcam frame (640×480)
    ↓
MediaPipe Hands — detects 21 landmarks (x, y, z per point)
    ↓
Feature extraction — normalize to wrist, scale by palm size → 63-dim vector
    ↓
Random Forest (300 trees) — predict gesture + confidence score
    ↓
10-frame smoothing — gesture must appear in 5/10 recent frames + conf > 65%
    ↓
Action cooldown (1.5s) — prevents repeated firing of same gesture
    ↓
System action via pyautogui / pycaw / ctypes
```

## File Structure

```
gesture_app/
├── app.py                  # Flask server + ML + Windows system control
├── templates/
│   └── index.html          # Web UI
├── models/
│   └── gesture_model.pkl   # Trained model (auto-created after training)
├── data/
│   ├── gesture_data.json   # Recorded landmark samples
│   └── custom_actions.json # Gesture → action mapping
├── requirements.txt
├── start.bat               # Windows one-click startup
└── README.md
```

## Tips for Best Accuracy

- Record **40–80+ samples** per gesture (hold gesture for 3–5 seconds)
- Record each gesture **3 times** (re-record with slight angle variations)
- Use **good lighting** — avoid backlit environments
- Keep gestures **distinctly different** from each other
- After recording more samples, click **TRAIN** again to retrain

## Troubleshooting

| Problem | Fix |
|---|---|
| Camera not found | Check Device Manager → Cameras; try unplugging and replugging |
| Volume action doesn't work | `pip install pycaw comtypes` |
| Brightness doesn't work | `pip install screen-brightness-control` — note: WMI brightness only works on laptops with supported drivers |
| Cursor not moving | `pip install pyautogui` |
| Low accuracy | Record more samples; make gestures more distinct |
| Actions firing too fast | Increase `action_cooldown` in `app.py` (default: 1.5s) |
