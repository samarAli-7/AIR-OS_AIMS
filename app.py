
import cv2
import numpy as np
import json
import base64
import os
import sys
import time
import threading
import pickle
import ctypes
import logging
import urllib.request
from pathlib import Path
from collections import deque, Counter
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score


from mediapipe.tasks.python.vision.hand_landmarker import (
    HandLandmarker, HandLandmarkerOptions, HandLandmarkerResult,
    HandLandmarksConnections,
)
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision.core.vision_task_running_mode import VisionTaskRunningMode
from mediapipe.tasks.python.vision.core.image import Image as MpImage, ImageFormat


try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_OK = True
except ImportError:
    PYAUTOGUI_OK = False
    print("[WARN] pyautogui not installed")

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
    PYCAW_OK = True
except ImportError:
    PYCAW_OK = False
    print("[WARN] pycaw not installed")

try:
    import screen_brightness_control as sbc
    SBC_OK = True
except ImportError:
    SBC_OK = False
    print("[WARN] screen-brightness-control not installed")

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'gestureos_win_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

BASE_DIR     = Path(__file__).parent
MODEL_PATH   = BASE_DIR / "models" / "gesture_model.pkl"
DATA_PATH    = BASE_DIR / "data" / "gesture_data.json"
ACTIONS_PATH = BASE_DIR / "data" / "custom_actions.json"
TASK_PATH    = BASE_DIR / "models" / "hand_landmarker.task"


TASK_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"


HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),       # thumb
    (0,5),(5,6),(6,7),(7,8),       # index
    (0,9),(9,10),(10,11),(11,12),  # middle
    (0,13),(13,14),(14,15),(15,16),# ring
    (0,17),(17,18),(18,19),(19,20),# pinky
    (5,9),(9,13),(13,17),          # palm
]


class AppState:
    def __init__(self):
        self.camera_active = False
        self.cap = None
        self.lock = threading.Lock()
        self.classifier = None
        self.label_encoder = LabelEncoder()
        self.gesture_data = {}
        self.recording = False
        self.recording_name = ""
        self.recording_landmarks = []
        self.prediction_history = deque(maxlen=12)
        self.last_action_time = {}
        self.action_cooldown = 1.5
        self.model_trained = False
        self.fps = 0.0
        self.frame_count = 0
        self.fps_start = time.time()
        self.custom_gesture_actions = {}
        self.task_model_ready = False

    def load(self):
        if MODEL_PATH.exists():
            with open(MODEL_PATH, 'rb') as f:
                saved = pickle.load(f)
                self.classifier   = saved['classifier']
                self.label_encoder = saved['label_encoder']
                self.model_trained = True
                logger.info("Gesture model loaded")
        if DATA_PATH.exists():
            with open(DATA_PATH) as f:
                self.gesture_data = json.load(f)
        if ACTIONS_PATH.exists():
            with open(ACTIONS_PATH) as f:
                self.custom_gesture_actions = json.load(f)
        self.task_model_ready = TASK_PATH.exists()

    def save(self):
        MODEL_PATH.parent.mkdir(exist_ok=True)
        DATA_PATH.parent.mkdir(exist_ok=True)
        if self.classifier:
            with open(MODEL_PATH, 'wb') as f:
                pickle.dump({'classifier': self.classifier,
                             'label_encoder': self.label_encoder}, f)
        with open(DATA_PATH, 'w') as f:
            json.dump(self.gesture_data, f)
        with open(ACTIONS_PATH, 'w') as f:
            json.dump(self.custom_gesture_actions, f)

state = AppState()

def download_task_model():
   
    if TASK_PATH.exists():
        state.task_model_ready = True
        return True
    TASK_PATH.parent.mkdir(exist_ok=True)
    logger.info(f"Downloading hand_landmarker.task model...")
    socketio.emit('notification', {
        'msg': ' Downloading hand landmark model (~5MB)...',
        'type': 'info'
    })
    try:
        def _progress(count, block_size, total_size):
            pct = int(count * block_size * 100 / total_size)
            if pct % 20 == 0:
                logger.info(f"  Download: {pct}%")
        urllib.request.urlretrieve(TASK_MODEL_URL, TASK_PATH, _progress)
        state.task_model_ready = True
        socketio.emit('notification', {
            'msg': ' Model downloaded! Camera is ready.',
            'type': 'success'
        })
        logger.info("hand_landmarker.task downloaded OK")
        return True
    except Exception as e:
        logger.error(f"Model download failed: {e}")
        socketio.emit('notification', {
            'msg': f' Model download failed: {e}',
            'type': 'error'
        })
        return False


