#!/usr/bin/env python3
"""Smoke-test the LLM_DECOMPILE transport before spending a full run on it.

Runs the SAME code path the pipeline uses (ida_llm_utils.call_llm_text ->
OpenAI-compatible chat.completions), so a pass here means the preprocessors'
LLM fallback will work, not just that the key is valid.

Three stages, cheapest first:
  1. tiny   - is the key/base_url/model id accepted at all (a few tokens)
  2. real   - one realistic LLM_DECOMPILE payload (a reference YAML, ~12 KB)
  3. burst  - 5 real calls back to back, to expose free-tier rate limits

Usage:
  export LLM_APIKEY=...            # or CS2VIBE_LLM_APIKEY
  export LLM_MODEL=glm-4.7-flash   # or CS2VIBE_LLM_MODEL
  export LLM_BASEURL=https://api.z.ai/api/paas/v4
  uv run test_llm_setup.py                 # stages 1 and 2
  uv run test_llm_setup.py -burst          # all three
"""

import argparse
import os
import sys
import time
from pathlib import Path

from ida_llm_utils import call_llm_text_sync

REPO = Path(__file__).resolve().parent
PROMPT = REPO / "ida_preprocessor_scripts" / "prompt" / "call_llm_decompile.md"
# One mid-sized reference block: representative of what a real spec sends.
REFERENCE = REPO / "ida_preprocessor_scripts" / "references" / "engine" / "CDemoPlayer_Pause.linux.yaml"


def _env(*names):
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _call(model, api_key, base_url, messages, label):
    started = time.monotonic()
    try:
        text = call_llm_text_sync(
            model=model,
            messages=messages,
            api_key=api_key,
            base_url=base_url,
        )
    except Exception as exc:  # noqa: BLE001 - the failure text is the whole point
        elapsed = time.monotonic() - started
        print(f"  {label}: FAIL after {elapsed:.1f}s")
        print(f"    {type(exc).__name__}: {exc}")
        return None
    elapsed = time.monotonic() - started
    print(f"  {label}: ok in {elapsed:.1f}s, {len(text)} chars back")
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-burst", action="store_true", help="also run 5 back-to-back calls (rate-limit probe)")
    parser.add_argument("-show", action="store_true", help="print the model's full reply")
    args = parser.parse_args()

    api_key = _env("LLM_APIKEY", "CS2VIBE_LLM_APIKEY")
    model = _env("LLM_MODEL", "CS2VIBE_LLM_MODEL")
    base_url = _env("LLM_BASEURL", "CS2VIBE_LLM_BASEURL")

    if not api_key:
        print("LLM_APIKEY (or CS2VIBE_LLM_APIKEY) is not set — nothing to test.")
        return 2
    if not model:
        print("LLM_MODEL (or CS2VIBE_LLM_MODEL) is not set. Do not rely on the gpt-4o default.")
        return 2

    print(f"model    : {model}")
    print(f"base_url : {base_url or '(OpenAI default)'}")
    print(f"api_key  : {api_key[:6]}...{api_key[-4:]} ({len(api_key)} chars)")
    print()

    print("stage 1 — transport")
    if _call(model, api_key, base_url, [{"role": "user", "content": "Reply with exactly: OK"}], "tiny") is None:
        print("\nStop here: the key, the model id or the base_url is wrong.")
        print("A 404 usually means the model id does not exist on this account;")
        print("a 401 means the key; a 400 mentioning 'reasoning_effort' means this")
        print("provider rejects that field (ida_llm_utils always sends it).")
        return 1

    print("\nstage 2 — realistic LLM_DECOMPILE payload")
    if not PROMPT.exists() or not REFERENCE.exists():
        print(f"  skipped: missing {PROMPT if not PROMPT.exists() else REFERENCE}")
        return 0
    prompt_text = PROMPT.read_text(encoding="utf-8")
    reference_text = REFERENCE.read_text(encoding="utf-8")
    body = (
        prompt_text.replace("{reference_blocks}", reference_text)
        .replace("{target_blocks}", reference_text)
        .replace("{symbol_name_list}", "CDemoPlayer_Pause")
    )
    print(f"  payload: {len(body)} chars (~{len(body)//4} tokens)")
    text = _call(model, api_key, base_url, [{"role": "user", "content": body}], "real")
    if text is None:
        print("\nThe transport works but this payload failed — likely a context-length")
        print("or rate limit on this tier. Try a paid tier (glm-5.3-flash).")
        return 1
    looks_like_yaml = any(key in text for key in ("found_vcall", "found_call", "found_gv", "found_struct_offset"))
    print(f"  result shape: {'YAML with the expected keys' if looks_like_yaml else 'NOT the expected YAML keys'}")
    if args.show or not looks_like_yaml:
        print("  --- reply ---")
        print("  " + "\n  ".join(text.splitlines()[:40]))

    if args.burst:
        print("\nstage 3 — 5 back-to-back calls (rate-limit probe)")
        failures = 0
        for index in range(5):
            if _call(model, api_key, base_url, [{"role": "user", "content": body}], f"call {index + 1}") is None:
                failures += 1
        if failures:
            print(f"  {failures}/5 failed — this tier will throttle a full run.")
        else:
            print("  5/5 ok — no throttling at this rate.")

    print("\nVerdict: this model works on the pipeline's own code path." if looks_like_yaml
          else "\nVerdict: transport ok, but output shape is wrong — the pipeline would retry, then fall back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
