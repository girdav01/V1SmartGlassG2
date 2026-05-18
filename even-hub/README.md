# Even Hub port (`.ehpk` app)

This directory contains a TypeScript port of V1 SmartGlass that runs as an
Even Hub app inside the [BxNxM/even-dev](https://github.com/BxNxM/even-dev)
simulator. It coexists with the Python companion at the repo root — pick
whichever path suits you:

| | Python companion (repo root) | Hub app (this dir) |
| --- | --- | --- |
| Runtime | Python on a host + BLE | JS in Even Hub (simulator or real) |
| SDK | `even-glasses` (community BLE) | `@evenrealities/even_hub_sdk` + `@jappyjan/even-better-sdk` |
| Interaction | "Hey Even" voice (faster-whisper on host) | Temple clicker: CLICK = next page, DOUBLE_CLICK = refresh |
| Emulator | None (use `dry_run: true` console driver) | **Yes** — `BxNxM/even-dev`'s browser-based Hub simulator |
| Distribution | `pip install v1smartglass` | Build to `.ehpk`, sideload into the Hub |

## Setup

The simulator's repo layout expects apps under `apps/<name>/` and shared
helpers under `apps/_shared/`. We don't vendor the simulator — clone it
once and symlink (or copy) this app into it:

```bash
# 1. Clone the simulator workspace (anywhere on disk)
git clone https://github.com/BxNxM/even-dev.git
cd even-dev

# 2. Bring this app into apps/v1smartglass/ — symlink keeps it editable
ln -s /path/to/V1SmartGlassG2/even-hub/v1smartglass apps/v1smartglass

# 3. Install root + app dependencies (handled by start-even.sh on first run)
./start-even.sh --devenv-update
```

> The Vite config (`vite.config.ts`) imports `apps/_shared/standalone-vite`,
> so the app **must** live under the simulator's `apps/` directory — that's
> what the symlink achieves.

## Run

```bash
./start-even.sh v1smartglass
```

That starts the Vite dev server on `http://127.0.0.1:5178`. Open it,
paste your Vision One API key, pick your region, and:

1. Click **Refresh data** — pulls workbench alerts, top risky users, top
   risky devices from Vision One via the local proxy.
2. Click **Connect glasses** — the simulator's bridge wires the in-page
   HUD preview to the glasses view (real or simulated).
3. Click the temple (or use the simulator's clicker UI):
   - **CLICK** — cycle to the next page (alerts → users → devices → alerts).
   - **DOUBLE_CLICK** — refresh data from Vision One.

## How the Vision One call works

Browsers can't call Vision One directly (CORS), so requests go through a
local Vite middleware (`vite-plugin.ts`):

```
browser/app  --GET /__v1proxy?url=https://api.eu.xdr.trendmicro.com/v3.0/workbench/alerts
              --header X-V1-Auth: <token>
        |
        v
Vite dev server  --GET https://api.eu.xdr.trendmicro.com/v3.0/workbench/alerts
                 --header Authorization: Bearer <token>
```

The proxy enforces an allowlist of the seven Vision One regional hosts so
it can't be repurposed as an open relay. The same hosts are listed in
`app.json` under `permissions.network`, which the real Hub enforces.

## Build the `.ehpk`

```bash
npm --prefix /path/to/even-dev/apps/v1smartglass run build
# Then bundle dist/ + app.json into a .ehpk per the Even Hub sideload spec.
```

> Even Realities has not published an official spec for `.ehpk` packaging
> as of this writing; the simulator's `evenhub-cli` ships the bundling
> step — `./start-even.sh --evenhub-cli --help` from the simulator root.

## What didn't port

- **Voice routing.** The Hub SDK exposes clicker events, not transcripts,
  so the "Hey Even, VisionOne alerts" intent router doesn't apply here.
  If you need voice, see the Python companion — it uses host-mic +
  faster-whisper.
- **Background refresh loop.** Add a `setInterval` in `main.ts` if you
  want auto-refresh; for now refresh is manual or triggered by
  DOUBLE_CLICK.
- **Severity glyphs (`!!`, `!`, `~`, `.`).** Kept as ASCII so the layout
  matches the Python version — you can swap them for unicode symbols
  once you've confirmed the on-glass font supports them.
