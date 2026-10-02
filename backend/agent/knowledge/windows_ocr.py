"""Local Windows OCR for scanned EPUB images; no provider or network fallback."""
from __future__ import annotations
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from PIL import Image

OCR_PARSER_VERSION = "epub-native-windows-ocr-v2"

class WindowsBookOCR:
    version = "windows-media-ocr-v1"

    def __call__(self, data: bytes) -> str:
        if os.name != "nt" or len(data) > 16 * 1024 * 1024:
            return ""
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 16_000_000:
                raise ValueError("BOOK_OCR_IMAGE_TOO_LARGE")
            scale = min(4.0, 2400 / max(image.size))
            bitmap = image.convert("RGB")
            if scale > 1:
                bitmap = bitmap.resize((int(image.width*scale), int(image.height*scale)), Image.Resampling.LANCZOS)
            with TemporaryDirectory(prefix="vellum-book-ocr-") as directory:
                path = Path(directory) / "page.png"
                bitmap.save(path)
                program = Path(__file__).with_suffix(".ps1").read_text(encoding="utf-8")
                executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
                result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-Command", program],
                    env={**os.environ, "VELLUM_OCR_INPUT": str(path)}, capture_output=True, text=True, encoding="utf-8",
                    timeout=45, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode:
                    raise ValueError("BOOK_LOCAL_OCR_UNAVAILABLE")
                payload = json.loads(result.stdout)
                return "\n".join(str(line) for line in payload.get("lines", []))[:100_000]
