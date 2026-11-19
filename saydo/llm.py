"""Model-agnostic LLM access with structured (JSON-schema) output.

Backends
--------
openai      Any OpenAI-compatible /v1/chat/completions server:
            9router (http://localhost:20128/v1), LM Studio (http://localhost:1234/v1),
            Ollama (http://localhost:11434/v1), vLLM, OpenRouter, ...
claude-cli  The local Claude Code CLI in headless mode (`claude -p --json-schema`),
            which uses whatever login the CLI already has (e.g. a Claude subscription).
opencode    The OpenCode CLI (`opencode run`), sandboxed with a tool-less agent; reaches every
            provider OpenCode is logged into (OpenCode Zen free models, claude-agent, Copilot, ...).

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


class QuotaExhausted(LLMError):
    """The provider's quota is used up for a long time; retrying now is pointless."""


_RESET = re.compile(r"reset after (?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?")
_QUOTA = ("free-limit", "Free usage limit", "FreeUsageLimitError", "insufficient_quota", "quota exceeded")


def _classify(err: Exception) -> float | None:
    """Seconds to wait before retrying (None = default backoff). Raises QuotaExhausted for long resets."""
    s = str(err)
    if any(q in s for q in _QUOTA):
        raise QuotaExhausted(s[:300])
    m = _RESET.search(s)
    if m and any(m.groups()):
        h, mi, se = (int(g) if g else 0 for g in m.groups())
        wait = h * 3600 + mi * 60 + se
        if wait > 600:
            raise QuotaExhausted(s[:300])
        return wait + 1
    return None


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

    def __init__(self, model: str, cache: bool = True, retries: int = 6, temperature: float | None = None):
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
            except QuotaExhausted:
                self.stats.add(failures=1)
                raise
            except (LLMError, httpx.HTTPError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as e:
                err = e
                try:
                    wait = _classify(e)
                except QuotaExhausted:
                    self.stats.add(failures=1)
                    raise
                time.sleep(wait if wait is not None else min(2 ** attempt, 30))
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
        # "json_schema" uses response_format; downgraded automatically to "prompt" (schema in the prompt) if the
        # server rejects it or returns nothing. Force with SAYDO_SCHEMA_MODE=prompt.
        self.schema_mode = os.environ.get("SAYDO_SCHEMA_MODE", "json_schema")

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
            if self.schema_mode == "json_schema":  # server accepted the schema but ignored/dropped it
                self.schema_mode = "prompt"
                return self._raw(system, user, schema)
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


OPENCODE_CONFIG = {
    "$schema": "https://opencode.ai/config.json",
    "permission": {"edit": "deny", "bash": "deny", "webfetch": "deny", "external_directory": "deny"},
    "agent": {
        "plain": {
            "mode": "primary",
            "description": "No tools; answer only.",
            "prompt": "Answer the user's message directly in the requested format. Never use tools.",
            "tools": {k: False for k in ("bash", "edit", "write", "read", "grep", "glob", "list", "patch",
                                         "todowrite", "todoread", "webfetch", "task")},
        }
    },
}


class OpenCodeLLM(LLM):
    """Calls models through the OpenCode CLI (`opencode run --format json`), e.g.
    `opencode/deepseek-v4.1-flash-free` or `claude-agent/sonnet` (Claude Code login).

    Safety: runs from an empty temp directory whose opencode.json defines a tool-less agent and denies
    edit/bash/web permissions; any reply containing a tool call is rejected. The system prompt is sent as
    the first block of the message (OpenCode's own agent prompt is a one-line "answer only" instruction).
    """

    backend = "opencode"

    def __init__(self, model, binary=None, timeout=300, **kw):
        super().__init__(model, **kw)
        self.cmd = shlex.split(binary or os.environ.get("SAYDO_OPENCODE_BIN", "opencode"))
        self.timeout = timeout
        self.workdir = tempfile.mkdtemp(prefix="saydo-opencode-")
        Path(self.workdir, "opencode.json").write_text(json.dumps(OPENCODE_CONFIG, indent=2))

    def _raw(self, system, user, schema):
        msg = (f"<system>\n{system}\n</system>\n\n{user}\n\n"
               "Respond with ONLY a JSON object (no prose, no code fence) matching this JSON Schema:\n" + json.dumps(schema))
        cmd = self.cmd + ["run", "--agent", "plain", "--format", "json", "--archived", "-m", self.model, msg]
        # OpenCode resolves its project (and opencode.json) from $PWD, not the process cwd.
        env = {**os.environ, "PWD": self.workdir}
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, cwd=self.workdir, env=env)
        texts, usage = [], {"prompt_tokens": 0, "completion_tokens": 0}
        for line in p.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            part = ev.get("part") or {}
            if ev.get("type") in ("tool_use", "tool") or part.get("type") == "tool":
                raise LLMError("model attempted a tool call; rejected")
            if ev.get("type") == "text" and part.get("text"):
                texts.append(part["text"])
            if ev.get("type") == "step_finish":
                tok = part.get("tokens") or {}
                usage["prompt_tokens"] += tok.get("input", 0) or 0
                usage["completion_tokens"] += (tok.get("output", 0) or 0) + (tok.get("reasoning", 0) or 0)
            if ev.get("type") == "error":
                raise LLMError(f"opencode error: {str(ev)[:300]}")
        if p.returncode != 0 and not texts:
            raise LLMError(f"opencode exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}")
        return _extract_json("".join(texts)), usage


def make_llm(spec: str, base_url: str | None = None, api_key_env: str = "OPENAI_API_KEY", temperature: float | None = None) -> LLM:
    """`spec` is `<backend>:<model>`; a bare model name means the OpenAI-compatible backend.

    Examples: `openai:cc/claude-sonnet-5`, `ag/gemini-3.8-flash-low`, `claude-cli:sonnet`,
    `opencode:opencode/deepseek-v4.1-flash-free`, `opencode:claude-agent/sonnet`.
    """
    backend, _, model = spec.partition(":") if spec.split(":", 1)[0] in ("openai", "claude-cli", "opencode") else ("openai", ":", spec)
    if backend == "claude-cli":
        return ClaudeCLILLM(model=model, temperature=temperature)
    if backend == "opencode":
        return OpenCodeLLM(model=model, temperature=temperature)
    return OpenAICompatLLM(model=model, base_url=base_url, api_key_env=api_key_env, temperature=temperature)
