import os
import re
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger("Config")

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
CONFIG_JSON_PATH = BASE_DIR / "config" / "config.json"
PROJECTS_JSON_PATH = BASE_DIR / "config" / "projects.json"


def auto_detect_apk_path(root_path: str) -> str:
    """Intelligently detects built APK path within Flutter/Android project, picking newest .apk."""
    if not root_path:
        return ""
    root = Path(root_path)

    # Search common Flutter & Android build output folders
    search_dirs = [
        root / "build" / "app" / "outputs" / "flutter-apk",
        root / "build" / "app" / "outputs" / "apk" / "release",
        root / "app" / "build" / "outputs" / "apk" / "release",
        root / "build" / "app" / "outputs" / "apk" / "debug",
    ]

    found_apks = []
    for d in search_dirs:
        if d.exists() and d.is_dir():
            for f in d.glob("*.apk"):
                if f.is_file() and not f.name.endswith(".sha1"):
                    try:
                        found_apks.append((f.stat().st_mtime, f))
                    except Exception:
                        pass

    if found_apks:
        # Sort by latest modification time (newest first)
        found_apks.sort(key=lambda x: x[0], reverse=True)
        return str(found_apks[0][1])

    # Direct fallback candidates
    candidates = [
        root / "build" / "app" / "outputs" / "flutter-apk" / "app-arm64-v8a-release.apk",
        root / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk",
        root / "build" / "app" / "outputs" / "apk" / "release" / "app-arm64-v8a-release.apk",
        root / "build" / "app" / "outputs" / "apk" / "release" / "app-release.apk"
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return str(root / "build" / "app" / "outputs" / "flutter-apk" / "app-arm64-v8a-release.apk")



class Config:
    def __init__(self):
        self.projects = []
        self.active_project_id = ""
        self.reload()

    def reload(self):
        """Loads environment variables from .env, config.json, and projects.json."""
        if ENV_PATH.exists():
            load_dotenv(dotenv_path=ENV_PATH, override=True)

        self.distribution_provider = os.getenv("DISTRIBUTION_PROVIDER", "github").lower()

        # GitHub Releases
        self.github_username = os.getenv("GITHUB_USERNAME", "")
        self.github_repo = os.getenv("GITHUB_REPO", "")
        self.github_token = os.getenv("GITHUB_TOKEN", "")
        self.github_release_tag = os.getenv("GITHUB_RELEASE_TAG", "latest")
        self.github_public_download_url = os.getenv("GITHUB_PUBLIC_DOWNLOAD_URL", "")

        # Cloudflare R2
        self.r2_account_id = os.getenv("R2_ACCOUNT_ID", "")
        self.r2_access_key_id = os.getenv("R2_ACCESS_KEY_ID", "")
        self.r2_secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "")
        self.r2_bucket_name = os.getenv("R2_BUCKET_NAME", "")
        self.r2_public_domain = os.getenv("R2_PUBLIC_DOMAIN", "")

        # Local Server Settings
        self.local_host = os.getenv("LOCAL_HOST", "127.0.0.1")
        self.local_port = int(os.getenv("LOCAL_PORT", 8765))
        self.poll_interval = float(os.getenv("POLL_INTERVAL_SECONDS", 2))
        self.stability_check_seconds = float(os.getenv("STABILITY_CHECK_SECONDS", 3))

        # Defaults for Flutter App Settings
        self.project_name = "SINA User Android"
        self.flutter_project_root = r"C:\Users\DELL\Desktop\SINA App\SINA User Android"
        self.apk_file_path = r"C:\Users\DELL\Desktop\SINA App\SINA User Android\build\app\outputs\flutter-apk\app-release.apk"
        self.apk_filename = "app-release.apk"

        # Load JSON config overrides if exists
        if CONFIG_JSON_PATH.exists():
            try:
                with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, val in data.items():
                        if hasattr(self, key):
                            setattr(self, key, val)
            except Exception as e:
                logger.error(f"Error loading config.json: {e}")

        self.load_projects()

    def load_projects(self):
        """Loads projects configuration or creates default pre-added projects."""
        default_projects = [
            {
                "id": "sina-user-android",
                "name": "SINA User Android",
                "flutter_project_root": r"C:\Users\DELL\Desktop\SINA App\SINA User Android",
                "apk_path": auto_detect_apk_path(r"C:\Users\DELL\Desktop\SINA App\SINA User Android"),
                "apk_filename": "app-release.apk",
                "github_release_tag": "sina-user-android"
            },
            {
                "id": "sina-admin-android",
                "name": "SINA Admin Android",
                "flutter_project_root": r"C:\Users\DELL\Desktop\SINA App\SINA Admin Android",
                "apk_path": auto_detect_apk_path(r"C:\Users\DELL\Desktop\SINA App\SINA Admin Android"),
                "apk_filename": "app-release.apk",
                "github_release_tag": "sina-admin-android"
            },
            {
                "id": "school-app",
                "name": "School App",
                "flutter_project_root": r"C:\Users\DELL\Desktop\school_app",
                "apk_path": auto_detect_apk_path(r"C:\Users\DELL\Desktop\school_app"),
                "apk_filename": "app-release.apk",
                "github_release_tag": "school-app"
            }
        ]

        if PROJECTS_JSON_PATH.exists():
            try:
                with open(PROJECTS_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.projects = data.get("projects", default_projects)
                    self.active_project_id = data.get("active_project_id", "sina-user-android")
            except Exception as e:
                logger.error(f"Error loading projects.json: {e}")
                self.projects = default_projects
                self.active_project_id = "sina-user-android"
        else:
            self.projects = default_projects
            self.active_project_id = "sina-user-android"
            self.save_projects()

        self.apply_active_project()

    def save_projects(self):
        """Saves current projects list and active project ID to projects.json."""
        try:
            PROJECTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(PROJECTS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "active_project_id": self.active_project_id,
                    "projects": self.projects
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving projects.json: {e}")

    def apply_active_project(self):
        """Applies configuration of the currently active project."""
        active = self.get_active_project()
        if active:
            self.project_name = active.get("name", self.project_name)
            self.flutter_project_root = active.get("flutter_project_root", self.flutter_project_root)
            specified_path = active.get("apk_path")
            if specified_path and Path(specified_path).exists():
                self.apk_file_path = specified_path
            else:
                self.apk_file_path = auto_detect_apk_path(self.flutter_project_root)
            self.apk_filename = Path(self.apk_file_path).name if self.apk_file_path else active.get("apk_filename", "app-arm64-v8a-release.apk")

    def get_active_project(self) -> dict:
        """Returns the active project dictionary."""
        for p in self.projects:
            if p.get("id") == self.active_project_id:
                return p
        if self.projects:
            self.active_project_id = self.projects[0]["id"]
            return self.projects[0]
        return {
            "id": "default",
            "name": self.project_name,
            "flutter_project_root": self.flutter_project_root,
            "apk_path": self.apk_file_path,
            "apk_filename": self.apk_filename
        }

    def switch_project(self, project_id: str) -> bool:
        """Switches active project to project_id."""
        for p in self.projects:
            if p.get("id") == project_id:
                self.active_project_id = project_id
                self.apply_active_project()
                self.save_projects()
                logger.info(f"Switched active project to '{p.get('name')}' ({project_id})")
                return True
        return False

    def add_project(self, name: str, flutter_project_root: str, apk_path: str = None) -> dict:
        """Creates a new project and switches to it."""
        slug = re.sub(r'[^a-z0-9]+', '-', name.strip().lower()).strip('-') or f"proj-{len(self.projects)+1}"
        
        # Ensure unique ID
        existing_ids = {p["id"] for p in self.projects}
        unique_id = slug
        counter = 1
        while unique_id in existing_ids:
            unique_id = f"{slug}-{counter}"
            counter += 1

        resolved_apk_path = apk_path or auto_detect_apk_path(flutter_project_root)

        new_proj = {
            "id": unique_id,
            "name": name.strip(),
            "flutter_project_root": flutter_project_root.strip(),
            "apk_path": resolved_apk_path,
            "apk_filename": Path(resolved_apk_path).name if resolved_apk_path else "app-release.apk",
            "github_release_tag": unique_id
        }

        self.projects.append(new_proj)
        self.active_project_id = unique_id
        self.apply_active_project()
        self.save_projects()
        logger.info(f"Added new project '{name}' ({unique_id})")
        return new_proj

    def get_project_release_tag(self, project_id: str = None) -> str:
        """Returns the GitHub release tag configured for the given project or active project."""
        pid = project_id or self.active_project_id
        for p in self.projects:
            if p.get("id") == pid:
                return p.get("github_release_tag") or p.get("id") or self.github_release_tag or "latest"
        return pid or self.github_release_tag or "latest"

    def delete_project(self, project_id: str) -> bool:
        """Deletes a project by ID."""
        if len(self.projects) <= 1:
            return False  # Do not allow deleting the last remaining project

        proj_to_remove = None
        for p in self.projects:
            if p.get("id") == project_id:
                proj_to_remove = p
                break

        if proj_to_remove:
            self.projects.remove(proj_to_remove)
            if self.active_project_id == project_id:
                self.active_project_id = self.projects[0]["id"]
                self.apply_active_project()
            self.save_projects()
            logger.info(f"Deleted project {project_id}")
            return True
        return False

    def get_public_download_url(self, filename: str = None, tag: str = None) -> str:
        """Returns the public download URL based on active provider and project tag."""
        filename = filename or self.apk_filename
        release_tag = tag or self.get_project_release_tag()
        if self.distribution_provider == "github":
            return f"https://github.com/{self.github_username}/{self.github_repo}/releases/download/{release_tag}/{filename}"
        else:
            domain = self.r2_public_domain.rstrip('/')
            return f"{domain}/{filename}"


    def to_safe_dict(self) -> dict:
        """Returns safe configuration dictionary isolating all sensitive tokens."""
        active_proj = self.get_active_project()
        return {
            "distribution_provider": self.distribution_provider,
            "github_username": self.github_username,
            "github_repo": self.github_repo,
            "github_release_tag": self.github_release_tag,
            "github_token_configured": bool(self.github_token and len(self.github_token) > 5),
            "r2_account_id": self.r2_account_id,
            "r2_bucket_name": self.r2_bucket_name,
            "r2_configured": bool(self.r2_access_key_id and self.r2_secret_access_key),
            "apk_file_path": self.apk_file_path,
            "apk_filename": self.apk_filename,
            "project_name": self.project_name,
            "flutter_project_root": self.flutter_project_root,
            "download_url": self.get_public_download_url(),
            "local_host": self.local_host,
            "local_port": self.local_port,
            "active_project_id": self.active_project_id,
            "active_project": active_proj,
            "projects": self.projects
        }


config = Config()

