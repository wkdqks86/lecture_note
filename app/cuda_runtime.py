"""Fetches the CUDA runtime DLLs faster-whisper needs, on demand.

Bundling cuBLAS + cuDNN made the build 2.27GB, of which 1.93GB was those two
packages alone. They only speed up machines that have an NVIDIA GPU, and
Transcriber already falls back to CPU without them, so the exe ships without
them and downloads them once into DATA_DIR (which survives reinstalls).

The wheels on PyPI are plain zip files, so this needs no pip at runtime -- it
reads the download URL from the PyPI JSON API and unpacks just the DLLs.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from app.cancellation import ProcessingCancelled
from app.paths import CUDA_DIR

# Pinned to the versions requirements.txt installs for development, so the
# downloaded runtime matches what the app was tested against. ctranslate2
# needs cuBLAS 12 / cuDNN 9.
PACKAGES = (
    ("nvidia-cublas-cu12", "12.9.2.10"),
    # Declared as a dependency of nvidia-cublas-cu12: cuBLASLt compiles some
    # kernels at runtime through NVRTC. The old bundled build shipped it too.
    ("nvidia-cuda-nvrtc-cu12", "12.9.86"),
    ("nvidia-cudnn-cu12", "9.25.1.1"),
)

PYPI_JSON_URL = "https://pypi.org/pypi/{name}/{version}/json"
MARKER_NAME = ".installed"
CHUNK_SIZE = 1 << 20  # 1 MiB
NETWORK_TIMEOUT = 60


def _expected_marker() -> str:
    return "\n".join(f"{name}=={version}" for name, version in PACKAGES)


def is_installed() -> bool:
    """True only for a complete install of the pinned versions -- a partial or
    outdated one has to be redone rather than half-loaded."""
    marker = CUDA_DIR / MARKER_NAME
    if not marker.is_file():
        return False
    try:
        return marker.read_text(encoding="utf-8").strip() == _expected_marker()
    except OSError:
        return False


def has_nvidia_gpu() -> bool:
    """The NVIDIA driver installs nvidia-smi alongside itself, so its presence
    is a good stand-in for 'this machine can use the CUDA runtime'."""
    if sys.platform != "win32":
        return False
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    if (Path(system_root) / "System32" / "nvidia-smi.exe").is_file():
        return True
    return shutil.which("nvidia-smi") is not None


def gpu_name() -> str | None:
    """Short GPU name for the setup dialog, or None if it can't be read."""
    if not has_nvidia_gpu():
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    name = out.stdout.strip().splitlines()
    return name[0].strip() if name and name[0].strip() else None


def _wheel_info(name: str, version: str) -> dict:
    url = PYPI_JSON_URL.format(name=name, version=version)
    with urllib.request.urlopen(url, timeout=NETWORK_TIMEOUT) as response:
        data = json.load(response)

    for entry in data["urls"]:
        if "win_amd64" in entry["filename"] and entry["filename"].endswith(".whl"):
            return {
                "filename": entry["filename"],
                "url": entry["url"],
                "size": entry["size"],
                "sha256": entry["digests"]["sha256"],
            }
    raise RuntimeError(f"{name} {version}: Windows용 파일을 찾을 수 없습니다.")


def download_size() -> int:
    """Total bytes to download, so the UI can ask before starting 1GB+."""
    return sum(_wheel_info(name, version)["size"] for name, version in PACKAGES)


def _download(info: dict, dest: Path, on_chunk, should_cancel) -> None:
    digest = hashlib.sha256()
    with urllib.request.urlopen(info["url"], timeout=NETWORK_TIMEOUT) as response:
        with open(dest, "wb") as out:
            while True:
                if should_cancel is not None and should_cancel():
                    raise ProcessingCancelled()
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                on_chunk(len(chunk))

    if digest.hexdigest() != info["sha256"]:
        raise RuntimeError(f"{info['filename']}: 내려받은 파일이 손상되었습니다.")


def _extract_dlls(wheel_path: Path, dest: Path) -> int:
    """Pulls just the runtime DLLs out, flattened into one folder so a single
    entry on the DLL search path covers both packages."""
    extracted = 0
    with zipfile.ZipFile(wheel_path) as archive:
        for member in archive.namelist():
            if not member.lower().endswith(".dll") or "/bin/" not in member:
                continue
            with archive.open(member) as source, open(dest / Path(member).name, "wb") as out:
                shutil.copyfileobj(source, out)
            extracted += 1
    return extracted


def install(
    progress_cb: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Path:
    """Downloads and unpacks the runtime. Raises ProcessingCancelled if the
    user stops it; the existing install (if any) is left untouched until the
    new one is complete."""
    infos = [_wheel_info(name, version) for name, version in PACKAGES]
    total = sum(info["size"] for info in infos)
    downloaded = 0

    def on_chunk(count: int) -> None:
        nonlocal downloaded
        downloaded += count
        if progress_cb is not None:
            progress_cb(downloaded, total)

    if progress_cb is not None:
        progress_cb(0, total)

    # Stage beside the final folder so the swap at the end is a rename on the
    # same drive, and a stopped download never looks like a finished install.
    staging = CUDA_DIR.with_name(CUDA_DIR.name + ".part")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(prefix="lecturenotes-cuda-") as tmp:
            for info in infos:
                wheel_path = Path(tmp) / info["filename"]
                _download(info, wheel_path, on_chunk, should_cancel)
                _extract_dlls(wheel_path, staging)
                # Free the ~600MB wheel before pulling the next one.
                wheel_path.unlink(missing_ok=True)

        (staging / MARKER_NAME).write_text(_expected_marker(), encoding="utf-8")
        shutil.rmtree(CUDA_DIR, ignore_errors=True)
        staging.replace(CUDA_DIR)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return CUDA_DIR


def uninstall() -> None:
    shutil.rmtree(CUDA_DIR, ignore_errors=True)
