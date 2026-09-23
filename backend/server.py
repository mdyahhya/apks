import sys
from pathlib import Path

# Ensure project root directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

from backend.config import config
from backend.watcher import watcher
from backend.github_uploader import github_uploader
from backend.r2_uploader import r2_uploader
from backend.apk_metadata import get_apk_metadata

logger = logging.getLogger("Server")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class CRMRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def log_message(self, format, *args):
        """Clean log handler that silences noisy HTTP 200 status polling while preserving actual errors."""
        if args and len(args) >= 2:
            status_code = str(args[1])
            path = str(args[0])
            # Suppress constant polling 200 GET logs
            if status_code == "200" and "/api/status" in path:
                return
        # Log non-polling requests and genuine errors
        sys.stdout.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def handle_one_request(self):
        """Handles single HTTP request with graceful exception trapping for Windows aborted connections."""
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            # Client closed/aborted socket connection gracefully (e.g. tab closed or aborted poll)
            pass

    def end_headers(self):
        try:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            super().end_headers()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass

    def do_OPTIONS(self):
        try:
            self.send_response(200)
            self.end_headers()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass

    def _send_json(self, data: dict, status_code: int = 200):
        try:
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/status":
                safe_config = config.to_safe_dict()
                
                # Read history sorted latest first
                history_list = watcher.history
                history_list.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)

                res = {
                    "watcher": {
                        "status": watcher.state["status"],
                        "auto_watch_enabled": watcher.auto_watch_enabled,
                        "last_check_time": watcher.state["last_check_time"],
                        "upload_status": watcher.state["upload_status"],
                        "last_error": watcher.state["last_error"],
                        "logs": watcher.state["logs"][:25]
                    },
                    "current_apk": watcher.state["current_apk"],
                    "history": history_list,
                    "config": safe_config
                }
                self._send_json(res)
                return

            elif path == "/api/history":
                history_list = watcher.history
                history_list.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
                self._send_json({"history": history_list})
                return

            elif path in ("/api/health", "/api/ping"):
                self._send_json({"status": "ok", "version": "2.1", "server": "CRM Distribution Hub Online"})
                return

            elif path == "/api/test-provider":
                provider = config.distribution_provider
                if provider == "github":
                    res = github_uploader.test_connection()
                else:
                    res = r2_uploader.test_connection()
                self._send_json(res)
                return

            # Serve static frontend files
            return super().do_GET()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if path in ("/api/force-upload", "/api/watcher/trigger"):
                res = watcher.manual_check_and_upload()
                if res.get("success"):
                    self._send_json({"success": True, "message": "APK check and upload completed successfully!", "apk": res.get("apk")})
                else:
                    self._send_json({"success": False, "error": res.get("error", "Upload failed")}, status_code=400)
                return

            elif path == "/api/watcher/toggle":
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = {}
                if content_length > 0:
                    try:
                        post_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    except Exception:
                        pass
                
                enabled = post_data.get("enabled")
                new_state = watcher.toggle_auto_watch(enabled)
                self._send_json({
                    "success": True,
                    "auto_watch_enabled": new_state,
                    "message": f"Auto-Watch is now {'ENABLED' if new_state else 'DISABLED'}"
                })
                return

            elif path == "/api/projects/switch":
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = {}
                if content_length > 0:
                    try:
                        post_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    except Exception:
                        pass

                project_id = post_data.get("project_id")
                if not project_id:
                    self._send_json({"success": False, "error": "project_id is required"}, status_code=400)
                    return

                if config.switch_project(project_id):
                    watcher.reload_for_project()
                    if watcher.auto_watch_enabled:
                        try:
                            watcher.check_once()
                        except Exception as e:
                            logger.error(f"Error checking project on switch: {e}")

                    history_list = watcher.history
                    history_list.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)

                    self._send_json({
                        "success": True,
                        "message": f"Switched active project to '{config.project_name}'",
                        "active_project_id": config.active_project_id,
                        "current_apk": watcher.state["current_apk"],
                        "history": history_list,
                        "config": config.to_safe_dict()
                    })
                else:
                    self._send_json({"success": False, "error": f"Project '{project_id}' not found"}, status_code=404)
                return

            elif path == "/api/projects/add":
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = {}
                if content_length > 0:
                    try:
                        post_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    except Exception:
                        pass

                name = post_data.get("name")
                root_path = post_data.get("flutter_project_root") or post_data.get("root_path")
                apk_path = post_data.get("apk_path")

                if not name or not root_path:
                    self._send_json({"success": False, "error": "Project name and folder path are required"}, status_code=400)
                    return

                new_proj = config.add_project(name, root_path, apk_path)
                watcher.reload_for_project()
                self._send_json({
                    "success": True,
                    "message": f"Project '{name}' created and activated!",
                    "project": new_proj,
                    "config": config.to_safe_dict()
                })
                return

            elif path == "/api/projects/delete":
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = {}
                if content_length > 0:
                    try:
                        post_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    except Exception:
                        pass

                project_id = post_data.get("project_id")
                if config.delete_project(project_id):
                    watcher.reload_for_project()
                    self._send_json({
                        "success": True,
                        "message": "Project deleted successfully",
                        "config": config.to_safe_dict()
                    })
                else:
                    self._send_json({"success": False, "error": "Failed to delete project"}, status_code=400)
                return

            elif path == "/api/browse-folder":
                folder = self._open_native_folder_picker()
                if folder:
                    auto_apk = config.auto_detect_apk_path(folder) if hasattr(config, 'auto_detect_apk_path') else ""
                    self._send_json({
                        "success": True,
                        "folder_path": folder,
                        "auto_apk_path": auto_apk,
                        "project_name": Path(folder).name
                    })
                else:
                    self._send_json({"success": False, "message": "Folder selection cancelled or unavailable"})
                return

            self._send_json({"error": "Endpoint not found"}, status_code=404)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass

    def _open_native_folder_picker(self) -> str:
        """Opens native Windows folder browser dialog using tkinter."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            folder_path = filedialog.askdirectory(title="Select Project Root Directory")
            root.destroy()
            return folder_path or ""
        except Exception as e:
            logger.error(f"Native folder picker error: {e}")
            return ""


def run_server():
    # Start background file watcher thread
    watcher.start()

    # Bind to "" (0.0.0.0) so both 127.0.0.1 and localhost resolve cleanly
    server_address = ("", config.local_port)
    httpd = ThreadedHTTPServer(server_address, CRMRequestHandler)
    print(f"================================================================")
    print(f"  LOCAL DEVELOPER CRM SERVER RUNNING")
    print(f"  Distribution Provider: {config.distribution_provider.upper()} Releases")
    print(f"  Dashboard URL:         http://127.0.0.1:{config.local_port} (or http://localhost:{config.local_port})")
    print(f"  Active Project:        {config.project_name} ({config.active_project_id})")
    print(f"  Monitoring APK Path:   {config.apk_file_path}")
    print(f"================================================================")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        watcher.stop()
        httpd.server_close()


if __name__ == "__main__":
    run_server()