def _predownload():
    time.sleep(1)
    download_task_model()

threading.Thread(target=_predownload, daemon=True).start()
state.load()

KEYEVENTF_KEYUP = 0x0002

def _press_vk(vk_code):
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)

class WindowsController:

    @staticmethod
    def _vol():
        if not PYCAW_OK: return None
        try:
            devices = AudioUtilities.GetSpeakers()
            iface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))
        except Exception: return None

    @staticmethod
    def volume_up():
        v = WindowsController._vol()
        if v:
            try: v.SetMasterVolumeLevelScalar(min(1.0, v.GetMasterVolumeLevelScalar()+0.05), None); return
            except Exception: pass
        _press_vk(0xAF)

    @staticmethod
    def volume_down():
        v = WindowsController._vol()
        if v:
            try: v.SetMasterVolumeLevelScalar(max(0.0, v.GetMasterVolumeLevelScalar()-0.05), None); return
            except Exception: pass
        _press_vk(0xAE)

    @staticmethod
    def volume_mute():
        v = WindowsController._vol()
        if v:
            try: v.SetMute(not v.GetMute(), None); return
            except Exception: pass
        _press_vk(0xAD)

    @staticmethod
    def brightness_up():
        if SBC_OK:
            try:
                for m in sbc.list_monitors():
                    sbc.set_brightness(min(100, sbc.get_brightness(display=m)[0]+10), display=m)
                return
            except Exception: pass
        if PYAUTOGUI_OK: pyautogui.hotkey('win', 'a')

    @staticmethod
    def brightness_down():
        if SBC_OK:
            try:
                for m in sbc.list_monitors():
                    sbc.set_brightness(max(0, sbc.get_brightness(display=m)[0]-10), display=m)
                return
            except Exception: pass
        if PYAUTOGUI_OK: pyautogui.hotkey('win', 'a')

    @staticmethod
    def screenshot():
        ts = int(time.time())
        path = Path.home() / "Desktop" / f"gesture_screenshot_{ts}.png"
        try:
            if PYAUTOGUI_OK:
                pyautogui.screenshot().save(str(path))
                socketio.emit('notification', {'msg': f'Screenshot saved: {path.name}', 'type': 'success'})
            else:
                ctypes.windll.user32.keybd_event(0x5B,0,0,0)
                ctypes.windll.user32.keybd_event(0x2C,0,0,0)
                time.sleep(0.1)
                ctypes.windll.user32.keybd_event(0x2C,0,KEYEVENTF_KEYUP,0)
                ctypes.windll.user32.keybd_event(0x5B,0,KEYEVENTF_KEYUP,0)
                socketio.emit('notification', {'msg': 'Screenshot via Win+PrtSc', 'type': 'success'})
        except Exception as e:
            socketio.emit('notification', {'msg': f'Screenshot failed: {e}', 'type': 'error'})

    @staticmethod
    def _move(dx, dy):
        if PYAUTOGUI_OK: pyautogui.moveRel(dx, dy, duration=0.05)
        else:
            class PT(ctypes.Structure): _fields_=[("x",ctypes.c_long),("y",ctypes.c_long)]
            pt=PT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            ctypes.windll.user32.SetCursorPos(pt.x+dx, pt.y+dy)

    @staticmethod
    def cursor_left():  WindowsController._move(-60, 0)
    @staticmethod
    def cursor_right(): WindowsController._move(60, 0)
    @staticmethod
    def cursor_up():    WindowsController._move(0, -60)
    @staticmethod
    def cursor_down():  WindowsController._move(0, 60)

    @staticmethod
    def left_click():
        if PYAUTOGUI_OK: pyautogui.click()
        else:
            ctypes.windll.user32.mouse_event(0x0002,0,0,0,0)
            time.sleep(0.05)
            ctypes.windll.user32.mouse_event(0x0004,0,0,0,0)

    @staticmethod
    def right_click():
        if PYAUTOGUI_OK: pyautogui.rightClick()
        else:
            ctypes.windll.user32.mouse_event(0x0008,0,0,0,0)
            time.sleep(0.05)
            ctypes.windll.user32.mouse_event(0x0010,0,0,0,0)

    @staticmethod
    def double_click():
        if PYAUTOGUI_OK: pyautogui.doubleClick()

    @staticmethod
    def scroll_up():
        if PYAUTOGUI_OK: pyautogui.scroll(3)
        else: ctypes.windll.user32.mouse_event(0x0800,0,0,360,0)

    @staticmethod
    def scroll_down():
        if PYAUTOGUI_OK: pyautogui.scroll(-3)
        else: ctypes.windll.user32.mouse_event(0x0800,0,0,ctypes.c_ulong(-360).value,0)

    @staticmethod
    def media_play_pause(): _press_vk(0xB3)
    @staticmethod
    def media_next(): _press_vk(0xB0)
    @staticmethod
    def media_prev(): _press_vk(0xB1)

    @staticmethod
    def minimize_window():
        if PYAUTOGUI_OK: pyautogui.hotkey('win', 'd')
    @staticmethod
    def switch_window():
        if PYAUTOGUI_OK: pyautogui.hotkey('alt', 'tab')
    @staticmethod
    def close_window():
        if PYAUTOGUI_OK: pyautogui.hotkey('alt', 'f4')
    @staticmethod
    def zoom_in():
        if PYAUTOGUI_OK: pyautogui.hotkey('ctrl', '+')
    @staticmethod
    def zoom_out():
        if PYAUTOGUI_OK: pyautogui.hotkey('ctrl', '-')

