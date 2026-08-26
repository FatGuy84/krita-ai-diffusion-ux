from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PyQt5.QtCore import QByteArray, QUrl
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

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
    instruct = "instruct"


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
    EnhanceTask.instruct: (
        "Apply the following change to the prompt below. Keep everything the change does"
        " not concern exactly as it is, and answer with the complete modified prompt."
        " Delete whatever contradicts the change instead of keeping both versions, and"
        " never state what was removed - a removed thing is simply absent from the"
        " answer.\n\nChange to apply: {instruction}"
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


# Tasks which modify an existing prompt rather than inventing one. A high temperature
# makes the model drift off and keep contradicting tags around, so it gets capped.
_conservative_tasks = {EnhanceTask.instruct, EnhanceTask.detail}
_conservative_temperature = 0.6


def temperature_for(task: EnhanceTask) -> float:
    if task in _conservative_tasks:
        return min(settings.ollama_temperature, _conservative_temperature)
    return settings.ollama_temperature


def _request_body(
    prompt: str,
    system: str,
    model: str,
    temperature: float | None,
    stream: bool,
    seed: int | None = None,
    keep_alive: int | None = None,
):
    options: dict = {
        "temperature": settings.ollama_temperature if temperature is None else temperature,
        "num_predict": settings.ollama_max_tokens,
    }
    if seed is not None:
        options["seed"] = seed
    data = {
        "model": model or settings.ollama_model,
        "prompt": prompt,
        "stream": stream,
        "think": False,  # ignored by models without a thinking mode
        "keep_alive": settings.ollama_keep_alive if keep_alive is None else keep_alive,
        "options": options,
    }
    if system:  # without it the model keeps whatever SYSTEM its Modelfile defines
        data["system"] = system
    return data


async def generate(
    prompt: str,
    *,
    system: str = "",
    model: str = "",
    temperature: float | None = None,
    timeout: float | None = None,
) -> str:
    # The reply is consumed as a single JSON document - streaming would produce
    # newline-delimited JSON which the request manager cannot parse.
    data = _request_body(prompt, system, model, temperature, stream=False)
    timeout = timeout or settings.ollama_timeout
    result = await _requests.http("POST", f"{url()}/api/generate", data, timeout=timeout)
    return clean_response(result.get("response", ""))


class Generation:
    """A streaming /api/generate call. Ollama sends one JSON document per token, so
    progress can be reported while the model is still writing."""

    def __init__(self, on_progress: Callable[[str], None] | None = None):
        self._net = QNetworkAccessManager()
        self._reply: QNetworkReply | None = None
        self._buffer = b""
        self._text = ""
        self._on_progress = on_progress
        self._future: asyncio.Future[str] | None = None

    @property
    def text(self):
        return self._text

    async def run(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = "",
        temperature: float | None = None,
        timeout: float | None = None,
        seed: int | None = None,
        keep_alive: int | None = None,
    ) -> str:
        self._text = ""
        self._buffer = b""
        data = _request_body(prompt, system, model, temperature, True, seed, keep_alive)
        request = QNetworkRequest(QUrl(f"{url()}/api/generate"))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        # applies to inactivity, not to the total duration - a slow model is fine as long
        # as it keeps emitting tokens
        request.setTransferTimeout(int((timeout or settings.ollama_timeout) * 1000))

        self._future = asyncio.get_running_loop().create_future()
        reply = self._net.post(request, QByteArray(json.dumps(data).encode("utf-8")))
        assert reply is not None, "Failed to start Ollama request"
        self._reply = reply
        reply.readyRead.connect(self._read)
        reply.finished.connect(self._finish)
        return await self._future

    def cancel(self):
        if self._reply is not None and self._reply.isRunning():
            self._reply.abort()

    def _read(self):
        if self._reply is None:
            return
        self._buffer += self._reply.readAll().data()
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue  # partial or unexpected line, the next read may complete it
            if error := chunk.get("error"):
                # Ollama reports model-level failures (unknown model, out of memory) in
                # the stream itself rather than as an HTTP error
                if self._future is not None and not self._future.done():
                    self._future.set_exception(NetworkError(0, str(error), url()))
                self.cancel()
                return
            self._text += chunk.get("response", "")
        if self._on_progress is not None:
            self._on_progress(self._text)

    def _finish(self):
        reply, self._reply = self._reply, None
        if reply is None or self._future is None or self._future.done():
            return
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            self._future.cancel()
        elif reply.error() != QNetworkReply.NetworkError.NoError:
            self._future.set_exception(NetworkError.from_reply(reply))
        else:
            self._future.set_result(clean_response(self._text))
        reply.deleteLater()


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
    system: str = ""  # empty: keep the system prompt baked into the Ollama model
    model: str = ""  # empty: use the model selected in the settings


class Profiles:
    """Maps a base model family (SD XL, Illustrious, Krea 2, ...) to the system prompt
    which teaches the language model how prompts for that family are written."""

    _instance: Profiles | None = None

    default_path = plugin_dir / "presets" / "prompt_enhance.json"
    user_path = user_data_dir / "prompt_enhance.json"

    def __init__(self, data: dict):
        self._profiles = {
            key: Profile(
                key, value.get("name", key), value.get("system", ""), value.get("model", "")
            )
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


class PoolMode(Enum):
    """How a batch of prompts is produced before generating images."""

    variation = "variation"  # variations of the prompt that is already there
    random = "random"  # fresh scenes for a theme


_pool_instructions = {
    PoolMode.variation: (
        "Write ONE variation of the prompt below. Vary pose, setting, lighting and camera,"
        " but keep the same subject and style. Answer with the finished prompt only."
    ),
    PoolMode.random: (
        "Write ONE image prompt for the theme below. Invent the scene freely - subject"
        " details, setting, lighting and camera are yours to choose. Answer with the"
        " finished prompt only."
    ),
}


def build_pool_prompt(mode: PoolMode, base: str, avoid: list[str] | None = None) -> str:
    label = "Prompt" if mode is PoolMode.variation else "Theme"
    text = f"{_pool_instructions[mode]}\n\n{label}:\n{base}"
    if avoid:
        # Without this the model repeats itself almost verbatim across a batch, even
        # with a different seed each time.
        previous = "\n".join(f"- {a}" for a in avoid)
        text += (
            "\n\nYou already wrote the following. Write something clearly different"
            f" this time:\n{previous}"
        )
    return text


def build_prompt(task: EnhanceTask, prompt: str, count: int = 4, instruction: str = "") -> str:
    task_text = _task_instructions[task].format(count=count, instruction=instruction)
    if not prompt.strip():
        if task is EnhanceTask.instruct:
            # nothing to modify - treat the instruction itself as the idea to write about
            rewrite = _task_instructions[EnhanceTask.rewrite]
            return f"{rewrite}\n\nPrompt:\n{instruction}"
        return "The user did not provide a prompt. Invent an interesting image prompt from scratch."
    return f"{task_text}\n\nPrompt:\n{prompt}"
