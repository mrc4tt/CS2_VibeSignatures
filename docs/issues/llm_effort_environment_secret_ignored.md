# Bug: GitHub Actions LLM effort silently falls back to `medium`

## Status

Open. Repository-side root cause identified on 2026-07-17 while investigating
PR #577 validation runs. The exact GitHub environment configuration that triggered
the affected run still needs confirmation.

Affected run:

- <https://github.com/HLND2T/CS2_VibeSignatures/actions/runs/29579900577>

The `win64` GitHub environment was expected to provide the environment secret
`CS2VIBE_LLM_EFFORT=high`, but the affected run's LLM requests used reasoning
effort `medium`. The masked Actions log cannot verify which literal value was
available when the job started.

## Summary

The PR self-runner workflow exposes `secrets.CS2VIBE_LLM_EFFORT` as the job-level
environment variable `CS2VIBE_LLM_EFFORT`. The analyzer CLI reads that environment
variable and forwards its normalized value through preprocessing to the LLM
transport.

The `fake_as=codex` transport does not ignore a valid `high` value. Its request
template already contains `reasoning.effort: high`, and the transport deliberately
overwrites that template field with the normalized runtime effort. Repository tests
confirm that explicitly passing `high` produces an outgoing `/responses` body with
`reasoning.effort: high`.

The observed `medium` therefore means the value was already missing, blank, or
`medium` before the Codex transport constructed the request. The repository silently
normalizes missing or blank input to `medium`, so an unavailable or incorrectly
scoped GitHub secret becomes a valid-looking medium-effort request instead of a
configuration failure.

## Expected Behavior

Given this GitHub environment secret:

```text
CS2VIBE_LLM_EFFORT=high
```

every preprocessing and vcall-finder LLM request initiated by the workflow should
contain the equivalent of:

```json
{
  "reasoning": {
    "effort": "high"
  }
}
```

For the Chat Completions transport, the corresponding request field should be:

```json
{
  "reasoning_effort": "high"
}
```

## Actual Behavior

The effective request uses:

```json
{
  "reasoning": {
    "effort": "medium"
  }
}
```

This is indistinguishable from the default produced when the configured value is
`None` or blank.

## Intended Configuration Path

The expected value flow is:

```text
GitHub environment secret
  -> workflow job env: CS2VIBE_LLM_EFFORT
  -> ida_analyze_bin.py parse_args().llm_effort
  -> analyze_all_modules(..., llm_effort=...)
  -> preprocess_skill(..., llm_effort=...)
  -> llm_config["effort"]
  -> call_llm_decompile(..., effort=...)
  -> call_llm_text(..., effort=...)
  -> outgoing request body
```

Relevant files:

- `.github/workflows/pr-self-runner.yml:27-34`
- `.github/workflows/build-on-self-runner.yml:86-97`
- `ida_analyze_bin.py:1261-1271`
- `ida_analyze_bin.py:1351-1355`
- `ida_analyze_bin.py:1447`
- `ida_skill_preprocessor.py:104-168`
- `ida_llm_decompile.py:795-857`
- `ida_llm_utils.py:263-292`
- `ida_llm_utils.py:377-406`
- `codex_faker.json:153-156`
- `tests/test_ida_llm_utils.py:287-311`

## Confirmed Findings

- Both self-runner workflows map `secrets.CS2VIBE_LLM_EFFORT` to the job-level
  `CS2VIBE_LLM_EFFORT` environment variable, but neither workflow validates that the
  resolved value is non-blank.
- `_parse_optional_llm_effort(...)` accepts `high` unchanged and converts `None` or
  blank text to `medium`.
- A local environment-only reproduction with `CS2VIBE_LLM_EFFORT=high` and no
  explicit `-llm_effort` argument resolves `args.llm_effort` to `high`.
- `_prepare_llm_decompile_request(...)` reads `llm_config["effort"]` and forwards it
  to `call_llm_decompile(...)`.
