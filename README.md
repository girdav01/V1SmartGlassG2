# V1 SmartGlass G2

A voice-driven heads-up display app that streams **Trend Vision One** signals
straight to **Even Realities G2** smart glasses.

Say **"Hey Even, VisionOne alerts"** to see the latest critical/high Workbench
alerts, or **"Hey Even, Vision One top risk"** to see the top risky users and
machines from ASRM — all rendered on the G2 HUD.

> **Looking for an emulator?** Check out [`even-hub/`](./even-hub/) for a
> TypeScript port of this app that runs inside the
> [BxNxM/even-dev](https://github.com/BxNxM/even-dev) Hub simulator (browser
> preview, no glasses required). The Python companion below is the path for
> direct BLE + voice on real hardware.

---

## How it works

```
┌────────────────────┐   BLE   ┌──────────────────────┐   HTTPS   ┌─────────────────┐
│ Even Realities G2  │ ──────► │ v1smartglass (host)  │ ────────► │ Vision One API  │
│  mic + HUD display │ ◄────── │ Python companion app │ ◄──────── │ (regional host) │
└────────────────────┘         └──────────────────────┘           └─────────────────┘
     "Hey Even, ..."               intent router                  /workbench/alerts
                                   formatter (5-line HUD)         /asrm/highRiskUsers
                                                                  /asrm/highRiskDevices
```

