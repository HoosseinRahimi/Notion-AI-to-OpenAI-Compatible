<div align="center">

# Notion AI → OpenAI Compatible

**Unofficial OpenAI-compatible proxy for Notion AI**  
Cookie auth · streaming · Cursor / 9router / Postman

[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-OpenAI%20API-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

<br/>

### Support the project

If this saves you time, a coffee (or satoshi) helps keep it maintained.

[![PayPal](https://img.shields.io/badge/PayPal-Donate-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/captainredz?locale.x=en_US&country.x=ID)
[![Patreon](https://img.shields.io/badge/Patreon-Support-FF424D?style=for-the-badge&logo=patreon&logoColor=white)](https://patreon.com/mughu?utm_medium=unknown&utm_source=join_link&utm_campaign=creatorshare_creator&utm_content=copyLink)
[![Traktir Kopi](https://img.shields.io/badge/Traktir%20Kopi-MuGhu-F59E0B?style=for-the-badge)](https://traktir.mughu.id/)

| | Network | Address |
|:--:|:--|:--|
| **BTC** | Bitcoin | `bc1pq0njd8sqextzrx2xx2qlzuud2m3nkcxqqu2kpyk6gwnufsum2phq6fdvtw` |
| **SOL** | Solana | `HUW8ntbpNGRcdTWc32yat3UCKcsHuiz1Me2QurPcF6iC` |
| **USDT** | Solana | `HUW8ntbpNGRcdTWc32yat3UCKcsHuiz1Me2QurPcF6iC` |
| **USDT** | TRON (TRC20) | `TY5qoR528nTwgkRvQmDMoRpmDRjKXnHMse` |

<p>
  <img src="https://img.shields.io/badge/BTC-Bitcoin-F7931A?style=flat-square&logo=bitcoin&logoColor=white" alt="BTC"/>
  <img src="https://img.shields.io/badge/SOL-Solana-9945FF?style=flat-square&logo=solana&logoColor=white" alt="SOL"/>
  <img src="https://img.shields.io/badge/USDT-Solana-26A17B?style=flat-square&logo=tether&logoColor=white" alt="USDT Solana"/>
  <img src="https://img.shields.io/badge/USDT-TRON%20TRC20-EF0027?style=flat-square&logo=tron&logoColor=white" alt="USDT TRON"/>
</p>

<sub>Send only the matching network asset to each address — wrong-chain transfers are lost forever.</sub>

</div>

---

> **Educational / unofficial** — for learning and research. Not affiliated with or endorsed by Notion. You must comply with Notion’s Terms of Service and your workspace plan limits.

OpenAI-compatible HTTP API that routes chat to **Notion AI** (`runInferenceTranscript`) using your Notion browser session (`token_v2`).

Works with [Cursor](https://cursor.com), [9router](https://github.com), Postman, or any OpenAI Chat Completions client.

## Features

- **OpenAI-compatible endpoints**
  - `POST /v1/chat/completions` (streaming and non-streaming)
  - `POST /v1/responses` (OpenAI Responses API contract)
  - `GET /v1/models` (dynamic list from Notion `getAvailableModels`, with aliases & stale cache fallback)
  - `GET /healthz` (liveness probe)
  - `GET /readyz` (readiness probe verifying loaded Notion credentials)
- **Browser cookie authentication** — no separate Notion API key required
- **Hardened Security**
  - Timing-safe API key verification (`secrets.compare_digest`)
  - Public bind protection (prohibits binding to `0.0.0.0` with default/empty key)
  - Atomic state writes with POSIX `0600` file permissions
  - Sanitized upstream error responses
- **Standard Streaming** — Append-only SSE chunk streaming without control markers; opt-in `X-Allow-Stream-Replace: 1` header
- **Model aliases** — e.g. `opus-4.8`, `gpt-4o`, `sonnet-4.6` mapped to Notion internal model IDs
- **Thread state & concurrency** — Per-session serialization locks, bounded TTL reuse pool (`NOTIONCHAT_THREAD_REUSE_LIMIT`)
- **Tools bridge (experimental)** — Feature-gated (`NOTIONCHAT_EXPERIMENTAL_TOOLS=1`) with strict client allowlist and schema validation
- **Postman collection** in [`postman/`](postman/)

## Compatibility Matrix

| Endpoint / Feature | Status | Notes |
| :--- | :--- | :--- |
| `POST /v1/chat/completions` | **Supported** | Full streaming & non-streaming support. |
| `POST /v1/responses` | **Supported** | Maps to/from Chat Completions; returns `status: "completed"`. |
| `GET /v1/models` | **Supported** | Dynamically fetched from Notion AI, alias mapping, stale cache fallback. |
| `GET /healthz` | **Supported** | Liveness check (HTTP 200). |
| `GET /readyz` | **Supported** | Readiness check (HTTP 200 if credentials loaded, 503 if unconfigured). |
| Streaming (`stream=true`) | **Supported** | Standard append-only SSE deltas. Opt-in `X-Allow-Stream-Replace: 1`. |
| Tool Calling (`tools`) | **Experimental** | Gated by `NOTIONCHAT_EXPERIMENTAL_TOOLS=1`. Enforces client allowlist & schema validation. |

## How it works

```
Client (Cursor / 9router / Postman)
        │
        ▼
  NotionChat (FastAPI)
        │  OpenAI messages + tools → Notion transcript
        ▼
  Notion API  POST /api/v3/runInferenceTranscript
        │  NDJSON stream
        ▼
  NotionChat parses response → OpenAI chat.completion (+ optional tool_calls)
```

Notion AI is a **chat** product. It does not expose native OpenAI function calling. For IDE agent workflows, NotionChat compiles model text into `tool_calls` (JSON, code fences, shell commands) and applies guardrails (scaffold sequencing, denial handling, etc.).

## Requirements

- Python 3.11+ recommended
- A Notion account with AI access (plan limits apply)
- A valid Notion browser session (`token_v2` cookie)

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/mughu-id/Notion-AI-to-OpenAI-Compatible.git
cd Notion-AI-to-OpenAI-Compatible
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

This registers CLI commands: **`notion`** and **`notionchat`** (same behavior).

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|----------|-------------|
| `NOTIONCHAT_API_KEY` | Bearer token clients must send (`Authorization: Bearer ...`) |
| `NOTIONCHAT_HOST` | Bind host (default `127.0.0.1`) |
| `NOTIONCHAT_PORT` | Port (default `1994`) |
| `NOTIONCHAT_ACCOUNT` | Path to account JSON (default `notion_account.json`) |
| `NOTIONCHAT_THREADS_DIR` | Thread state directory (default `threads/`) |
| `NOTIONCHAT_DEFAULT_MODEL` | Default Notion model ID |
| `NOTIONCHAT_HOME` | Optional — absolute project folder so `notion serve` finds `.env` / account files from any cwd |
| `NOTION_COOKIE` | Optional — full `document.cookie` for auto-bootstrap on startup |
| `NOTION_PROXY` | Optional — HTTP/SOCKS proxy for Notion egress (needed when a home-PC cookie is used on a VPS) |
| `NOTION_USER_AGENT` / `NOTION_CLIENT_VERSION` | Optional — match the browser that created the cookie |
| `NOTIONCHAT_THREAD_REUSE_LIMIT` | Optional — reuse one Notion chat for N completions before rotating (`0` = off, default). Helps reduce thread spam / ban risk |
| `NOTIONCHAT_EXPERIMENTAL_TOOLS` | Optional — set to `1` or `true` to enable experimental tool calling / agent bridge (`0` = off, default) |

### 3. Bootstrap account from browser cookie

**Important (VPS / production):** Notion ties AI permission to the **IP where you logged in**. Copying a cookie from your home PC browser onto a VPS often causes intermittent `403` / `trust-rule-denied` ("This action is not currently available"). Prefer one of:

1. Log into Notion **on the VPS** (or any browser exiting the same public IP), use Notion AI once, then copy **that** cookie and run `init`.
2. Or set `NOTION_PROXY` to a SOCKS/HTTP proxy that exits your home/residential IP, then init + serve through that proxy.
3. Or run NotionChat on the same machine/network as the browser.

Then:

1. Log in to [Notion](https://www.notion.com) in your browser.
2. Open DevTools → **Application** → **Cookies** → `https://www.notion.com`.
3. Copy the full cookie string (must include `token_v2` and ideally `notion_browser_id`).

```bash
notion init --cookie "notion_browser_id=...; token_v2=..."
```

Or use the interactive wizard:

```bash
notion setup
```

If you have multiple workspaces:

```bash
notion init --cookie "..." --space-name "My Workspace"
```

This writes `notion_account.json` (gitignored — **do not commit**).

Alternatively, set `NOTION_COOKIE` in `.env` and NotionChat will bootstrap on first request.

### 4. Run the server

```bash
notion serve
```

Same as `notionchat serve` or `python -m notionchat serve`.

Server URL: `http://127.0.0.1:1994` (or your `NOTIONCHAT_HOST` / `NOTIONCHAT_PORT`).

### 5. Optional — add `notion` to PATH (use from any folder)

#### Windows (CMD / PowerShell)

**Option A — pip entry point (recommended after `pip install -e .`)**

1. Note where `notion.exe` was installed. With a venv:

   ```
   <your-clone>\.venv\Scripts
   ```

   With user install (no venv):

   ```
   %APPDATA%\Python\Python3xx\Scripts
   ```

2. Add that folder to your **user PATH**:
   - Settings → System → About → Advanced system settings → Environment Variables
   - Under **User variables** → `Path` → Edit → New → paste the Scripts folder
3. Open a **new** CMD window and run:

   ```bat
   notion serve
   ```

Also set a user variable so config is found from any directory:

| Name | Value |
|------|--------|
| `NOTIONCHAT_HOME` | Full path to your clone, e.g. `C:\Users\You\Notion-AI-to-OpenAI-Compatible` |

**Option B — project `scripts\` launcher (no global pip Scripts needed)**

1. Add this folder to your user PATH:

   ```
   <your-clone>\scripts
   ```

   Example: `C:\Users\You\Notion-AI-to-OpenAI-Compatible\scripts`

2. Set user env:

   | Name | Value |
   |------|--------|
   | `NOTIONCHAT_HOME` | Full path to `<your-clone>` |

   (`notion.cmd` also defaults `NOTIONCHAT_HOME` to the parent of `scripts\` if unset.)

3. New CMD:

   ```bat
   notion serve
   notion setup
   notionchat serve
   ```

#### macOS / Linux

**Option A — pip / venv**

```bash
source .venv/bin/activate   # keeps notion on PATH while active
# or add to ~/.bashrc / ~/.zshrc:
# export PATH="$HOME/path/to/Notion-AI-to-OpenAI-Compatible/.venv/bin:$PATH"
export NOTIONCHAT_HOME="$HOME/path/to/Notion-AI-to-OpenAI-Compatible"
notion serve
```

**Option B — `scripts/` launcher**

```bash
# ~/.bashrc or ~/.zshrc
export PATH="$HOME/path/to/Notion-AI-to-OpenAI-Compatible/scripts:$PATH"
export NOTIONCHAT_HOME="$HOME/path/to/Notion-AI-to-OpenAI-Compatible"
chmod +x "$NOTIONCHAT_HOME/scripts/notion" "$NOTIONCHAT_HOME/scripts/notionchat"
```

Then:

```bash
notion serve
```

### 6. Test

```bash
# Health & readiness checks
curl http://127.0.0.1:1994/healthz
curl http://127.0.0.1:1994/readyz

# List available models
curl http://127.0.0.1:1994/v1/models \
  -H "Authorization: Bearer sk-your-notionchat-key"

# Chat completion
curl http://127.0.0.1:1994/v1/chat/completions \
  -H "Authorization: Bearer sk-your-notionchat-key" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"opus-4.8\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello in one sentence.\"}]}"
```

Import [`postman/NotionChat.postman_collection.json`](postman/NotionChat.postman_collection.json) for more examples.

### Test Screenshots (Postman & Notion AI UI)

Below are visual confirmations of the API completion and model alignment flows running locally:

#### 1. Chat Completion Output (`gpt-5.6-terra`)
![Postman completion request](https://img.lightshot.app/ElIeVwm5RGClRmS4tg3RAQ.png)

#### 2. Chat Completion Output (`fable-5`)
![Postman fable-5 request](https://img.lightshot.app/4J53VlBVQ3eU2gCXiTIwzw.png)

#### 3. Notion UI Side-by-Side (`gpt-5.6-terra` thread view)
![Notion UI session matching gpt-5.6-terra](https://img.lightshot.app/XfAmfEdGSUqh6sa5IxMNEQ.png)

#### 4. Notion UI Side-by-Side (`fable-5` thread view)
![Notion UI session matching fable-5](https://img.lightshot.app/YrkxNs9PTkeQn9tgcM1TXg.png)

### 7. Run in background with PM2 (optional)

[PM2](https://pm2.keymetrics.io/) keeps NotionChat running, restarts on crash, and can start on boot.

```bash
# one-time: Node.js required for PM2
npm install -g pm2

# from the project root (venv + .env already set up)
pm2 start ecosystem.config.cjs
pm2 status
pm2 logs notionchat
```

Useful commands:

```bash
pm2 restart notionchat
pm2 stop notionchat
pm2 delete notionchat
pm2 save
pm2 startup    # print OS instructions to relaunch PM2 after reboot
```

Notes:

- `ecosystem.config.cjs` prefers `.venv` Python, sets `NOTIONCHAT_HOME` to the project root, and writes logs under `logs/`.
- Bind host/port still come from `.env` (`NOTIONCHAT_HOST`, `NOTIONCHAT_PORT`).
- Use **one** process (`instances: 1`) — NotionChat is not meant for multi-instance concurrency on the same cookie/thread state.
- After changing `.env` or code: `pm2 restart notionchat`.

## Cursor / 9router setup

1. Run NotionChat locally (`notion serve` or `pm2 start ecosystem.config.cjs`).
2. In your router or Cursor custom model settings:
   - **Base URL:** `http://127.0.0.1:1994/v1`
   - **API key:** value of `NOTIONCHAT_API_KEY` from `.env`
   - **Model:** e.g. `opus-4.8` (see `/v1/models`)

**Chat mode** generally works well.

**Agent mode** (tools) is experimental — see limitations below.

## API

### `POST /v1/chat/completions`

Supports standard OpenAI Chat Completions fields:
- `model`: Target model ID or alias (e.g. `opus-4.8`, `gpt-4o`, `sonnet-4.6`).
- `messages`: Standard role-based conversation array (`system`, `user`, `assistant`, `tool`).
- `stream`: Boolean for Server-Sent Events (SSE) streaming. Emits append-only deltas by default. Send `X-Allow-Stream-Replace: 1` header to enable stream replacement markers.
- `tools`, `tool_choice`, `parallel_tool_calls`: Experimental function calling (requires `NOTIONCHAT_EXPERIMENTAL_TOOLS=1`).
- `user`: Optional session key for thread continuity across requests.

### `POST /v1/responses`

OpenAI Responses API contract:
- Accepts `model`, `input` (string or array of text/input items), `tools`, `instructions`.
- Automatically maps to/from Chat Completions representation.
- Always returns standard Responses payload with `status: "completed"`.

### `GET /v1/models`

Returns models available to your Notion workspace, cached for 5 minutes with automatic stale-cache fallback on upstream network interruptions.

### `GET /healthz` & `GET /readyz`

- `GET /healthz`: Basic liveness probe (returns `{"status": "ok"}`).
- `GET /readyz`: Readiness probe (returns HTTP 200 with account workspace info if credentials are valid, HTTP 503 if unconfigured or invalid).

## Project layout

```
notionchat/          # Python package (API, client, parsers, tools bridge)
scripts/             # PATH launchers: notion / notionchat (.cmd on Windows)
postman/             # Postman collection
ecosystem.config.cjs # PM2 process file (`pm2 start ecosystem.config.cjs`)
.env.example         # Copy to .env (never commit .env)
pyproject.toml       # package + CLI entry points (notion, notionchat)
requirements.txt
```

## Project Status & Roadmap

### What this project already has (Done)
- [x] **OpenAI-Compatible completions API** (`/v1/chat/completions`) with full SSE streaming and non-streaming support.
- [x] **Dynamic model resolution** (`/v1/models`) fetching enabled models directly from Notion and mapping aliases (`opus-4.8`, `gpt-4o`, `sonnet-4.6`, `Grok 4.5`, `GPT-5.6 Terra/Sol/Luna`).
- [x] **Auto-Bootstrap account init** from raw browser cookie strings directly on start.
- [x] **Interactive CLI setup wizard** (`python -m notionchat setup`) for cookie + `.env` configuration.
- [x] **State-aware NDJSON patch parser** which correctly resolves nested block paths to prevent text corruption/merges.
- [x] **Stream buffering & cleaning** to strip model preambles ("I'm ready to write this...") without slicing into the actual response.
- [x] **`patch-sync` event parsing** to support models like `opus-4.8` without 502/empty errors.
- [x] **Chrome TLS Impersonation** (via `curl_cffi`) and Windows event loop fixes for high stability.
- [x] **Windows Server browser fingerprinting** (`browser_fp`) to reduce `trust-rule-denied` when browser AI works but the API does not.
- [x] **Auto-confirm web-search URL safety prompts** so long research generations don't stall waiting for a manual Allow click.
- [x] **CLI commands** — `notion` / `notionchat` via `pip install -e .` or `scripts/` PATH launchers.
- [x] **PM2 support** — `ecosystem.config.cjs` for background run, auto-restart, and logs.
- [x] **Experimental Tools Compiler** for mapping Cursor Agent commands (`Shell`, `Write`) to Notion prose blocks and back.

### Next Steps (Todo)
- [ ] **Multi-Cookie/Account rotation pool** to load-balance requests across multiple Notion accounts.
- [ ] **Auto-refresh cookie session** by simulating background navigation.
- [ ] **Multimodal support** (images/assets) mapped to Notion's inline image attachment blocks.
- [ ] **Full Custom Agent configuration** via endpoint custom params or headers.
- [ ] **Background service setup** — Windows Service / systemd unit (PM2 already covered; native service wrappers optional).
- [ ] **Dockerization** — add a simple `Dockerfile` and `docker-compose.yml` to spin up the proxy server anywhere.
- [ ] **Lightweight Dashboard (Web UI)** — add a `/admin` panel to monitor active threads, log history, and verify/refresh browser cookies in real-time.
- [ ] **Multiple API keys management** instead of a single global `NOTIONCHAT_API_KEY`.
- [ ] **Workspace Search mapping** — map file-search queries to Notion Workspace search to let Notion AI reference other docs in your workspace.

## Known limitations

### Tool calling / Cursor Agent — not fully working

This is the main gap if you expect parity with OpenAI, Anthropic, or native Cursor models.

**Root cause:** Notion AI is not an IDE agent. It runs as Notion's chat assistant (`surface: ai_module`), often refuses filesystem/tool access, and does not reliably emit OpenAI-style `tool_calls`. NotionChat bridges this with prompts, parsing, and heuristics — not true function calling.

**What often goes wrong**

| Symptom | Why |
|---------|-----|
| Model says *"I can't access your filesystem / Cursor tools"* | Notion AI persona rejects IDE tool context as out-of-scope |
| `out=0` tool rounds but no real progress | Compiler emitted `Shell`/`Write` from prose; Notion didn't plan the task |
| `npm create` used a subfolder | Notion suggests `npm create vite@latest my-app`; paths drift from workspace (partially mitigated: forced `.` scaffold) |
| Shell + Write in one turn | Cursor runs tools in parallel; writes happen before scaffold finishes (mitigated: scaffold-only first turn) |
| Glob / search loops | Model keeps exploring instead of building (partially mitigated: loop tool filtering) |
| Complex apps (Vite + React + Tailwind + shadcn) stall | Multi-step scaffolding needs reliable tool planning; Notion output is inconsistent |

**What NotionChat tries to do today**

- Detect Cursor Agent requests (tools + system prompt markers)
- Inject full tool schemas and JSON tool-call instructions
- Compile Notion output into `tool_calls` from:
  - JSON `tool_calls` in text
  - NDJSON `tool_use` events
  - `bash` / `npm` / `npx` lines → `Shell`
  - Path-tagged code fences → `Write`
- Bootstrap `npm create vite@latest .` when Notion refuses on coding tasks
- Run scaffold `Shell` alone first; defer `Write` until shell tool results exist
- Suppress Notion refusal prose from reaching Cursor when possible
- Disable Notion thread reuse in agent mode to avoid polluted state

**Recommendation**

| Use case | Suggested backend |
|----------|-------------------|
| Chat, Q&A, drafting | NotionChat — works well |
| Light edits with tools | NotionChat — may work, expect retries |
| Full Agent builds (scaffold + many files) | OpenAI / Anthropic / native Cursor models |

Contributions welcome on [`notionchat/tools.py`](notionchat/tools.py) — especially a more robust `compile_agent_tool_calls` pipeline and better Notion prompt strategy.

### Other limitations

- **Cookie expiry** — refresh `token_v2` when you get 401/403 errors
- **Unofficial API** — Notion can change endpoints or formats without notice (`patchResponseVersion`, NDJSON events, etc.)
- **Rate limits / credits** — subject to your Notion plan
- **Security** — the cookie grants full account access; run locally and never publish `notion_account.json` or `.env`

## Security

- Never commit `.env`, `notion_account.json`, or `threads/`
- Use a strong `NOTIONCHAT_API_KEY` if the server is reachable on your network
- Default bind is `127.0.0.1` — avoid exposing to the public internet without proper auth and TLS

## Troubleshooting

| Problem | Things to try |
|---------|----------------|
| Empty assistant response | Refresh cookie; check `space_id` in account file; verify AI credits |
| `402 Payment Required` | Notion AI credits exhausted for this workspace — check Notion billing / quota or switch cookie |
| `401` / `403` from Notion | Cookie/IP trust mismatch is common: re-init with a cookie taken **on the same public IP** as the server, or set `NOTION_PROXY` to exit via your home IP |
| `notion` not found in CMD | Add `.venv\Scripts` or `scripts\` to PATH; set `NOTIONCHAT_HOME` to the project folder |
| Agent does nothing | New Agent chat; check server logs for `IDE bridge tool_calls=...` |
| Wrong model | Call `GET /v1/models`; use an ID from that list |
| Business / empty stream | Ensure `curl_cffi` is installed (Chrome TLS impersonation) |

Enable server logging:

```bash
# NotionChat logs IDE bridge decisions at INFO level
python -m notionchat serve
```

## Development

```bash
pip install -r requirements.txt
python -m py_compile notionchat/*.py
python -m notionchat serve
```

## Disclaimer

This software is provided as-is. Using browser session cookies to access Notion's internal APIs may violate Notion's Terms of Service. Use at your own risk.

## License

[MIT](LICENSE)
