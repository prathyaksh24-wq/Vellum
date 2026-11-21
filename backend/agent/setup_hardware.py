"""Scan this computer and recommend how Vellum should run its model.

Onboarding asks: can this machine run a local model well? If yes, which
one; if not, use a cloud model (OpenRouter with the user's key, or free
Groq). The scan only reads local facts: memory, free disk, GPU, CPU, and
whether Ollama is installed. Nothing leaves the machine.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

GB = 1024 ** 3

# Local model tiers, largest first. Sizes are the Q4 download. A tier fits
# when the GPU can hold it (min_vram_gb) or, without enough GPU memory, when
# system RAM can (min_ram_cpu_gb). Windows reports a little under the
# installed RAM (16 GB shows as ~15.2), so thresholds sit just below.
LOCAL_TIERS = (
    {"model": "gemma4:12b", "label": "Gemma 4 12B", "size_gb": 7.6, "min_vram_gb": 10, "min_ram_cpu_gb": 23},
    {"model": "qwen3.5:9b", "label": "Qwen 3.5 9B", "size_gb": 5.5, "min_vram_gb": 6, "min_ram_cpu_gb": 7.5},
)
MIN_RAM_GB = 7.5  # an "8 GB" machine
MIN_FREE_DISK_GB = 10  # model + memory engines + room to work


@dataclass
class Hardware:
    ram_gb: float
    free_disk_gb: float
    cpu_cores: int
    cpu_name: str = ""
    gpu_name: str = ""
    vram_gb: float = 0.0
    ollama_installed: bool = False
    ollama_running: bool = False
    platform: str = sys.platform


@dataclass
class Recommendation:
    mode: str  # "local" | "cloud"
    model: str = ""
    label: str = ""
    size_gb: float = 0.0
    reasons: list[str] = field(default_factory=list)
    cloud_options: list[str] = field(default_factory=lambda: ["openrouter", "groq"])


def recommend(hw: Hardware) -> Recommendation:
    reasons: list[str] = []
    if hw.free_disk_gb < MIN_FREE_DISK_GB:
        reasons.append(f"Only {hw.free_disk_gb:.0f} GB free; a local model needs about {MIN_FREE_DISK_GB} GB.")
    if hw.ram_gb < MIN_RAM_GB:
        reasons.append(f"{hw.ram_gb:.0f} GB of memory is not enough to run a local model well (8 GB minimum).")
    if reasons:
        return Recommendation(mode="cloud", reasons=reasons + [
            "Use a cloud model instead: OpenRouter with your key, or Groq's free tier."])
    for tier in LOCAL_TIERS:
        on_gpu = hw.vram_gb >= tier["min_vram_gb"]
        if on_gpu or hw.ram_gb >= tier["min_ram_cpu_gb"]:
            why = [f"Runs on your {hw.gpu_name or 'GPU'} ({hw.vram_gb:.0f} GB)" if on_gpu
                   else f"Runs on your processor with {hw.ram_gb:.0f} GB memory (no suitable GPU; slower)",
                   f"{tier['label']} is about {tier['size_gb']} GB to download"]
            why.append(_context_reason(tier, on_gpu, hw))
            if not hw.ollama_installed:
                why.append("Ollama will need to be installed to run it")
            return Recommendation(mode="local", model=tier["model"], label=tier["label"],
                                  size_gb=tier["size_gb"], reasons=why)
    return Recommendation(mode="cloud", reasons=["No local model fits this machine."])


def _context_reason(tier: dict[str, Any], on_gpu: bool, hw: Hardware) -> str:
    """How much conversation the recommended model can keep in view on this computer."""
    from agent.llm.context_sizing import _read
    measured = (_read().get("measured") or {}).get("ollama/" + tier["model"]) or {}
    if measured.get("window"):
        return f"Context window: {measured['window'] // 1024}k tokens, measured on this computer"
    from agent.setup_models import estimate_context
    tokens = estimate_context(tier["label"], tier["size_gb"], "gpu" if on_gpu else "cpu",
                              {"vram_gb": hw.vram_gb, "ram_gb": hw.ram_gb})
    if not on_gpu:
        return f"Context window: about {tokens // 1024}k tokens on your processor"
    return f"Context window: at least {tokens // 1024}k tokens on your GPU; Vellum measures the exact size after download"


def scan(workspace: Path | None = None) -> Hardware:
    import psutil

    from agent.config import REPO_ROOT, get_settings

    disk_root = Path(workspace or REPO_ROOT).anchor or str(Path.home())
    gpu_name, vram_gb = _gpu()
    ollama_url = get_settings().ollama_base_url.rstrip("/")
    return Hardware(
        ram_gb=round(psutil.virtual_memory().total / GB, 1),
        free_disk_gb=round(shutil.disk_usage(disk_root).free / GB, 1),
        cpu_cores=int(psutil.cpu_count(logical=True) or os.cpu_count() or 1),
        cpu_name=_cpu_name(),
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        ollama_installed=bool(shutil.which("ollama")) or _ollama_running(ollama_url),
        ollama_running=_ollama_running(ollama_url),
    )


def scan_and_recommend() -> dict[str, Any]:
    hardware = scan()
    return {"hardware": asdict(hardware), "recommendation": asdict(recommend(hardware))}


def _run(argv: list[str]) -> str:
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=8, check=False, **extra)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _gpu() -> tuple[str, float]:
    """NVIDIA via nvidia-smi (exact VRAM); otherwise the Windows video controller."""
    if shutil.which("nvidia-smi"):
        out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        if out:
            name, _, mib = out.splitlines()[0].partition(",")
            try:
                return name.strip(), round(float(mib.strip()) / 1024, 1)
            except ValueError:
                return name.strip(), 0.0
    if sys.platform == "win32":
        out = _run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name | ConvertTo-Json -Compress"])
        try:
            data = json.loads(out) if out else []
        except ValueError:
            data = []
        names = [item.get("Name", "") for item in (data if isinstance(data, list) else [data])]
        # AdapterRAM caps at 4 GB on Windows, so VRAM is unknown without nvidia-smi.
        return next((name for name in names if name), ""), 0.0
    return "", 0.0


def _cpu_name() -> str:
    if sys.platform == "win32":
        return os.environ.get("PROCESSOR_IDENTIFIER", "")
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def _ollama_running(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/version", timeout=1) as response:  # noqa: S310 - local
            return response.status == 200
    except Exception:  # noqa: BLE001
        return False
