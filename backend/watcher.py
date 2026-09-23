import os
import sys
import time
import json
import logging
import threading
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import config
from backend.apk_metadata import get_apk_metadata, is_file_locked, check_file_stability
from backend.r2_uploader import r2_uploader
from backend.github_uploader import github_uploader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Watcher")

BASE_DIR = Path(__file__).resolve().parent.parent


class APKWatcher:
    def __init__(self):
        self.running = False
        self.thread = None
        self.last_seen_sha256 = None
        self.last_seen_mtime = None
        self.auto_watch_enabled = True
        self.state = {
            "status": "idle",
            "auto_watch_enabled": True,
            "last_check_time": None,
            "current_apk": None,
            "upload_status": "none",
            "last_error": None,
            "logs": []
        }
        self.history = []
        self._load_state()

    def _get_project_files(self):
        project_id = config.active_project_id or "default"
        data_dir = BASE_DIR / "data"
        state_file = data_dir / f"state_{project_id}.json"
        history_file = data_dir / f"history_{project_id}.json"
        return state_file, history_file

    def reload_for_project(self):
        """Reload state and history when active project is switched."""
        self.last_seen_sha256 = None
        self.last_seen_mtime = None
        self.state["current_apk"] = None
        self.state["status"] = "idle"
        self.state["upload_status"] = "none"
        self.state["last_error"] = None
        self.history = []
        self._load_state()

        target_tag = config.get_project_release_tag()

        # Update legacy URLs in current_apk and history to project-specific release tag
        if self.state["current_apk"]:
            curr_url = self.state["current_apk"].get("download_url", "")
            if "/releases/download/latest/" in curr_url:
                self.state["current_apk"]["download_url"] = curr_url.replace("/releases/download/latest/", f"/releases/download/{target_tag}/")
        for h in self.history:
            h_url = h.get("download_url", "")
            if "/releases/download/latest/" in h_url:
                h["download_url"] = h_url.replace("/releases/download/latest/", f"/releases/download/{target_tag}/")

        # Auto-detect newest local file on disk if configured target_path does not exist
        target_path = Path(config.apk_file_path)
        if not target_path.exists():
            from backend.config import auto_detect_apk_path
            auto_path = auto_detect_apk_path(config.flutter_project_root)
            if auto_path and Path(auto_path).exists():
                config.apk_file_path = auto_path
                config.apk_filename = Path(auto_path).name
                target_path = Path(auto_path)

        if not self.state["current_apk"] and target_path.exists():
            try:
                meta = get_apk_metadata(target_path, config.flutter_project_root)
                if meta.get("exists"):
                    dl_url = config.get_public_download_url(meta.get("filename"), tag=target_tag)
                    ver = meta.get("version", "1.0.0")
                    bn = meta.get("build_number", "")
                    self.state["current_apk"] = {
                        "id": "build-local",
                        "project_id": config.active_project_id,
                        "project_name": config.project_name,
                        "filename": meta.get("filename"),
                        "version": ver,
                        "build_number": bn,
                        "version_label": f"v{ver} (Build {bn})" if bn else f"v{ver}",
                        "file_size_mb": meta.get("file_size_mb", 0.0),
                        "sha256": meta.get("sha256"),
                        "mtime_timestamp": meta.get("mtime_timestamp"),
                        "download_url": dl_url,
                        "provider": config.distribution_provider,
                        "build_time": meta.get("build_time"),
                        "file_modified_at": meta.get("file_modified_at"),
                        "uploaded_at": datetime.now().isoformat(),
                        "uploaded_at_formatted": meta.get("build_time") or "Local Build",
                        "is_latest": True
                    }
                    self.last_seen_sha256 = meta.get("sha256")
                    self.last_seen_mtime = meta.get("mtime_timestamp")
            except Exception as e:
                logger.warning(f"Could not auto-inspect local APK for {config.project_name}: {e}")


        self._log(f"Switched context to project '{config.project_name}' (Tag: {target_tag} | Target APK: {config.apk_file_path})")

    def _log(self, message: str, level: str = "INFO"):
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message
        }
        self.state["logs"].insert(0, entry)
        if len(self.state["logs"]) > 100:
            self.state["logs"].pop()
        logger.info(f"[{level}] {message}")

    def _load_state(self):
        try:
            state_file, history_file = self._get_project_files()
            if state_file.exists():
                with open(state_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.state["current_apk"] = saved.get("current_apk")
                    if self.state["current_apk"]:
                        self.last_seen_sha256 = self.state["current_apk"].get("sha256")
                        self.last_seen_mtime = self.state["current_apk"].get("mtime_timestamp")
            if history_file.exists():
                with open(history_file, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
                    # Sort history latest first
                    self.history.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
        except Exception as e:
            logger.error(f"Error loading state/history: {e}")

    def _save_state(self):
        try:
            state_file, history_file = self._get_project_files()
            state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump({
                    "current_apk": self.state["current_apk"],
                    "last_updated": datetime.now().isoformat()
                }, f, indent=2)

            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state/history: {e}")

    def add_to_history(self, record: dict):
        """Add new build record and keep history sorted newest first."""
        # Mark all old records as not latest
        for h in self.history:
            h["is_latest"] = False

        record["is_latest"] = True
        self.history.insert(0, record)
        # Keep maximum 50 builds history
        if len(self.history) > 50:
            self.history = self.history[:50]
        self._save_state()

    def trigger_upload(self, file_path: str, metadata: dict) -> bool:
        """Uploads APK to selected distribution provider (GitHub / R2)."""
        provider = config.distribution_provider
        metadata["github_release_tag"] = config.get_project_release_tag()
        metadata["project_name"] = config.project_name
        size_mb = metadata.get("file_size_mb", metadata.get("size_mb", 0.0))
        filename = metadata.get("filename", "app-release.apk")
        sha256 = metadata.get("sha256", "")
        mtime_ts = metadata.get("mtime_timestamp")
        version = metadata.get("version", "1.0.0")
        build_number = metadata.get("build_number", "")

        self._log(f"Starting upload using provider '{provider.upper()}' for {filename} ({size_mb} MB)...")
        self.state["upload_status"] = "uploading"

        if provider == "github":
            result = github_uploader.upload_apk(file_path, metadata)
        else:
            result = r2_uploader.upload_apk(file_path, metadata)

        if result.get("success"):
            download_url = result.get("download_url") or config.get_public_download_url()
            now_iso = datetime.now().isoformat()
            now_formatted = datetime.now().strftime("%d %b %Y, %I:%M %p")

            apk_record = {
                "id": f"build-{int(time.time())}",
                "project_id": config.active_project_id,
                "project_name": config.project_name,
                "filename": filename,
                "version": version,
                "build_number": build_number,
                "version_label": f"v{version} (Build {build_number})" if build_number else f"v{version}",
                "file_size_mb": size_mb,
                "sha256": sha256,
                "mtime_timestamp": mtime_ts,
                "download_url": download_url,
                "provider": provider,
                "build_time": metadata.get("build_time") or metadata.get("modified_at_formatted") or now_formatted,
                "file_modified_at": metadata.get("modified_at_formatted") or now_formatted,
                "uploaded_at": now_iso,
                "uploaded_at_formatted": now_formatted,
                "is_latest": True
            }

            self.state["current_apk"] = apk_record
            self.state["upload_status"] = "success"
            self.state["last_error"] = None
            self.last_seen_sha256 = sha256
            self.last_seen_mtime = mtime_ts

            self.add_to_history(apk_record)
            self._log(f"[SUCCESS] Upload completed successfully. Live URL: {download_url}", level="SUCCESS")
            return True
        else:
            error_msg = result.get("error", "Unknown upload error")
            self.state["upload_status"] = "failed"
            self.state["last_error"] = error_msg
            self.last_seen_sha256 = sha256
            self.last_seen_mtime = mtime_ts
            self._log(f"[ERROR] Upload failed: {error_msg}", level="ERROR")
            return False

    def check_once(self):
        """Single poll loop checking target APK."""
        target_path = Path(config.apk_file_path)
        self.state["last_check_time"] = datetime.now().strftime("%H:%M:%S")

        if not target_path.exists():
            from backend.config import auto_detect_apk_path
            auto_path = auto_detect_apk_path(config.flutter_project_root)
            if auto_path and Path(auto_path).exists():
                config.apk_file_path = auto_path
                config.apk_filename = Path(auto_path).name
                target_path = Path(auto_path)
            else:
                self.state["status"] = "waiting_for_file"
                return


        # 1. Check if Windows file lock active (Flutter compiler compiling)
        if is_file_locked(target_path):
            self.state["status"] = "building"
            self._log("Flutter is compiling APK (file locked)...", level="INFO")
            return

        # 2. Extract metadata & calculate hash / mtime
        metadata = get_apk_metadata(target_path, config.flutter_project_root)
        current_sha = metadata.get("sha256")
        current_mtime = metadata.get("mtime_timestamp")

        # Check if new or updated build detected
        is_sha_changed = bool(current_sha and (self.last_seen_sha256 is None or current_sha != self.last_seen_sha256))
        is_mtime_changed = bool(current_mtime and (self.last_seen_mtime is None or current_mtime != self.last_seen_mtime))

        if is_sha_changed or is_mtime_changed:
            self._log(f"NEW OR UPDATED APK DETECTED! (SHA-256: {current_sha[:10] if current_sha else 'N/A'}... | Modified: {metadata.get('build_time')})", level="INFO")
            self.state["status"] = "verifying_stability"

            # Check size stability
            if not check_file_stability(target_path, wait_seconds=config.stability_check_seconds):
                self._log("APK file size still changing, waiting for compiler to finish writing...", level="INFO")
                return

            # Trigger Upload
            self.trigger_upload(str(target_path), metadata)
        else:
            self.state["status"] = "monitoring"

    def toggle_auto_watch(self, enabled: bool = None) -> bool:
        """Toggle or set auto-watch status."""
        if enabled is None:
            self.auto_watch_enabled = not self.auto_watch_enabled
        else:
            self.auto_watch_enabled = bool(enabled)
        
        self.state["auto_watch_enabled"] = self.auto_watch_enabled
        status_str = "ENABLED" if self.auto_watch_enabled else "DISABLED (Manual Mode Active)"
        self._log(f"Auto-Watch is now {status_str}", level="INFO")

        if self.auto_watch_enabled:
            # Immediately run a check loop when toggled ON
            try:
                self.check_once()
            except Exception as e:
                self._log(f"Error checking APK on Auto-Watch toggle: {e}", level="ERROR")
        else:
            self.state["status"] = "manual_mode"

        return self.auto_watch_enabled

    def manual_check_and_upload(self) -> dict:
        """Manually trigger immediate APK check and upload on-demand."""
        target_path = Path(config.apk_file_path)
        self._log(f"Manual 'Check & Upload Now' triggered for project '{config.project_name}'", level="INFO")

        if not target_path.exists():
            from backend.config import auto_detect_apk_path
            auto_path = auto_detect_apk_path(config.flutter_project_root)
            if auto_path and Path(auto_path).exists():
                config.apk_file_path = auto_path
                config.apk_filename = Path(auto_path).name
                target_path = Path(auto_path)
            else:
                msg = f"APK file not found at path: {target_path}"
                self._log(msg, level="ERROR")
                return {"success": False, "error": msg}


        if is_file_locked(target_path):
            msg = "Flutter is still compiling/writing the APK. Please wait a moment and try again."
            self._log(msg, level="WARNING")
            return {"success": False, "error": msg}

        metadata = get_apk_metadata(target_path, config.flutter_project_root)
        success = self.trigger_upload(str(target_path), metadata)
        if success:
            return {"success": True, "apk": self.state.get("current_apk")}
        else:
            return {"success": False, "error": self.state.get("last_error", "Upload failed")}

    def _loop(self):
        self._log(f"APK Watcher started monitoring '{config.project_name}' path '{config.apk_file_path}' (Provider: {config.distribution_provider.upper()})")
        while self.running:
            try:
                if self.auto_watch_enabled:
                    self.check_once()
                else:
                    self.state["status"] = "manual_mode"
                    self.state["last_check_time"] = datetime.now().strftime("%H:%M:%S")
            except Exception as e:
                self._log(f"Error in watcher loop: {e}", level="ERROR")
            time.sleep(config.poll_interval)

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)


watcher = APKWatcher()


