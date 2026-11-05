"""PPTX -> PDF with headless LibreOffice in Docker (scripts/libreoffice/Dockerfile).

Nothing runs on the host: the container has no network, sees only a work directory,
and is killed by name when it exceeds the timeout.
"""

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Literal

# Impress PDF export; hidden slides are exported too, so the PDF page count always
# equals the PPTX slide count (the alignment check relies on it).
PDF_FILTER = 'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}'
BUILD_HINT = "build it with scripts/libreoffice/build.sh"
# A fresh profile in the container's /tmp: works for any --user uid, gone after the run.
PROFILE_ARG = "-env:UserInstallation=file:///tmp/lo-profile"

ErrorKind = Literal["docker", "load", "timeout"]


class LibreOfficeError(RuntimeError):
    def __init__(self, message: str, kind: ErrorKind):
        super().__init__(message)
        self.kind = kind


def docker_ready(image: str) -> bool:
    """True when the docker CLI exists, the daemon answers, and the image is built."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _user_args() -> list[str]:
    # Run as the host user so output files are not owned by the container user (Linux).
    if hasattr(os, "getuid"):
        return ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp"]
    return []


def pptx_to_pdf(pptx: Path, work_dir: Path, image: str, timeout: float) -> Path:
    """Convert `pptx` and return the PDF path inside `work_dir`."""
    if not docker_ready(image):
        raise LibreOfficeError(f"docker image {image!r} is not available; {BUILD_HINT}", "docker")
    work_dir.mkdir(parents=True, exist_ok=True)
    source = work_dir / "input.pptx"
    target = work_dir / "input.pdf"
    if pptx.resolve() != source.resolve():
        shutil.copyfile(pptx, source)
    target.unlink(missing_ok=True)
    name = f"classpilot-lo-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker", "run", "--rm", "--name", name, "--network", "none",
        *_user_args(),
        "-v", f"{work_dir.resolve()}:/work",
        image, PROFILE_ARG,
        "--convert-to", PDF_FILTER, "--outdir", "/work", "/work/input.pptx",
    ]  # fmt: skip
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=30)
        raise LibreOfficeError(f"LibreOffice timed out after {timeout:.0f} s", "timeout") from exc
    if result.returncode != 0 or not target.exists():
        lines = [
            line
            for line in (result.stderr + result.stdout).splitlines()
            if line.strip() and "javaldx" not in line
        ]
        detail = lines[-1] if lines else f"exit code {result.returncode}"
        raise LibreOfficeError(f"LibreOffice could not convert the file: {detail}", "load")
    return target