# ── Action Registry ─────────────────────────────────────────────────────────
ACTION_MAP = {
    "volume_up":        WindowsController.volume_up,
    "volume_down":      WindowsController.volume_down,
    "volume_mute":      WindowsController.volume_mute,
    "brightness_up":    WindowsController.brightness_up,
    "brightness_down":  WindowsController.brightness_down,
    "screenshot":       WindowsController.screenshot,
    "cursor_left":      WindowsController.cursor_left,
    "cursor_right":     WindowsController.cursor_right,
    "cursor_up":        WindowsController.cursor_up,
    "cursor_down":      WindowsController.cursor_down,
    "left_click":       WindowsController.left_click,
    "right_click":      WindowsController.right_click,
    "double_click":     WindowsController.double_click,
    "scroll_up":        WindowsController.scroll_up,
    "scroll_down":      WindowsController.scroll_down,
    "media_play_pause": WindowsController.media_play_pause,
    "media_next":       WindowsController.media_next,
    "media_prev":       WindowsController.media_prev,
    "minimize_window":  WindowsController.minimize_window,
    "switch_window":    WindowsController.switch_window,
    "close_window":     WindowsController.close_window,
    "zoom_in":          WindowsController.zoom_in,
    "zoom_out":         WindowsController.zoom_out,
}

ACTION_LABELS = {
    "volume_up":"Volume Up","volume_down":"Volume Down","volume_mute":"Mute Toggle",
    "brightness_up":"Brightness Up","brightness_down":"Brightness Down",
    "screenshot":"Screenshot",
    "cursor_left":"Cursor Left","cursor_right":"Cursor Right",
    "cursor_up":"Cursor Up","cursor_down":"Cursor Down",
    "left_click":"Left Click","right_click":"Right Click","double_click":"Double Click",
    "scroll_up":"Scroll Up","scroll_down":"Scroll Down",
    "media_play_pause":"Play/Pause","media_next":"Next Track","media_prev":"Prev Track",
    "minimize_window":"Show Desktop","switch_window":"Alt+Tab",
    "close_window":"Close Window","zoom_in":"Zoom In","zoom_out":"Zoom Out",
}

ACTION_ICONS = {
    "volume_up":"🔊","volume_down":"🔉","volume_mute":"🔇",
    "brightness_up":"☀️","brightness_down":"🌙","screenshot":"📸",
    "cursor_left":"⬅️","cursor_right":"➡️","cursor_up":"⬆️","cursor_down":"⬇️",
    "left_click":"👆","right_click":"👉","double_click":"👆👆",
    "scroll_up":"⏫","scroll_down":"⏬",
    "media_play_pause":"⏯️","media_next":"⏭️","media_prev":"⏮️",
    "minimize_window":"🗕","switch_window":"⬛","close_window":"✖️",
    "zoom_in":"🔍+","zoom_out":"🔍-",
}

