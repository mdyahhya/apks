@echo off
TITLE Dev CRM - GitHub Release & APK Distribution Watcher
CLS
ECHO ====================================================================
ECHO   OFFLINE DEVELOPER CRM & GITHUB APK DISTRIBUTION SYSTEM
ECHO ====================================================================
ECHO.
ECHO [1/2] Checking Python environment...
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    ECHO [ERROR] Python is not installed or not added to PATH.
    PAUSE
    EXIT /B
)

ECHO [2/2] Launching Local Python Server & Watcher...
ECHO.
ECHO Dashboard URL: http://127.0.0.1:8765
ECHO Target APK:   C:\Users\DELL\Desktop\school_app\build\app\outputs\flutter-apk\app-release.apk
ECHO Provider:     GitHub Releases (mdyahhya/app-releases)
ECHO.
ECHO Opening Dashboard in your browser...
start http://127.0.0.1:8765
ECHO.
ECHO Server running! Press Ctrl+C in this window to stop.
ECHO ====================================================================
ECHO.

python run.py
PAUSE
