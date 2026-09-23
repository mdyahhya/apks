# Offline Developer CRM & GitHub APK Distribution System

A lightweight, 100% offline local developer CRM and automated APK distribution pipeline.

## 🚀 Features

- **GitHub Releases Integration**: Automated binary upload to GitHub Releases (`mdyahhya/app-releases`). 100% Free, supports files up to 2 GB, no credit card required.
- **Automatic PC APK Watcher**: Monitors `C:\Users\DELL\Desktop\school_app\build\app\outputs\flutter-apk\app-release.apk` every 2 seconds.
- **Smart Compiler Lock & Stability Protection**: Detects when Flutter is actively compiling and waits until file size stabilizes.
- **Offline QR Code Generator**: Generates instant QR codes on your CRM dashboard so you can scan with your phone and install the latest build.
- **Chronological Version History**: Displays all builds with **Latest First**, formatted date and time (`15 Aug 2026, 02:25 PM`), file size in MB, and direct download links.

## 🛠️ How to Start the System

Open Command Prompt or PowerShell in `C:\Users\DELL\Desktop\App QR Software` and run:

```cmd
python backend/server.py
```

Or simply double-click **`start.bat`**.

Then open your browser to:
👉 **`http://127.0.0.1:8765`**