- **G2 SDK**: we use the community Python BLE SDK
  [`even-glasses`](https://pypi.org/project/even-glasses/) which implements
  Even Realities' reverse-engineered BLE protocol — scan both temples, pair,
  push TEXT command frames to the HUD, and receive the wake-word event.
- **Vision One v3 API**: `GET /v3.0/workbench/alerts`,
  `GET /v3.0/asrm/highRiskUsers`, `GET /v3.0/asrm/highRiskDevices`.
- Voice commands are matched with fuzzy regexes so "VisionOne" / "vision one" /
  "V1" all resolve to the same intent.

### Voice routing: host mic + faster-whisper

The G2 hardware does the "Hey Even" wake-word detection on the temple and
forwards a START_AI event over BLE — but no transcript, and the raw mic
audio is LC3-encoded (no Python decoder on PyPI). So we use the wake
event as a *trigger*: the host then records ~4 s from its own microphone
via `sounddevice` and transcribes locally with `faster-whisper`. The
resulting text goes through the same `parse_intent` router that the
console driver uses.

Install the extra to enable per-phrase routing:

```bash
pip install -e ".[even,asr]"
```

That pulls `faster-whisper`, `sounddevice`, and `numpy`. On first wake
event the Whisper model (`tiny.en` by default, ~75 MB) downloads to your
HuggingFace cache — subsequent calls load from disk.

If `[asr]` isn't installed, or `asr.enabled: false`, the driver falls back
to a **wake-cycle** UX where each wake rotates between ALERTS and TOP_RISK
without needing the microphone.

The **console driver** (`app.dry_run: true`) accepts typed
`Hey Even ...` strings on stdin and runs the full intent router, so you
can develop and demo the phrase matching with no hardware and no model
download.

> **macOS tip**: grant microphone permission to your terminal under
> System Settings → Privacy & Security → Microphone, otherwise
> `sounddevice` returns silence.

## Voice commands

| Utterance                                  | Intent      | What you see                                       |
| ------------------------------------------ | ----------- | -------------------------------------------------- |
| `Hey Even, VisionOne alerts`               | `ALERTS`    | Up to 4 most severe Workbench alerts + entity name |
| `Hey Even, Vision One top risk`            | `TOP_RISK`  | Top-N risky users + top-N risky devices (2 pages)  |
| `Hey Even, top risky users`                | `TOP_RISK`  | Same                                               |
| `Hey Even, alerts on Vision One`           | `ALERTS`    | Same                                               |
| `Hey Even, ask why alice@corp is risky`    | `ASK`       | LLM answer (with MCP tools) wrapped onto the HUD   |
| `Hey Even, what is the latest critical`    | `ASK`       | Same                                               |
| `Hey Even, tell me about 1.2.3.4`          | `ASK`       | Same                                               |

## Prerequisites

1. A Trend Vision One tenant with:
   - A **Bearer API key** (Administration → API Keys) scoped for
     `Workbench / read` and `ASRM / read`.
   - The **regional host** for your tenant — one of:

     | Region | Host                              |
     | ------ | --------------------------------- |
     | `us`   | `api.xdr.trendmicro.com`          |
     | `eu`   | `api.eu.xdr.trendmicro.com`       |
     | `jp`   | `api.xdr.trendmicro.co.jp`        |
     | `sg`   | `api.sg.xdr.trendmicro.com`       |
     | `au`   | `api.au.xdr.trendmicro.com`       |
     | `in`   | `api.in.xdr.trendmicro.com`       |
     | `uae`  | `api.uae.xdr.trendmicro.com`      |

2. A paired set of **Even Realities G2** glasses and a host with a working
   BLE adapter (macOS, Linux + BlueZ, or Windows 10+).

3. Python 3.10+.

## Install

```bash
git clone https://github.com/girdav01/v1smartglassg2.git
cd v1smartglassg2
python -m venv .venv && source .venv/bin/activate
pip install -e ".[even,asr]"   # add [test] if you want pytest etc.
```

The extras are independent:

- `[even]` — community BLE SDK for the G2 (skip in dry-run / CI).
- `[asr]` — `faster-whisper` + `sounddevice` for host-mic transcription.
  Skip if you're happy with the wake-cycle fallback.
- `[llm]` — `openai-agents` + `mcp` to answer free-form `Hey Even, ask …`
  questions via an LLM with MCP tools. Skip if you only need the two
  fast-path intents.

### LLM + MCP setup (Hey Even, ask …)

`ASK` routes the transcribed question to an OpenAI-compatible LLM that has a
fleet of MCP servers registered as tools. Verified servers wired in
`config.example.yaml`:

| Server         | Repo                                                   | Tools |
| -------------- | ------------------------------------------------------ | ----- |
| Trend Vision One | `github.com/trendmicro/vision-one-mcp-server`       | Workbench, ASRM, Cloud Posture, IAM, Email/Container/Endpoint, AI Security, Threat Intel — read-only by default |
| Splunk         | `github.com/deslicer/mcp-for-splunk`                   | NL → SPL, search execution, knowledge objects (20+ tools) |
| MISP           | `github.com/MISP/misp-mcp`                             | Read-only event / attribute / object search |
| Shodan         | `github.com/BurtTheCoder/mcp-shodan`                   | IP/host recon, DNS, CVE/CPE intel |
| AbuseIPDB      | `github.com/n3r0-b1n4ry/mcp-abuseipdb`                 | IP reputation queries |
| VirusTotal     | `github.com/BurtTheCoder/mcp-virustotal`               | URL / file / IP / domain reports with relationship pivots |
| URLhaus        | `github.com/Cyreslab-AI/urlhaus-mcp-server`            | abuse.ch malicious-URL feed (free, no API key) |

To enable, set `llm.enabled: true`, point `llm.base_url` at any
OpenAI-compatible Chat Completions endpoint (OpenAI, a local Ollama or
LMStudio reachable over Tailscale, or a LiteLLM proxy), and flip
`enabled: true` on each MCP server you have credentials for. Secrets in
the MCP `env:` blocks support `${VAR}` substitution from the process
environment, so you don't have to commit them.

Host prerequisites per server:

- Vision One — `docker pull ghcr.io/trendmicro/vision-one-mcp-server`
- Splunk / MISP / Shodan / AbuseIPDB — `uvx` (install via `pipx install uv`)
- VirusTotal / URLhaus — `npx` (any modern Node.js)

```bash
export V1SG_API_KEY="<vision-one-token>"
export SHODAN_API_KEY="..."
export VIRUSTOTAL_API_KEY="..."
# URLhaus needs no key.
v1smartglass run --config config.yaml
# In one terminal you'll see each MCP server log its startup.
# Say: "Hey Even, ask which user has the highest risk score today"
# Or:  "Hey Even, ask is 1.2.3.4 a known malware C2"
```

Tuning knobs (`llm:` block):

- `max_chars` — hard ceiling on the answer (default 160 = 5 HUD lines × 32).
- `max_turns` — cap on LLM-tool iterations per question (default 6).
- `timeout_seconds` — abort if the round-trip stalls (default 30 s).
- `system_prompt` — override the built-in HUD-aware prompt.

**Latency**: local Ollama on a beefy box typically 3–6 s; cloud LLMs 8–15 s.
The HUD shows an `ASK / thinking…` holding frame for the duration.

**Blast radius**: the bundled servers are read-only or read-mostly. If you
add a write-capable MCP later (e.g. an EDR isolate-host server), put an
approval flow in front of it — the agents SDK supports `require_approval`
on `MCPServerStdio`.

## Configure

```bash
cp config.example.yaml config.yaml
$EDITOR config.yaml        # paste api_key + region
```

Or use environment variables (handy for CI / containers):

```bash
export V1SG_API_KEY="eyJhbGciOi..."
export V1SG_REGION="eu"
```

## Run

```bash
# Live mode: connect the glasses and wait for voice commands.
v1smartglass run --config config.yaml

# Smoke test without glasses (prints frames to the terminal).
v1smartglass once "Hey Even VisionOne alerts" --config config.yaml
v1smartglass once "Hey Even Vision One top risk" --config config.yaml

# Just verify the API key + region are working.
v1smartglass doctor --config config.yaml
```

When `app.dry_run: true` (or if `even-glasses` isn't installed), the driver
falls back to a terminal renderer that prints each HUD page as a Rich panel
and lets you type simulated `Hey Even ...` utterances on stdin.

## Testing

```bash
pip install -e ".[test]"
pytest
```

The suite covers:

- `tests/test_voice.py` — intent parsing, including fuzzy ASR variants.
- `tests/test_vision_one.py` — mocked Vision One API (`respx`) exercising the
  auth header, severity filter, and error paths.
- `tests/test_formatter.py` — HUD layout, severity ranking, line truncation.
- `tests/test_app.py` — end-to-end with a fake driver + fake client.

### Manual end-to-end

1. Power on both G2 arms, put them in pairing range.
2. `v1smartglass run -v` — you should see `console driver ready` replaced with
   `paired with Even G2_L + Even G2_R`, then a "V1 SMARTGLASS" banner on the
   HUD.
3. Say **"Hey Even, VisionOne alerts"**. Within a couple of seconds the HUD
   shows a `V1 ALERTS (n)` page with the most severe items.
4. Say **"Hey Even, Vision One top risk"**. The HUD cycles through a
   `TOP RISKY USERS` page and a `TOP RISKY DEVICES` page.

## Publishing

Even Realities does not operate a third-party app store for the G2, so
"publishing" this app means distributing the companion that runs on the
paired host. Three common ways:

### 1. PyPI wheel

```bash
pip install build twine
python -m build                    # produces dist/v1smartglass-0.1.0-*.whl
twine upload dist/*                # or twine upload --repository testpypi dist/*
```

End users then run:

```bash
pipx install v1smartglass[even]
v1smartglass run
```

### 2. Docker image (headless host, BLE passthrough)

```dockerfile
# Dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends bluez && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[even]"
ENTRYPOINT ["v1smartglass", "run"]
```

```bash
docker build -t v1smartglass .
docker run --rm -it \
  --net=host --privileged \
  -v /var/run/dbus:/var/run/dbus \
  -e V1SG_API_KEY -e V1SG_REGION \
  v1smartglass
```

### 3. systemd service (auto-start at login)

```ini
# /etc/systemd/system/v1smartglass.service
[Unit]
Description=Vision One → Even Realities G2 HUD
After=bluetooth.target network-online.target

[Service]
Type=simple
Environment=V1SG_API_KEY=...
Environment=V1SG_REGION=eu
ExecStart=/usr/local/bin/v1smartglass run
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now v1smartglass
journalctl -u v1smartglass -f     # follow logs
```

## Troubleshooting

- **`Could not pair with Even Realities G2`** — make sure both arms are awake
  (tap the temple), and that no phone nearby is already holding the BLE
  connection. Run with `-v` for verbose BLE logs.
- **HTTP 401 from Vision One** — the API key is either wrong or doesn't have
  the Workbench/ASRM scopes. Regenerate under
  *Administration → API Keys* and paste it into `config.yaml`.
- **HTTP 404 for `/asrm/highRiskUsers`** — ASRM isn't enabled on the tenant.
  Enable it or remove the `TOP_RISK` intent from your deployment.
- **Wrong region** — Vision One tenants are region-locked; a US key will 401
  against the EU host. Set `region:` to match the console URL you log in to.

## License

MIT — see `LICENSE`.
