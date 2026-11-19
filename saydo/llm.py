"""Model-agnostic LLM access with structured (JSON-schema) output.

Backends
--------
openai      Any OpenAI-compatible /v1/chat/completions server:
            9router (http://localhost:20128/v1), LM Studio (http://localhost:1234/v1),
            Ollama (http://localhost:11434/v1), vLLM, OpenRouter, ...
claude-cli  The local Claude Code CLI in headless mode (`claude -p --json-schema`),
            which uses whatever login the CLI already has (e.g. a Claude subscription).

Every call goes through an on-disk cache keyed by (backend, model, prompt, schema),
so interrupted sweeps resume for free and re-analysis never re-queries a model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

CACHE_DIR = Path(os.environ.get("SAYDO_CACHE", ".cache/llm"))


class LLMError(RuntimeError):
    pass


@dataclass
class Stats:
    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, getattr(self, k) + v)

    def as_dict(self):
        return {k: getattr(self, k) for k in ("calls", "cache_hits", "failures", "seconds", "prompt_tokens", "completion_tokens")}


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # first balanced {...}
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise LLMError(f"no JSON object in model output: {text[:200]!r}")


def _validate(obj: dict, schema: dict) -> dict:
    """Light validation: required keys present and enum values legal. Coerces case of enums."""
    if not isinstance(obj, dict):
        raise LLMError("output is not an object")
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in obj:
            raise LLMError(f"missing key {key!r}")
    for key, spec in props.items():
        if key in obj and "enum" in spec:
            val = obj[key]
            if val not in spec["enum"]:
                lowered = {str(e).lower(): e for e in spec["enum"]}
                if str(val).lower() in lowered:
                    obj[key] = lowered[str(val).lower()]
                else:
                    raise LLMError(f"{key}={val!r} not in {spec['enum']}")
        if key in obj and spec.get("type") == "number" and isinstance(obj[key], str):
            obj[key] = float(obj[key])
    return obj


class LLM:
    """Base class: subclasses implement `_raw(system, user, schema) -> (dict, usage)`."""

    backend = "base"

    def __init__(self, model: str, cache: bool = True, retries: int = 3, temperature: float | None = None):
        self.model = model
        self.cache = cache
        self.retries = retries
        self.temperature = temperature
        self.stats = Stats()

    @property
    def name(self) -> str:
        return f"{self.backend}:{self.model}"

    def _key(self, system, user, schema) -> Path:
        h = hashlib.sha256(json.dumps([self.name, self.temperature, system, user, schema], sort_keys=True).encode()).hexdigest()
        return CACHE_DIR / h[:2] / f"{h}.json"

    def complete_json(self, system: str, user: str, schema: dict, sample: int = 0) -> dict:
        """Return a dict that satisfies `schema`. `sample` > 0 forces distinct cache entries
        for repeated stochastic samples of the same prompt."""
        key = self._key(system, user + (f"\n<!--sample {sample}-->" if sample else ""), schema)
        if self.cache and key.exists():
            self.stats.add(cache_hits=1)
            return json.loads(key.read_text())["output"]
        err = None
        for attempt in range(self.retries):
            t0 = time.time()
            try:
                out, usage = self._raw(system, user, schema)
                out = _validate(out, schema)
                self.stats.add(calls=1, seconds=time.time() - t0, **usage)
                if self.cache:
                    key.parent.mkdir(parents=True, exist_ok=True)
                    tmp = key.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
                    tmp.write_text(json.dumps({"model": self.name, "output": out}))
                    tmp.replace(key)
                return out
            except (LLMError, httpx.HTTPError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as e:
                err = e
                time.sleep(min(2 ** attempt, 20))
        self.stats.add(failures=1)
        raise LLMError(f"{self.name} failed after {self.retries} attempts: {err}")

    def _raw(self, system, user, schema):  # pragma: no cover
        raise NotImplementedError


class OpenAICompatLLM(LLM):
    backend = "openai"

    def __init__(self, model, base_url=None, api_key_env="OPENAI_API_KEY", timeout=180.0, **kw):
        super().__init__(model, **kw)
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "http://localhost:20128/v1").rstrip("/")
        key = os.environ.get(api_key_env, "")
        self.headers = {"content-type": "application/json"}
        if key:
            self.headers["authorization"] = f"Bearer {key}"
        self.client = httpx.Client(timeout=timeout)
        self.schema_mode = "json_schema"  # downgraded automatically if the server rejects it

    def _payload(self, system, user, schema):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        body = {"model": self.model, "messages": msgs, "stream": False}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.schema_mode == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "decision", "strict": True, "schema": schema}}
        else:
            msgs[-1]["content"] = (
                user + "\n\nRespond with ONLY a JSON object (no prose, no code fence) matching this JSON Schema:\n" + json.dumps(schema)
            )
        return body

    def _raw(self, system, user, schema):
        r = self.client.post(f"{self.base_url}/chat/completions", headers=self.headers, json=self._payload(system, user, schema))
        if r.status_code == 400 and self.schema_mode == "json_schema" and "response_format" in r.text.lower():
            self.schema_mode = "prompt"
            r = self.client.post(f"{self.base_url}/chat/completions", headers=self.headers, json=self._payload(system, user, schema))
        if r.status_code in (401, 403):
            raise SystemExit(f"auth error from {self.base_url}: {r.text[:200]} (set the key env var, e.g. --api-key-env)")
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        if isinstance(content, list):  # some servers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        try:
            out = _extract_json(content)
        except LLMError:
            if self.schema_mode == "json_schema":  # server accepted the schema but ignored it
                self.schema_mode = "prompt"
            raise
        u = data.get("usage") or {}
        return out, {"prompt_tokens": u.get("prompt_tokens", 0) or 0, "completion_tokens": u.get("completion_tokens", 0) or 0}


class ClaudeCLILLM(LLM):
    backend = "claude-cli"

    def __init__(self, model="sonnet", binary=None, timeout=300, **kw):
        super().__init__(model, **kw)
        self.cmd = shlex.split(binary or os.environ.get("SAYDO_CLAUDE_BIN", "claude"))
        self.timeout = timeout
        self.workdir = tempfile.mkdtemp(prefix="saydo-cli-")  # no project CLAUDE.md / settings leak in

    def _raw(self, system, user, schema):
        cmd = self.cmd + [
            "-p", user, "--output-format", "json", "--json-schema", json.dumps(schema),
            "--system-prompt", system, "--tools", "", "--strict-mcp-config",
            "--no-session-persistence", "--model", self.model,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, cwd=self.workdir)
        if p.returncode != 0:
            raise LLMError(f"claude CLI exit {p.returncode}: {(p.stderr or p.stdout)[:300]}")
        data = json.loads(p.stdout)
        if data.get("is_error"):
            raise LLMError(f"claude CLI error: {str(data.get('result'))[:300]}")
        out = data.get("structured_output") or _extract_json(data.get("result", ""))
        u = data.get("usage") or {}
        return out, {"prompt_tokens": (u.get("input_tokens", 0) or 0) + (u.get("cache_read_input_tokens", 0) or 0)
                     + (u.get("cache_creation_input_tokens", 0) or 0), "completion_tokens": u.get("output_tokens", 0) or 0}


def make_llm(spec: str, base_url: str | None = None, api_key_env: str = "OPENAI_API_KEY", temperature: float | None = None) -> LLM:
    """`spec` is `<backend>:<model>`; a bare model name means the OpenAI-compatible backend.

    Examples: `openai:ocz/claude-sonnet-4-6`, `ocz/gpt-5.4-mini`, `claude-cli:sonnet`.
    """
    backend, _, model = spec.partition(":") if spec.split(":", 1)[0] in ("openai", "claude-cli") else ("openai", ":", spec)
    if backend == "claude-cli":
        return ClaudeCLILLM(model=model, temperature=temperature)
    return OpenAICompatLLM(model=model, base_url=base_url, api_key_env=api_key_env, temperature=temperature)
