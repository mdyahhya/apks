import os
import time
import hashlib
import re
import zipfile
from datetime import datetime
from pathlib import Path


def calculate_sha256(file_path: str) -> str:
    """Compute SHA-256 hash of a file efficiently using chunking."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def is_file_locked(file_path: str) -> bool:
    """Check if the file is currently locked by a write process (e.g., Flutter build)."""
    if not os.path.exists(file_path):
        return False
    try:
        # On Windows, opening with 'r+b' will fail with PermissionError if another process has exclusive write lock
        with open(file_path, "a+b"):
            pass
        return False
    except (IOError, PermissionError):
        return True


def check_file_stability(file_path: str, wait_seconds: float = 3.0) -> bool:
    """
    Verify that an APK file has finished writing.
    Checks:
      1. File exists
      2. File size > 0
      3. File is not actively locked
      4. File size remains identical after wait_seconds
    """
    path = Path(file_path)
    if not path.exists():
        return False

    try:
        initial_size = path.stat().st_size
        if initial_size == 0:
            return False

        if is_file_locked(file_path):
            return False

        # Sleep briefly to ensure no further bytes are being appended
        time.sleep(wait_seconds)

        if not path.exists():
            return False

        final_size = path.stat().st_size
        if is_file_locked(file_path):
            return False

        return (initial_size == final_size) and (final_size > 0)
    except Exception:
        return False


def extract_version_from_pubspec(project_root: str) -> dict:
    """Extract version and build number from Flutter pubspec.yaml if present."""
    if not project_root:
        return {}
    
    pubspec_path = Path(project_root) / "pubspec.yaml"
    if not pubspec_path.exists():
        return {}

    try:
        with open(pubspec_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                # Matches: version: 1.0.0+1 or version: 2.1.0
                if line_str.startswith("version:"):
                    parts = line_str.split(":", 1)
                    if len(parts) > 1:
                        raw_version = parts[1].strip().split("#")[0].strip()
                        # Split version and build number (e.g., 1.0.5+12)
                        if "+" in raw_version:
                            v, b = raw_version.split("+", 1)
                            return {"version": v.strip(), "build_number": b.strip()}
                        return {"version": raw_version, "build_number": ""}
    except Exception:
        pass
    return {}


def extract_version_from_apk(apk_path: str) -> dict:
    """Fallback extraction of version information from APK contents if possible."""
    if not os.path.exists(apk_path):
        return {}
    
    try:
        with zipfile.ZipFile(apk_path, "r") as zf:
            # Check for standard Flutter app assets or manifest strings
            for name in zf.namelist():
                if "app.so" in name or "flutter_assets" in name:
                    # APK is indeed a valid Flutter package
                    break
    except Exception:
        pass
    return {}


def get_apk_metadata(file_path: str, flutter_project_root: str = None) -> dict:
    """
    Get full metadata dictionary for an APK file.
    """
    path = Path(file_path)
    if not path.exists():
        return {
            "exists": False,
            "filename": path.name,
            "path": str(path),
            "size_bytes": 0,
            "size_mb": 0.0,
            "version": "1.0.0",
            "build_number": "",
            "sha256": None,
            "modified_at_iso": None,
            "modified_at_formatted": None
        }

    stat = path.stat()
    size_bytes = stat.st_size
    size_mb = round(size_bytes / (1024 * 1024), 2)
    mtime = datetime.fromtimestamp(stat.st_mtime)

    # Compute hash
    sha256 = calculate_sha256(str(path))

    # Version extraction
    ver_info = extract_version_from_pubspec(flutter_project_root)
    if not ver_info:
        ver_info = extract_version_from_apk(str(path))

    version = ver_info.get("version") or "1.0.0"
    build_number = ver_info.get("build_number") or ""

    build_time_formatted = mtime.strftime("%d %b %Y, %I:%M %p")
    build_time_full = mtime.strftime("%d %b %Y, %I:%M:%S %p")

    return {
        "exists": True,
        "filename": path.name,
        "path": str(path),
        "size_bytes": size_bytes,
        "size_mb": size_mb,
        "file_size_mb": size_mb,
        "version": version,
        "build_number": build_number,
        "sha256": sha256,
        "mtime_timestamp": stat.st_mtime,
        "build_time": build_time_formatted,
        "build_time_full": build_time_full,
        "file_modified_at": build_time_formatted,
        "modified_at_iso": mtime.isoformat(),
        "modified_at_formatted": build_time_formatted
    }