def landmarks_to_features(landmarks):
    """
    Convert 21 NormalizedLandmark objects → 63-dim normalized feature vector.
    landmarks: list of objects with .x .y .z attributes
    """
    wrist = landmarks[0]
    palm_size = np.sqrt(
        (landmarks[9].x - wrist.x)**2 +
        (landmarks[9].y - wrist.y)**2 +
        (landmarks[9].z - wrist.z)**2
    )
    if palm_size < 1e-6:
        palm_size = 1.0
    features = []
    for pt in landmarks:
        features.extend([
            (pt.x - wrist.x) / palm_size,
            (pt.y - wrist.y) / palm_size,
            (pt.z - wrist.z) / palm_size,
        ])
    return features  # 63 values

def draw_landmarks_cv2(frame, landmarks, h, w):

    pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
    # Draw connections
    for (a, b) in HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (0, 220, 100), 2)
    # Draw landmark dots
    for i, (x, y) in enumerate(pts):
        color = (0, 255, 136) if i == 0 else (255, 255, 255)
        cv2.circle(frame, (x, y), 4, color, -1)
        cv2.circle(frame, (x, y), 4, (0, 180, 80), 1)

def execute_action(gesture_name):
    action = state.custom_gesture_actions.get(gesture_name)
    if action and action in ACTION_MAP:
        try:
            ACTION_MAP[action]()
            socketio.emit('action_fired', {
                'gesture': gesture_name,
                'action':  action,
                'label':   ACTION_LABELS.get(action, action),
                'icon':    ACTION_ICONS.get(action, '⚡'),
                'ts':      int(time.time()),
            })
            logger.info(f"{gesture_name} → {action}")
        except Exception as e:
            logger.error(f"Action error ({action}): {e}")


def camera_thread():
    if not state.task_model_ready:
        if not download_task_model():
            socketio.emit('notification',
                {'msg': ' Cannot start camera: model download failed', 'type': 'error'})
            state.camera_active = False
            return

    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(TASK_PATH)),
        running_mode=VisionTaskRunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    landmarker = HandLandmarker.create_from_options(options)
    logger.info("Camera thread started (Tasks API)")

    start_ms = int(time.time() * 1000)

    while state.camera_active:
        if state.cap is None or not state.cap.isOpened():
            time.sleep(0.05)
            continue

        ret, frame = state.cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]

        # FPS
        state.frame_count += 1
        elapsed = time.time() - state.fps_start
        if elapsed >= 1.0:
            state.fps = state.frame_count / elapsed
            state.frame_count = 0
            state.fps_start = time.time()

        # Convert BGR→RGB for mediapipe
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = MpImage(image_format=ImageFormat.SRGB, data=rgb)
        timestamp_ms = int(time.time() * 1000) - start_ms

        # Detect
        result = landmarker.detect_for_video(mp_image, timestamp_ms)

        gesture_name = "No Hand"
        confidence   = 0.0
        features     = None

        if result.hand_landmarks:
            landmarks = result.hand_landmarks[0]  # first hand
            draw_landmarks_cv2(frame, landmarks, h, w)
            features = landmarks_to_features(landmarks)

            # Recording
            if state.recording and features:
                state.recording_landmarks.append(features)
                cv2.rectangle(frame, (0,0), (w-1,h-1), (0,0,220), 8)
                cv2.putText(frame,
                    f"  REC [{state.recording_name}]  {len(state.recording_landmarks)} samples",
                    (10,35), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0,0,220), 2)

            # Inference
            if state.model_trained and state.classifier and not state.recording and features:
                X     = np.array([features])
                pred  = state.classifier.predict(X)[0]
                proba = state.classifier.predict_proba(X)[0]
                confidence   = float(np.max(proba))
                gesture_name = state.label_encoder.inverse_transform([pred])[0]

                state.prediction_history.append((gesture_name, confidence))
                if len(state.prediction_history) >= 7:
                    recent = [g for g,c in state.prediction_history]
                    counts = Counter(recent)
                    top, top_n = counts.most_common(1)[0]
                    if top_n >= 5 and confidence > 0.65:
                        gesture_name = top
                        now = time.time()
                        if now - state.last_action_time.get(gesture_name, 0) > state.action_cooldown:
                            state.last_action_time[gesture_name] = now
                            threading.Thread(target=execute_action,
                                             args=(gesture_name,), daemon=True).start()

        # Overlay
        if features:
            c = (0,255,136) if confidence>0.70 else (0,200,255) if confidence>0.50 else (180,180,180)
            cv2.rectangle(frame, (0,h-70), (w,h), (0,0,0), -1)
            cv2.putText(frame, gesture_name, (12,h-38), cv2.FONT_HERSHEY_SIMPLEX, 1.0, c, 2)
            cv2.rectangle(frame, (0,h-12), (int(w*confidence),h), c, -1)

        cv2.putText(frame, f"FPS {state.fps:.0f}", (w-88,22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180,180,180), 1)

        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
        b64 = base64.b64encode(buf).decode('utf-8')
        socketio.emit('frame', {
            'image':          b64,
            'gesture':        gesture_name,
            'confidence':     round(confidence*100, 1),
            'fps':            round(state.fps, 1),
            'recording':      state.recording,
            'recording_name': state.recording_name,
            'samples':        len(state.recording_landmarks) if state.recording else 0,
        })

    landmarker.close()
    logger.info("Camera thread stopped")


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    return jsonify({
        'camera_active':    state.camera_active,
        'model_trained':    state.model_trained,
        'gesture_count':    len(state.gesture_data),
        'gestures':         list(state.gesture_data.keys()),
        'custom_actions':   state.custom_gesture_actions,
        'action_labels':    ACTION_LABELS,
        'action_icons':     ACTION_ICONS,
        'actions':          list(ACTION_MAP.keys()),
        'task_model_ready': state.task_model_ready,
        'capabilities': {
            'pyautogui':   PYAUTOGUI_OK,
            'pycaw':       PYCAW_OK,
            'brightness':  SBC_OK,
        }
    })

