"""One call interface, two backends.

Local uses the *native* `ollama` package rather than its OpenAI-compatible
shim: qwen3.5:4b is a thinking model (confirmed via `ollama show qwen3.5:4b`
-> Capabilities: thinking) and needs `think=False` or its reasoning trace
eats num_predict and the real answer gets truncated. Whether that param
reliably passes through /v1/chat/completions as extra_body is unverified
and not worth gambling on — see doc/PLAN.md's Day-1 plan notes. Both
backends expose the same `.chat(messages, **opts) -> (text, usage)` so
call sites don't care which one they're talking to.
"""
import time

import ollama
from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src import config


class OllamaClient:
    def __init__(self, model=None):
        self.model = model or config.OLLAMA_MODEL

    def chat(self, messages, temperature=config.TEMPERATURE, num_predict=config.NUM_PREDICT,
              num_ctx=config.NUM_CTX, think=False):
        t0 = time.time()
        resp = ollama.chat(
            model=self.model,
            think=think,
            messages=messages,
            options={"temperature": temperature, "num_ctx": num_ctx, "num_predict": num_predict},
        )
        latency = time.time() - t0
        text = resp["message"]["content"]
        usage = {
            "prompt_tokens": resp.get("prompt_eval_count"),
            "completion_tokens": resp.get("eval_count"),
            "latency_s": latency,
        }
        return text, usage


class DotBlueClient:
    """dotBlue (PSU) ignores the OpenAI SDK's default stream=False and always
    returns Server-Sent-Events chunks regardless (confirmed empirically: a
    non-streaming create() call comes back as a raw 'data: {...}' text blob
    that the SDK can't parse, surfacing as `resp` being a plain str instead
    of a ChatCompletion object). Requesting stream=True explicitly and
    accumulating deltas — with stream_options={"include_usage": True} for
    the final usage chunk — works reliably; this is the only way to reach
    dotBlue from this SDK.
    """

    def __init__(self, model=None):
        self.model = model or config.DOTBLUE_MODEL
        self._client = OpenAI(base_url=config.DOTBLUE_BASE_URL, api_key=config.DOTBLUE_API_KEY, timeout=30.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    def _call(self, messages, temperature, max_tokens):
        stream = self._client.chat.completions.create(
            model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens,
            stream=True, stream_options={"include_usage": True},
        )
        text, usage = "", None
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text += chunk.choices[0].delta.content
            if getattr(chunk, "usage", None):
                usage = chunk.usage
        return text, usage

    def chat(self, messages, temperature=config.TEMPERATURE, num_predict=config.NUM_PREDICT, **_ignored):
        t0 = time.time()
        text, usage = self._call(messages, temperature, num_predict)
        latency = time.time() - t0
        usage_dict = {
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "latency_s": latency,
        }
        return text, usage_dict


def get_llm(provider="local", model=None):
    if provider == "local":
        return OllamaClient(model=model)
    if provider == "api":
        return DotBlueClient(model=model)
    raise ValueError(f"unknown provider: {provider!r} (expected 'local' or 'api')")
