"""
qwen_client.py: a small, reusable client for a Qwen model (or any model) served by Ollama.

Everything that changes between uses (model, settings, prompts, output schema) is passed in
from outside. The module itself only handles talking to Ollama: requests, JSON output,
retries, caching, batching and timing. Standard library only, no installs needed.

Quick start
-----------
    from qwen_client import QwenClient, QwenConfig

    qwen = QwenClient(QwenConfig(model="qwen3.5:4b"))
    qwen.check()                                    # clear error if Ollama or the model is missing

    r = qwen.ask("Name one city in the Philippines.")
    print(r.text, r.seconds)

    r = qwen.ask_json("Is 'Shore360 - Parallaxx' naming a client?",
                      system="Answer as JSON.", schema={"type": "object",
                      "properties": {"client": {"type": "string"}}, "required": ["client"]})
    print(r.data["client"])

    results = qwen.map(rows, prompt="Company text: {Company}", schema=..., system=...)

Requires Ollama running locally (`ollama serve`, or the Ollama desktop app) and the model
pulled once (`ollama pull qwen3.5:4b`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Iterable


class QwenError(RuntimeError):
    """Raised for connection problems, missing models, bad responses and unparseable JSON."""


@dataclass
class QwenConfig:
    """All the knobs. Anything left as None uses the model's own default."""
    model: str = "qwen3.5:4b"
    host: str = "http://localhost:11434"

    # Generation settings
    num_ctx: int | None = 4096          # context window in tokens; bigger = more RAM
    temperature: float | None = None    # None = model default; 0 for most repeatable answers
    seed: int | None = None             # fix for repeatable runs
    num_predict: int | None = None      # max tokens to generate; None = no cap
    top_p: float | None = None
    num_thread: int | None = None       # CPU threads; None lets Ollama decide
    think: bool | None = False          # False = skip step-by-step reasoning (much faster on CPU);
                                        # True = allow it; None = don't send the setting at all
    extra_options: dict = field(default_factory=dict)   # any other Ollama option, passed through

    # Behaviour
    timeout: float = 300                # seconds per request (CPU can be slow)
    max_retries: int = 2                # retries on timeouts / connection drops / bad JSON
    retry_wait: float = 3               # seconds between retries, doubled each time
    keep_alive: str | None = "15m"      # how long Ollama keeps the model loaded between calls
    cache_path: str | None = None       # JSONL file; repeated identical requests are free
    verbose: bool = True                # print progress during map()

    def options(self) -> dict:
        opts = {"num_ctx": self.num_ctx, "temperature": self.temperature, "seed": self.seed,
                "num_predict": self.num_predict, "top_p": self.top_p, "num_thread": self.num_thread}
        opts = {k: v for k, v in opts.items() if v is not None}
        opts.update(self.extra_options)
        return opts


@dataclass
class QwenResult:
    """One answer. `data` holds the parsed JSON when ask_json/map with a schema was used."""
    text: str = ""
    data: Any = None
    thinking: str = ""
    seconds: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    tokens_per_second: float = 0.0
    cached: bool = False
    error: str = ""                      # filled instead of raising when map(on_error="record")

    @property
    def ok(self) -> bool:
        return not self.error


