from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path  # noqa: F401 used in fetch_loras fallback
from typing import TYPE_CHECKING

from ..util import client_logger as log

if TYPE_CHECKING:
    from .network import RequestManager


@dataclass
class LoraInfo:
    name: str
    file_name: str
    base_model: str = ""
    tags: list[str] = field(default_factory=list)
    preview_url: str = ""
    trigger_words: list[str] = field(default_factory=list)
    sha256: str = ""

    @staticmethod
    def from_api(data: dict, base_url: str) -> LoraInfo:
        name = data.get("model_name") or data.get("name") or data.get("file_name", "")
        file_name = data.get("file_name") or name
        sha256 = data.get("sha256", "")
        preview = ""
        if sha256:
            preview = f"{base_url}/loras/preview/{sha256}"
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        trigger_words = data.get("trained_words", [])
        if isinstance(trigger_words, str):
            trigger_words = [t.strip() for t in trigger_words.split(",") if t.strip()]
        return LoraInfo(
            name=name,
            file_name=file_name,
            base_model=data.get("base_model", ""),
            tags=tags,
            preview_url=preview,
            trigger_words=trigger_words,
            sha256=sha256,
        )


# base_model strings from Lora Manager → Arch enum value name
_BASE_MODEL_MAP = {
    "sd 1": "sd15",
    "sd1": "sd15",
    "v1": "sd15",
    "sdxl": "sdxl",
    "sd xl": "sdxl",
    "pony": "sdxl",
    "sd3": "sd3",
    "sd 3": "sd3",
    "flux": "flux",
    "illustrious": "sdxl",
}


def arch_for_base_model(base_model: str) -> str:
    """Return Arch enum name (e.g. 'sdxl') for a base_model string, or '' if unknown."""
    lower = base_model.lower()
    for key, arch in _BASE_MODEL_MAP.items():
        if key in lower:
            return arch
    return ""


async def fetch_loras(requests: RequestManager, base_url: str) -> list[LoraInfo]:
    """Fetch LoRA list. Tries ComfyUI-Lora-Manager first, falls back to /models/loras."""
    base = base_url.rstrip("/")

    # Try Lora Manager (rich metadata)
    try:
        data = await requests.get(f"{base}/loras?page=1&page_size=10000&load_metadata=true", timeout=10.0)
        if isinstance(data, (bytes, bytearray)):
            data = json.loads(data)
        if isinstance(data, dict):
            items = data.get("loras") or data.get("items") or []
            if items:
                return [LoraInfo.from_api(item, base) for item in items]
    except Exception:
        pass

    # Fallback: standard ComfyUI /models/loras (filename list only)
    try:
        data = await requests.get(f"{base}/models/loras", timeout=10.0)
        if isinstance(data, (bytes, bytearray)):
            data = json.loads(data)
        if isinstance(data, list):
            result = []
            for entry in data:
                if isinstance(entry, str):
                    name = Path(entry).stem
                    result.append(LoraInfo(name=name, file_name=entry))
                elif isinstance(entry, dict):
                    result.append(LoraInfo.from_api(entry, base))
            log.info(f"Loaded {len(result)} LoRAs from /models/loras (no metadata)")
            return result
    except Exception as e:
        log.warning(f"Could not fetch LoRA list: {e}")

    return []


async def fetch_preview_bytes(requests: RequestManager, preview_url: str) -> bytes | None:
    """Fetch preview image bytes. Returns None on error."""
    if not preview_url:
        return None
    try:
        result = await requests.download(preview_url, timeout=8.0)
        # result is QByteArray from buffer.data()
        return bytes(result) if result else None
    except Exception as e:
        log.warning(f"Could not fetch LoRA preview {preview_url}: {e}")
        return None