@app.route('/api/camera/toggle', methods=['POST'])
def toggle_camera():
    with state.lock:
        if state.camera_active:
            state.camera_active = False
            time.sleep(0.5)
            if state.cap:
                state.cap.release()
                state.cap = None
            return jsonify({'camera_active': False, 'status': 'stopped'})
        else:
            if not state.task_model_ready and not download_task_model():
                return jsonify({'error': 'Hand landmark model not available. Check internet connection.', 'camera_active': False}), 500

            cap = None
            for idx in range(4):
                c = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if c.isOpened():
                    cap = c; break
                c.release()
            if cap is None:
                return jsonify({'error': 'No camera detected. Check Device Manager.', 'camera_active': False}), 500

            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            state.cap = cap
            state.camera_active = True
            threading.Thread(target=camera_thread, daemon=True).start()
            return jsonify({'camera_active': True, 'status': 'started'})

@app.route('/api/recording/start', methods=['POST'])
def start_recording():
    data = request.json or {}
    name = data.get('name','').strip().lower().replace(' ','_')
    if not name:
        return jsonify({'error': 'Gesture name required'}), 400
    if not state.camera_active:
        return jsonify({'error': 'Start camera first'}), 400
    state.recording = True
    state.recording_name = name
    state.recording_landmarks = []
    socketio.emit('notification', {'msg': f'Recording "{name}" — hold your gesture!', 'type': 'warning'})
    return jsonify({'status': 'recording', 'name': name})

@app.route('/api/recording/stop', methods=['POST'])
def stop_recording():
    if not state.recording:
        return jsonify({'error': 'Not recording'}), 400
    state.recording = False
    name = state.recording_name
    landmarks = list(state.recording_landmarks)
    state.recording_landmarks = []
    if len(landmarks) < 15:
        return jsonify({'error': f'Only {len(landmarks)} samples — hold gesture longer (need 15+)'}), 400
    state.gesture_data.setdefault(name, [])
    state.gesture_data[name].extend(landmarks)
    state.save()
    total = len(state.gesture_data[name])
    socketio.emit('notification', {
        'msg': f'Saved {len(landmarks)} samples for "{name}" (total: {total})',
        'type': 'success'
    })
    return jsonify({'status':'saved','name':name,'samples':len(landmarks),'total':total,
                    'all_gestures':list(state.gesture_data.keys())})