class QwenClient:
    def __init__(self, config: QwenConfig | None = None, **overrides):
        """QwenClient(QwenConfig(...)) or QwenClient(model="qwen3.5:4b", temperature=0)."""
        self.config = config or QwenConfig()
        for k, v in overrides.items():
            if not hasattr(self.config, k):
                raise TypeError(f"Unknown setting '{k}'. Valid: {list(asdict(self.config))}")
            setattr(self.config, k, v)
        self._cache: dict[str, dict] = {}
        self._think_supported = True
        if self.config.cache_path and os.path.exists(self.config.cache_path):
            with open(self.config.cache_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        self._cache[rec["key"]] = rec["result"]
                    except (json.JSONDecodeError, KeyError):
                        continue

    # ------------------------------------------------------------------ setup checks
    def check(self) -> None:
        """Confirm Ollama is reachable and the model is pulled. Raises QwenError with the fix."""
        try:
            tags = self._request("GET", "/api/tags", timeout=10)
        except QwenError as e:
            raise QwenError(f"Can't reach Ollama at {self.config.host}. Start it with `ollama serve` "
                            f"(or open the Ollama app). Details: {e}") from None
        names = {m.get("name", "") for m in tags.get("models", [])}
        wanted = self.config.model if ":" in self.config.model else self.config.model + ":latest"
        if wanted not in names:
            have = ", ".join(sorted(names)) or "none"
            raise QwenError(f"Model '{self.config.model}' isn't pulled. Run `ollama pull {self.config.model}`. "
                            f"Models available: {have}")
        if self.config.verbose:
            print(f"Ollama OK, model {self.config.model} ready.")

    # ------------------------------------------------------------------ single calls
    def chat(self, messages: list[dict], schema: dict | str | None = None) -> QwenResult:
        """Low-level call with a full message list: [{'role': 'system'|'user'|'assistant', 'content': ...}].
        schema: None for free text, "json" for any JSON, or a JSON Schema dict for a fixed shape."""
        body = {"model": self.config.model, "messages": messages, "stream": False,
                "options": self.config.options()}
        if schema is not None:
            body["format"] = schema
        if self.config.think is not None and self._think_supported:
            body["think"] = self.config.think
        if self.config.keep_alive is not None:
            body["keep_alive"] = self.config.keep_alive

        key = self._key(body)
        if key in self._cache:
            return QwenResult(**{**self._cache[key], "cached": True})

        wait, last_err = self.config.retry_wait, None
        for attempt in range(self.config.max_retries + 1):
            try:
                t0 = time.perf_counter()
                out = self._request("POST", "/api/chat", body)
                result = self._to_result(out, time.perf_counter() - t0, parse_json=schema is not None)
                self._store(key, result)
                return result
            except QwenError as e:
                msg = str(e)
                if "does not support thinking" in msg and "think" in body:
                    self._think_supported = False          # model has no thinking mode: drop the flag
                    body.pop("think")
                    continue
                if "not found" in msg and "model" in msg.lower():
                    raise QwenError(f"Model '{self.config.model}' not found. Run `ollama pull {self.config.model}`.") from None
                last_err = e
                if attempt < self.config.max_retries:
                    time.sleep(wait); wait *= 2
        raise QwenError(f"Failed after {self.config.max_retries + 1} attempts: {last_err}")

    def ask(self, prompt: str, system: str | None = None) -> QwenResult:
        """Free-text answer to one prompt."""
        return self.chat(self._messages(prompt, system))

    def ask_json(self, prompt: str, system: str | None = None, schema: dict | None = None) -> QwenResult:
        """JSON answer to one prompt. With a schema, Ollama constrains the output to that shape;
        without one, any valid JSON is accepted. Parsed result is in .data."""
        return self.chat(self._messages(prompt, system), schema=schema or "json")

    # ------------------------------------------------------------------ batches
    def map(self, items: Iterable[Any], prompt: str | Callable[[Any], str], system: str | None = None,
            schema: dict | str | None = None, on_error: str = "record",
            progress_every: int = 5) -> list[QwenResult]:
        """Run one prompt per item and return results in the same order.

        prompt: a template like "Company: {Company}\\nIndustry: {Industry}" filled from each item
                (dict keys, or {item} for plain strings), or a function item -> prompt text.
        schema: None for text, "json" for any JSON, or a JSON Schema dict.
        on_error: "record" puts the error message in result.error and carries on; "raise" stops.
        """
        items = list(items)
        build = prompt if callable(prompt) else (lambda it: self.fill(prompt, it))
        results, t_start, done_live = [], time.perf_counter(), 0
        for i, item in enumerate(items, 1):
            try:
                text = build(item)
                r = self.chat(self._messages(text, system), schema=schema)
            except (QwenError, KeyError, IndexError, ValueError) as e:
                if on_error == "raise":
                    raise
                r = QwenResult(error=f"{type(e).__name__}: {e}")
            results.append(r)
            if not r.cached and r.ok:
                done_live += 1
            if self.config.verbose and (i % progress_every == 0 or i == len(items)):
                elapsed = time.perf_counter() - t_start
                per = elapsed / done_live if done_live else 0
                left = per * (len(items) - i)
                errs = sum(not x.ok for x in results)
                print(f"  {i}/{len(items)} done | {per:.1f}s per new item | ~{left/60:.1f} min left"
                      + (f" | {errs} errors" if errs else ""), file=sys.stderr, flush=True)
        return results

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def fill(template: str, item: Any) -> str:
        """Fill {placeholders} from a dict (or pandas row), or {item} for anything else.
        Literal braces in the template must be doubled: {{ and }}."""
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        if isinstance(item, dict):
            return template.format(**{str(k): ("" if v is None else v) for k, v in item.items()})
        return template.format(item=item)

    @staticmethod
    def _messages(prompt: str, system: str | None) -> list[dict]:
        msgs = [{"role": "system", "content": system}] if system else []
        return msgs + [{"role": "user", "content": prompt}]

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        url = self.config.host.rstrip("/") + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.config.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except json.JSONDecodeError:
                pass
            raise QwenError(f"Ollama returned {e.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise QwenError(f"{type(e).__name__}: {getattr(e, 'reason', e)}") from None

    def _to_result(self, out: dict, seconds: float, parse_json: bool) -> QwenResult:
        msg = out.get("message", {})
        text = msg.get("content", "")
        n_out = out.get("eval_count", 0)
        gen_s = out.get("eval_duration", 0) / 1e9
        result = QwenResult(text=text, thinking=msg.get("thinking", ""), seconds=round(seconds, 2),
                            prompt_tokens=out.get("prompt_eval_count", 0), output_tokens=n_out,
                            tokens_per_second=round(n_out / gen_s, 1) if gen_s else 0.0)
        if parse_json:
            result.data = self.parse_json(text)
        return result

    @staticmethod
    def parse_json(text: str) -> Any:
        """Parse JSON, tolerating ```json fences or stray text around the object."""
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            m = re.search(r"(\{.*\}|\[.*\])", cleaned, re.S)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
        raise QwenError(f"Model did not return valid JSON: {text[:200]!r}")

    def _key(self, body: dict) -> str:
        stable = {k: v for k, v in body.items() if k != "keep_alive"}
        return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()

    def _store(self, key: str, result: QwenResult) -> None:
        if not self.config.cache_path:
            return
        rec = asdict(result); rec.pop("cached"); rec.pop("error")
        self._cache[key] = rec
        with open(self.config.cache_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "result": rec}) + "\n")
