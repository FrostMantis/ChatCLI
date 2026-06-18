# ChatCLI

A self-hosted, cross-platform desktop chat application. Real-time messaging, group chats, and VoIP calls — built with Electron + Python.

> **Live instance:** [chat.puam.be](http://chat.puam.be)  
> **License:** GNU General Public License v3.0  
> **Author:** [FrostMantis](https://github.com/FrostMantis)

---

## Table of contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Project structure](#project-structure)
4. [Prerequisites](#prerequisites)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [Running the app](#running-the-app)
8. [Troubleshooting](#troubleshooting)

---

## Features

- **Real-time messaging** — WebSocket-based instant delivery with typing indicators and live online presence
- **Group chats** — Create multi-user rooms, invite and remove participants
- **VoIP calling** *(beta)* — In-app voice calls powered by LiveKit
- **Search & archiving** — Search through chats, archive inactive conversations
- **Secure authentication** — Email verification, persistent login, password reset, rate-limited endpoints
- **Account management** — Update username/email, delete or deactivate your account

---

## Architecture

ChatCLI has two sides:

| Part | Technology | Role |
|---|---|---|
| **Client** | Electron (Node.js) | Desktop app for Windows and Linux |
| **HTTP API** | Python · Flask · Waitress | REST API — port `5123` |
| **WebSocket server** | Python · FastAPI · uvicorn | Real-time messaging — port `8765` |
| **Database** | MariaDB | Persistent storage |
| **VoIP** | LiveKit | Peer-to-peer voice calls |

The client ships as a standalone installer (`.exe` / `.deb`) and talks to the backend over HTTP and WebSocket. The backend runs as **two separate processes** that must both be started.

---

## Project structure

```
ChatCLI/
├── src/
│   ├── backend/                        # Python server
│   │   ├── main.py                     # Flask entry point (port 5123)
│   │   ├── run_server.py               # Launches both server processes
│   │   ├── install_update_server.py    # Database initialisation script
│   │   ├── requirements.txt
│   │   ├── .env                        # Environment config (not committed)
│   │   └── app/
│   │       ├── __init__.py             # Flask app factory
│   │       ├── config.py
│   │       ├── errors.py
│   │       ├── extensions.py           # Rate limiter
│   │       ├── routes/
│   │       │   ├── base_routes.py      # GET / and utility routes
│   │       │   ├── user_routes.py      # Auth, account management
│   │       │   └── chat_routes.py      # Chat, groups, archiving
│   │       ├── services/               # Business logic
│   │       │   ├── base_services.py
│   │       │   ├── user_services.py
│   │       │   ├── chat_services.py
│   │       │   └── mail_services.py
│   │       ├── database/
│   │       │   └── db_helper.py        # MariaDB connection helpers
│   │       ├── websockets/
│   │       │   ├── main.py             # FastAPI entry point (port 8765)
│   │       │   ├── handler.py          # WebSocket message dispatcher
│   │       │   ├── services.py         # WS business logic
│   │       │   ├── calls.py            # VoIP / LiveKit logic
│   │       │   └── db_helper.py        # Async DB helpers for WS
│   │       └── templates/
│   │           ├── index.html          # Landing page (served at /)
│   │           ├── reset_password.html
│   │           └── subscribe.html
│   └── client/
│       └── ChatCLI/                    # Electron client
│           ├── package.json
│           ├── forge.config.js
│           ├── dist/                   # Pre-built installers
│           └── src/
│               ├── main/               # Electron main process
│               ├── preload/            # Preload scripts (IPC bridge)
│               └── renderer/
│                   ├── pages/          # HTML pages
│                   ├── scripts/        # JS modules (chat, auth, calls…)
│                   └── styles/         # CSS
```

---

## Prerequisites

Make sure the following are installed before continuing.

```bash
python3 --version   # >= 3.12.0
mariadb --version   # >= 10.6  (server must be running)
node --version      # >= 24.7.0  (only needed to build the client from source)
git --version
```

To install MariaDB on Debian/Ubuntu:

```bash
sudo apt install mariadb-server
sudo systemctl start mariadb
```

---

## Installation

### End users — download the client

Pre-built installers are available in `src/client/ChatCLI/dist/` or on the [GitHub releases](https://github.com/FrostMantis/ChatCLI/releases) page.

| Platform | File |
|---|---|
| Windows | `ChatCLI Setup 0.4.1-beta.exe` |
| Windows (portable) | `ChatCLI-0.4.1-beta-win-portable.zip` |
| Linux (Debian/Ubuntu) | `chatcli_0.4.1-beta_amd64.deb` |
| Linux (portable) | `chatcli_0.4.1-beta_linux_portable.zip` |

```bash
# Linux .deb install
sudo dpkg -i chatcli_0.4.1-beta_amd64.deb
```

No additional dependencies required. Launch ChatCLI and connect to `chat.puam.be`.

---

### Self-hosting the backend

**1 — Clone the repository**

```bash
git clone https://github.com/FrostMantis/ChatCLI.git
cd ChatCLI/src/backend
```

**2 — Install Python dependencies**

```bash
pip install -r requirements.txt
```

**3 — Initialise the database**

This script creates the database, tables, and application user. It also generates a `.env` file with safe defaults if one does not exist yet.

```bash
python3 install_update_server.py
```

> If your MariaDB root user requires a password, set `ROOT_ACCESS=true` and fill in `DB_ROOT_USER` / `DB_ROOT_PASSWORD` in `.env` before running.

**4 — Configure `.env`** — see [Configuration](#configuration) below.

**5 — Start both server processes**

```bash
# Option A — single command (cross-platform)
python3 run_server.py

# Option B — manually in two terminals
# Terminal 1 — HTTP API (port 5123)
python3 main.py

# Terminal 2 — WebSocket server (port 8765)
python3 app/websockets/main.py
```

The backend is now running. Point the Electron client at your server by editing `src/client/ChatCLI/src/preload/config.js`.

---

## Configuration

`install_update_server.py` creates `.env` automatically on first run. Edit it to match your environment:

```env
# ── Server ────────────────────────────────────
FLASK_ENV=dev           # dev (debug) or prod (Waitress)
THREADS=2               # Waitress worker threads (prod only)

# ── Database ──────────────────────────────────
DB_HOST=localhost
DB_PORT=3306
DB_NAME=chatcli
DB_USER=chatcli_access
DB_PASSWORD=generated_automatically

ROOT_ACCESS=false       # Set true to let the installer create the DB user
DB_ROOT_USER=root
DB_ROOT_PASSWORD=

# ── Flask ─────────────────────────────────────
FLASK_SECRET_KEY=generated_automatically

# ── Public URL ────────────────────────────────
PUB_URL=your.domain.com     # Used in verification and reset email links

# ── Email (SMTP) ──────────────────────────────
EMAIL_USER=your@email.com
EMAIL_PASSWORD=app_password  # Use an app-specific password

# ── LiveKit (VoIP) ────────────────────────────
LIVEKIT_URL=ws://your-livekit-host:7880
LIVEKIT_KEY=your_key
LIVEKIT_SECRET=your_secret

# ── Dev helpers ───────────────────────────────
IGNORE_EMAIL_VERIF=false    # Set true to skip email verification in dev
```

---

## Running the app

### Development

```bash
cd src/backend
python3 run_server.py
```

Both processes start in the foreground. Press `Ctrl+C` to stop both.

### Production

Set `FLASK_ENV=prod` in `.env`. Waitress replaces Flask's dev server for the HTTP API. The WebSocket server always uses uvicorn.

```bash
cd src/backend
python3 run_server.py
```

For a persistent deployment, use a process manager such as `systemd` or `supervisor` to keep both processes running after logout.

---

## Troubleshooting

### 1 — `mariadb.OperationalError: Access denied` on startup

The credentials in `.env` don't match what MariaDB expects. Re-run the installer with root access:

```env
ROOT_ACCESS=true
DB_ROOT_USER=root
DB_ROOT_PASSWORD=your_root_password
```

```bash
python3 install_update_server.py
```

---

### 2 — Client shows "Server unreachable" immediately

Both server processes must be running. Check that ports `5123` and `8765` are open and listening:

```bash
ss -tlnp | grep -E '5123|8765'
```

Also verify `PUB_URL` in `.env` matches the hostname the client is connecting to.

---

### 3 — Emails are not being sent / verification code never arrives

- Use an **app-specific password**, not your regular account password.
- For Gmail, enable 2FA and generate an app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
- During development, bypass the check entirely with `IGNORE_EMAIL_VERIF=true`.

---

### 4 — VoIP call never connects

VoIP is a beta feature that requires a running LiveKit server.

- Confirm `LIVEKIT_URL`, `LIVEKIT_KEY`, and `LIVEKIT_SECRET` are set correctly in `.env`.
- Check that your LiveKit instance is reachable from the server: `curl http://your-livekit-host:7880`.
- Firewall rules must allow WebRTC UDP traffic (ports 50000–60000 by default for LiveKit).

If none of the above resolves the issue, there is currently no further workaround. VoIP is still in early development and known edge cases may not yet be addressed.

---

### 5 — `ModuleNotFoundError` on startup

Dependencies are not installed, or you are using the wrong Python environment.

```bash
pip install -r requirements.txt

# If using a virtual environment, activate it first:
source venv/bin/activate
pip install -r requirements.txt
```

---

### 6 — Linux: `dpkg` install fails with dependency errors

```bash
sudo apt --fix-broken install
sudo dpkg -i chatcli_0.4.1-beta_amd64.deb
```

---

### 7 — Port already in use (`Address already in use`)

Another process is using port `5123` or `8765`. Find and stop it:

```bash
sudo fuser -k 5123/tcp
sudo fuser -k 8765/tcp
```

---

## License

This project is licensed under the **GNU General Public License v3.0**.  
You are free to use, study, modify, and distribute it provided any derivative work is also licensed under GPLv3.

© 2024–2026 [FrostMantis](https://github.com/FrostMantis)