@app.route('/api/gesture/delete', methods=['POST'])
def delete_gesture():
    data = request.json or {}
    name = data.get('name')
    state.gesture_data.pop(name, None)
    state.custom_gesture_actions.pop(name, None)
    state.save()
    return jsonify({'status':'deleted','gestures':list(state.gesture_data.keys())})

@app.route('/api/gesture/assign_action', methods=['POST'])
def assign_action():
    data = request.json or {}
    gesture = data.get('gesture')
    action  = data.get('action')
    if not gesture or not action: return jsonify({'error':'gesture and action required'}),400
    if action not in ACTION_MAP: return jsonify({'error':f'Unknown action: {action}'}),400
    state.custom_gesture_actions[gesture] = action
    state.save()
    return jsonify({'status':'assigned','gesture':gesture,'action':action})

@app.route('/api/gesture/list')
def list_gestures():
    return jsonify({
        'gestures':      {n:len(v) for n,v in state.gesture_data.items()},
        'custom_actions': state.custom_gesture_actions,
    })

@app.route('/api/train', methods=['POST'])
def train_model():
    if len(state.gesture_data) < 2:
        return jsonify({'error':'Need at least 2 different gestures'}),400
    X, y = [], []
    for name, samples in state.gesture_data.items():
        for s in samples:
            X.append(s); y.append(name)
    X = np.array(X)
    y_enc = state.label_encoder.fit_transform(y)
    if len(X) < 30:
        return jsonify({'error':f'Only {len(X)} samples — need 30+ total'}),400

    def do_train():
        socketio.emit('training_status', {'status':'training','msg':'Training Random Forest...'})
        try:
            X_tr,X_te,y_tr,y_te = train_test_split(X,y_enc,test_size=0.2,random_state=42,stratify=y_enc)
            clf = RandomForestClassifier(n_estimators=300,class_weight='balanced',random_state=42,n_jobs=-1)
            clf.fit(X_tr, y_tr)
            acc = accuracy_score(y_te, clf.predict(X_te))
            state.classifier    = clf
            state.model_trained = True
            state.save()
            socketio.emit('training_status', {
                'status':'done','accuracy':round(acc*100,1),
                'classes':state.label_encoder.classes_.tolist(),
                'samples':len(X),
                'msg':f'Done! Accuracy: {acc*100:.1f}% on {len(X_te)} test samples',
            })
        except Exception as e:
            socketio.emit('training_status', {'status':'error','msg':str(e)})

    threading.Thread(target=do_train, daemon=True).start()
    return jsonify({'status':'training_started'})

@app.route('/api/action/test', methods=['POST'])
def test_action():
    data = request.json or {}
    action = data.get('action')
    if action not in ACTION_MAP: return jsonify({'error':f'Unknown action: {action}'}),400
    threading.Thread(target=ACTION_MAP[action], daemon=True).start()
    return jsonify({'status':'fired','action':action})


@socketio.on('connect')
def on_connect():
    emit('connected', {'msg': 'GestureOS connected'})
    emit('status_update', {
        'camera_active':    state.camera_active,
        'model_trained':    state.model_trained,
        'gesture_count':    len(state.gesture_data),
        'task_model_ready': state.task_model_ready,
    })


if __name__ == '__main__':
    (BASE_DIR/'models').mkdir(exist_ok=True)
    (BASE_DIR/'data').mkdir(exist_ok=True)

    print("=" * 52)
    print("  GestureOS  —  Windows Edition (mediapipe 0.10.x)")
    print("=" * 52)
    print(f"  pyautogui  : {'OK' if PYAUTOGUI_OK else 'MISSING  pip install pyautogui'}")
    print(f"  pycaw      : {'OK' if PYCAW_OK    else 'MISSING  pip install pycaw'}")
    print(f"  brightness : {'OK' if SBC_OK      else 'MISSING  pip install screen-brightness-control'}")
    print(f"  task model : {'OK' if TASK_PATH.exists() else 'Will download on first camera start (~5MB)'}")
    print()
    print("  http://localhost:5000")
    print("=" * 52)

    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
