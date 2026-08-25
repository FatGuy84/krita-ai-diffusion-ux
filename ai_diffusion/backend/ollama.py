from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..settings import settings
from ..util import client_logger as log, plugin_dir, user_data_dir
from .network import NetworkError, RequestManager

# Ollama runs as its own service, independent of the ComfyUI connection, so it gets
# its own request manager rather than borrowing the one owned by the client.
_requests = RequestManager()


class EnhanceTask(Enum):
    enhance = "enhance"
    rewrite = "rewrite"
    detail = "detail"
    variations = "variations"


_task_instructions = {
    EnhanceTask.enhance: (
        "Expand and improve the following prompt. Keep the subject, composition and"
        " intent unchanged, but make it more specific and visually detailed."
    ),
    EnhanceTask.rewrite: (
        "Write a new prompt for the following idea. You may restructure it completely,"
        " but stay true to the subject the user described."
    ),
    EnhanceTask.detail: (
        "Add missing detail to the following prompt. Do not change or remove anything"
        " that is already there - only append what is missing (lighting, materials,"
        " camera, background)."
    ),
    EnhanceTask.variations: (
        "Write {count} different variations of the following prompt. Vary pose, setting,"
        " lighting and camera, but keep the same subject. Output one variation per line,"
        " nothing else - no numbering, no blank lines, no commentary."
    ),
}


def url() -> str:
    value = settings.ollama_url.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    return value


async def list_models() -> list[str]:
    result = await _requests.get(f"{url()}/api/tags", timeout=10)
    models = result.get("models") or []
    return sorted(m["name"] for m in models if m.get("name"))


async def generate(system: str, prompt: str, *, timeout: float | None = None) -> str:
    data = {
        "model": settings.ollama_model,
        "system": system,
        "prompt": prompt,
        # The reply is consumed as a single JSON document - streaming would produce
        # newline-delimited JSON which the request manager cannot parse.
        "stream": False,
        "think": False,  # ignored by models without a thinking mode
        "keep_alive": settings.ollama_keep_alive,
        "options": {
            "temperature": settings.ollama_temperature,
            "num_predict": settings.ollama_max_tokens,
        },
    }
    timeout = timeout or settings.ollama_timeout
    result = await _requests.http("POST", f"{url()}/api/generate", data, timeout=timeout)
    return clean_response(result.get("response", ""))


async def unload():
    """Ask Ollama to drop the model from VRAM right now."""
    data = {"model": settings.ollama_model, "prompt": "", "stream": False, "keep_alive": 0}
    try:
        await _requests.http("POST", f"{url()}/api/generate", data, timeout=30)
    except NetworkError as e:
        log.warning(f"Failed to unload Ollama model: {e}")


async def free_comfy_vram(client):
    """Unload checkpoints on the ComfyUI side to make room for the language model.
    Only useful when both run on the same GPU."""
    try:
        await client._requests.http(
            "POST",
            f"{client.url}/free",
            {"unload_models": True, "free_memory": True},
            timeout=30,
        )
    except NetworkError as e:
        log.warning(f"Failed to free ComfyUI memory: {e}")


# Response clean-up ####################################################################

_think_re = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_fence_re = re.compile(r"^```[a-z]*\n?|```$", re.MULTILINE)
_prefix_re = re.compile(r"^\s*(?:prompt|positive prompt|output)\s*:\s*", re.IGNORECASE)


def clean_response(text: str) -> str:
    text = _think_re.sub("", text)
    text = _fence_re.sub("", text)
    text = _prefix_re.sub("", text.strip())
    text = text.strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text.strip()


# Protecting syntax the language model must not touch ##################################

# LoRA tags, file wildcards, random and sequential wildcard groups. These carry meaning
# for the plugin and get mangled if the model is allowed to rewrite them.
_protected_re = re.compile(r"<lora:[^>]*>|__[^_\s]+?__|\[\[.*?\]\]|\{[^{}]*\|[^{}]*\}")


@dataclass
class ProtectedPrompt:
    text: str  # prompt with protected parts removed, safe to send to the model
    tokens: list[str]  # protected parts, in the order they appeared

    def restore(self, result: str) -> str:
        if not self.tokens:
            return result
        return ", ".join([result.rstrip(" ,")] + self.tokens)


def protect(prompt: str) -> ProtectedPrompt:
    tokens = _protected_re.findall(prompt)
    text = _protected_re.sub("", prompt)
    text = re.sub(r"[^\S\n]+", " ", text)  # collapse gaps left by removed tokens
    text = re.sub(r"(?:\s*,)+", ",", text)  # ... and the dangling commas around them
    text = re.sub(r",(?=\S)", ", ", text)
    return ProtectedPrompt(text.strip().strip(",").strip(), tokens)


# Prompt profiles ######################################################################


@dataclass
class Profile:
    id: str
    name: str
    system: str


class Profiles:
    """Maps a base model family (SD XL, Illustrious, Krea 2, ...) to the system prompt
    which teaches the language model how prompts for that family are written."""

    _instance: Profiles | None = None

    default_path = plugin_dir / "presets" / "prompt_enhance.json"
    user_path = user_data_dir / "prompt_enhance.json"

    def __init__(self, data: dict):
        self._profiles = {
            key: Profile(key, value.get("name", key), value.get("system", ""))
            for key, value in (data.get("profiles") or {}).items()
        }
        self._families: dict[str, str] = data.get("families") or {}
        self._default = data.get("default", next(iter(self._profiles), ""))

    @classmethod
    def instance(cls) -> Profiles:
        if cls._instance is None:
            cls._instance = cls.load()
        return cls._instance

    @classmethod
    def load(cls) -> Profiles:
        data = _read_json(cls.default_path) or {}
        if user := _read_json(cls.user_path):
            data.setdefault("profiles", {}).update(user.get("profiles") or {})
            data.setdefault("families", {}).update(user.get("families") or {})
            data["default"] = user.get("default", data.get("default"))
        return Profiles(data)

    @classmethod
    def reload(cls):
        cls._instance = cls.load()
        return cls._instance

    def __iter__(self):
        return iter(self._profiles.values())

    def get(self, profile_id: str) -> Profile | None:
        return self._profiles.get(profile_id)

    def for_family(self, family: str) -> Profile | None:
        profile_id = self._families.get(family, self._default)
        return self._profiles.get(profile_id) or self._profiles.get(self._default)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"Failed to read prompt profiles from {path}: {e}")
        return None


def build_prompt(task: EnhanceTask, prompt: str, count: int = 4) -> str:
    instruction = _task_instructions[task].format(count=count)
    if not prompt.strip():
        instruction = (
            "The user did not provide a prompt. Invent an interesting image prompt from" " scratch."
        )
        return instruction
    return f"{instruction}\n\nPrompt:\n{prompt}"
