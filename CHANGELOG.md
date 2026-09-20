# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-09-20

### Security & Hardening
- **Timing-Safe Key Verification:** Migrated API key authentication to `secrets.compare_digest` across all endpoints to eliminate timing-attack vulnerabilities.
- **Public Bind Protection:** Prohibited binding to public interfaces (`0.0.0.0` or non-loopback addresses) when using the default (`sk-notionchat`) or an empty API key. The server halts on startup if misconfigured.
- **Atomic File Writes & Permissions:** Secured account credentials (`notion_account.json`) and thread state files (`threads/*.json`) with atomic write patterns and POSIX `0600` file permissions.
- **Error Sanitization:** Sanitized upstream HTTP error messages and raw response bodies returned from Notion AI endpoints to prevent internal credential or header leakage.
- **Experimental Tools Gating:** Gated IDE agent and tool translation behind `NOTIONCHAT_EXPERIMENTAL_TOOLS` (disabled by default) to eliminate unsolicited tool generation.
- **Tool Allowlist & Schema Validation:** Enforced strict client tool allowlists and JSON schema validation (including required properties) for all model tool calls, preventing prompt-injected or hallucinated tool execution.

### Features & API Enhancements
- **OpenAI Responses API (`POST /v1/responses`):** Added support for the OpenAI Responses API contract, translating between Responses and Chat Completions formats with `"completed"` status semantics.
- **Readiness Probe (`GET /readyz`):** Added a `/readyz` health endpoint that returns HTTP 200 when Notion credentials and account state are loaded and ready, or HTTP 503 if not configured.
- **Stale Cache Fallback for Models:** Configured `GET /v1/models` to gracefully return cached models when upstream Notion requests encounter temporary network errors, falling back to HTTP 502 only if no cache exists.
- **Standard Append-Only Streaming:** Updated SSE streaming to emit standard append-only text deltas by default. Added opt-in support for replacement markers via the `X-Allow-Stream-Replace: 1` request header.
- **Standardized Error Events in Streams:** Updated streaming error handlers to emit standard OpenAI error JSON objects prior to terminating with `data: [DONE]\n\n`.

### Concurrency & Lifecycle
- **Per-Session Async Locks:** Implemented per-session serialization locks (`_session_locks`) to eliminate race conditions when concurrent requests target the same session or thread.
- **Bounded TTL Thread Reuse Pool:** Added a 1-hour time-to-live (`TTL = 3600s`) and bounded capacity (`MAX_REUSE_POOL_SIZE = 50`) to the thread reuse pool to prevent memory leaks and stale conversation state.
- **FastAPI Lifespan Management:** Replaced deprecated startup event handlers with modern FastAPI lifespan management, cleanly initializing the account state on startup.

### Quality, Tooling & CI
- **Comprehensive Test Suite:** Added 56+ automated unit and integration tests covering security, concurrency, streaming, tools, models, account management, and API contracts.
- **Modern Tooling & Linting:** Standardized on Ruff (linting and formatting) and Pyright (type checking) with 0 errors across the codebase.
- **CI & Dependency Management:** Added GitHub Actions CI workflow covering multi-check testing and linting, alongside Dependabot configuration for weekly dependency and action updates.
- **Unified Port & CLI:** Standardized default port across all components and documentation to `1994`. Fixed `.env` writing in setup CLI to preserve comments and unmanaged settings.
