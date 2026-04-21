# V1 SmartGlass G2

A voice-driven heads-up display app that streams **Trend Vision One** signals
straight to **Even Realities G2** smart glasses.

Say **"Hey Even, VisionOne alerts"** to see the latest critical/high Workbench
alerts, or **"Hey Even, Vision One top risk"** to see the top risky users and
machines from ASRM — all rendered on the G2 HUD.

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
  Even Realities' reverse-engineered BLE protocol (pair both temples, push
  TEXT command frames to the HUD, and subscribe to post-wake-word voice
  transcripts).
- **Vision One v3 API**: `GET /v3.0/workbench/alerts`,
  `GET /v3.0/asrm/highRiskUsers`, `GET /v3.0/asrm/highRiskDevices`.
- Voice commands are matched with fuzzy regexes so "VisionOne" / "vision one" /
  "V1" all resolve to the same intent.

## Voice commands

| Utterance                               | Intent      | What you see                                       |
| --------------------------------------- | ----------- | -------------------------------------------------- |
| `Hey Even, VisionOne alerts`            | `ALERTS`    | Up to 4 most severe Workbench alerts + entity name |
| `Hey Even, Vision One top risk`         | `TOP_RISK`  | Top-N risky users + top-N risky devices (2 pages)  |
| `Hey Even, top risky users`             | `TOP_RISK`  | Same                                               |
| `Hey Even, alerts on Vision One`        | `ALERTS`    | Same                                               |

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
pip install -e ".[even]"   # add [test] if you want pytest etc.
```

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