- `call_llm_text(..., fake_as="codex")` forwards the normalized effort to the
  Codex-compatible `/responses` transport.
- `codex_faker.json` contains `reasoning.effort: high`, but
  `_call_llm_text_via_codex_http(...)` always replaces that field with the normalized
  runtime value. A missing input therefore changes the template's `high` to the
  fallback `medium`.
- The Codex HTTP transport test captures the actual JSON request body and confirms
  that passing `effort="high"` sends `reasoning.effort: high`.

The Actions log masks the environment value as `***`, so it does not prove that the
analyzer process received the literal value `high`. It also does not distinguish an
outdated value from a secret resolved from the wrong scope. The affected run lacks a
non-sensitive startup diagnostic showing the normalized effort.

## Root Cause

The repository-side root cause is a fail-open configuration contract:

1. The workflow injects `secrets.CS2VIBE_LLM_EFFORT` without checking whether it
   resolved to a non-blank value.
2. The CLI treats a missing or blank value as the legitimate local default
   `medium`.
3. The `fake_as=codex` transport then overwrites the template's existing `high` with
   that normalized `medium` value.
4. No startup or request-construction diagnostic records where the effective value
   changed.

Consequently, any CI input that differs from the intended non-blank `high` value can
be silently converted into a syntactically valid medium-effort request. The
transport is behaving as implemented; it is exposing the earlier silent fallback.

The immediate external trigger for run `29579900577` cannot be uniquely determined
from the masked log. The remaining possibilities are that the secret was unavailable
to the `win64` environment at job start, was configured under a different scope or
as a variable instead of a secret, still had an older value, or resolved to the
literal value `medium`. If a future client-side capture shows `high` while the
provider reports `medium`, the configured gateway or provider becomes a separate
downstream investigation target.

## Investigation Targets

1. Confirm the secret is defined on the exact `win64` environment used by the job
   and was already set to `high` when the affected job started, rather than existing
   only as a repository variable, repository secret, or similarly named setting in
   another environment.
2. Fail the CI job before starting analysis when `CS2VIBE_LLM_EFFORT` is missing or
   blank.
3. Log the normalized effective effort after CLI parsing. This value is not
   sensitive and can safely be printed as `none`, `minimal`, `low`, `medium`,
   `high`, or `xhigh`.
4. Log the effective effort immediately before each `fake_as=codex` transport call.
5. Add an integration-style test that sets `CS2VIBE_LLM_EFFORT=high`, calls
   `parse_args()`, and asserts the captured `/responses` request body uses `high`
   without an explicit `-llm_effort` CLI argument.
6. Only investigate the configured gateway or provider when the client-side request
   body is confirmed as `high` but downstream request metadata still reports
   `medium`.

## Recommended Fix Direction

- Fail early in both self-runner workflows when `CS2VIBE_LLM_EFFORT` is missing or
  blank instead of silently defaulting to `medium` for CI runs that require an
  explicitly configured effort.
- Print the non-secret normalized effort at analyzer startup and immediately before
  the Codex transport call.
- Keep `medium` as the local CLI default if desired, but make the CI configuration
  contract explicit and test it end to end.
- Do not rely on the `high` value embedded in `codex_faker.json` as a fallback. The
  runtime value intentionally overrides it, so the effective configuration must be
  validated before request construction.

An example startup diagnostic would be:

```text
LLM effort: high
```

It must report the effective normalized value without printing any API key, base
URL credentials, or other secret material.

## Acceptance Criteria

- A self-runner job using `CS2VIBE_LLM_EFFORT=high` logs `LLM effort: high`.
- A client-side capture confirms the outgoing `/responses` body contains
  `reasoning.effort: high`.
- No explicit `-llm_effort high` workaround is required in the workflow command.
- Missing or blank CI configuration fails before analysis with a clear diagnostic
  instead of silently falling back to `medium`.
- Tests cover environment-only configuration for both supported LLM transports,
  including the final JSON body for `fake_as=codex`.
