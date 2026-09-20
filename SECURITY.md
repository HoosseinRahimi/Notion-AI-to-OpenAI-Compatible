# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.4.x   | :white_check_mark: |
| < 0.4.0 | :x:                |

## Reporting a Vulnerability

We take the security of NotionChat seriously. If you discover a vulnerability or security issue, please do **NOT** open a public issue.

Instead, please report security vulnerabilities privately:
- Through **GitHub Private Vulnerability Reporting** via the Security tab of the repository, or
- By contacting the maintainers directly via email or security disclosure channels listed in the repository profile.

Please include:
- A clear description of the vulnerability.
- Steps to reproduce or proof-of-concept (PoC) code/payloads.
- Impact assessment and potential threat scenario.

We will acknowledge receipt within 48 hours and work with you on a coordinated disclosure timeline and fix.

---

## Threat Model & Security Architecture

NotionChat is designed as a local or private proxy converting OpenAI-compatible API requests into Notion AI sessions via browser cookie authentication. Because browser cookies carry full account privileges, several security controls are enforced:

### 1. API Key Verification & Network Binding
- **Timing-Safe Comparison:** API bearer tokens are validated using `secrets.compare_digest` to prevent timing-attack side channels.
- **Public Bind Protection:** Binding to non-loopback interfaces (`0.0.0.0` or public IPs) is strictly prohibited if `NOTIONCHAT_API_KEY` is unset or set to the default placeholder (`sk-notionchat`). The server will refuse to start until a strong, unique secret key is configured.

### 2. Credential & State File Protection
- **Atomic Writes:** Account credentials (`notion_account.json`) and thread states (`threads/*.json`) are written via atomic temporary files to eliminate partial writes or race conditions.
- **Restrictive Permissions:** State files are written with POSIX `0600` permissions (read/write only by the owning process user) on supported platforms.

### 3. Upstream Error Sanitization
- Upstream HTTP errors and exception messages from Notion's private endpoints are sanitized before returning responses to callers, preventing accidental leakage of internal cookies, headers, or raw response bodies.

### 4. Streaming Safety
- Streaming responses operate in append-only mode by default. Internal control signals (such as stream replacement markers) are stripped unless callers explicitly opt in via the `X-Allow-Stream-Replace: 1` header.
- In tool-calling mode, raw stream tokens are buffered and validated against the bridge result to ensure only verified content or tool calls are delivered.

### 5. Experimental Tools Isolation
- **Feature-Gated:** Tool calling and IDE agent bridging are experimental and **disabled by default**. They must be explicitly enabled via `NOTIONCHAT_EXPERIMENTAL_TOOLS=1`.
- **Client Allowlist Enforcement:** Model outputs cannot invoke tools that were not explicitly provided in the client's request `tools` array. Unsolicited or injected tool names are discarded.
- **Schema & Arguments Validation:** Tool call arguments are validated against standard JSON and verified against required schema properties before being passed back to clients.
- **Adversarial Prompt Injection Defense:** Tool calls parsed from model prose or markdown blocks are subject to the same strict allowlist and schema validation as structured events.
