@echo off
title GestureOS — Windows Hand Gesture Control
cls

echo ====================================================
echo   GestureOS  ^|  Windows Edition
echo ====================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from python.org
    pause
    exit /b 1
)

echo [OK] Python found
echo.
echo [*] Installing / verifying dependencies...
echo.

pip install flask flask-socketio opencv-python mediapipe scikit-learn eventlet pyautogui pycaw comtypes screen-brightness-control Pillow -q

echo.
echo [OK] Dependencies ready
echo.

:: Create required directories
if not exist models mkdir models
if not exist data mkdir data
if not exist recordings mkdir recordings

echo ====================================================
echo   Starting GestureOS at http://localhost:5000
echo ====================================================
echo.
echo   Open your browser and go to:
echo   http://localhost:5000
echo.
echo   Press Ctrl+C to stop the server
echo.

python app.py

pause
