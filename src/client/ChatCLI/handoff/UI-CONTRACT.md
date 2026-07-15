# ChatCLI — UI Contract & Rewrite Handoff

This document is the **contract** between the ChatCLI backend/Electron shell and the
renderer (UI). A UI that honours everything below works against the real app with no
backend changes.

You do **not** need to understand or run the backend to build the UI. You can build the
entire thing against the included mock (`mock-bridges.js`) in a normal browser.

**Intent:** this is meant to ship as the real, production ChatCLI — the version everyday,
non-technical users will actually use, so treat it as a finished product, not a throwaway
prototype. The look, feel, and UX are your call; this is context for your design
decisions, not a brief on them.

---

## 1. The seam — what you own vs. what you build on

The app is an Electron app with three layers:

```
┌─────────────────────────────────────────────┐
│  RENDERER  (HTML / CSS / JS)  ← YOU BUILD    │   src/renderer/**
├─────────────────────────────────────────────┤
│  PRELOAD bridges  (window.api, window.auth,  │   src/preload/**   ← PROVIDED
│  window.secureStore)  +  MAIN process        │   src/main/**      ← PROVIDED
├─────────────────────────────────────────────┤
│  BACKEND  (Flask REST + FastAPI WebSocket)   │   src/backend/**   ← FROZEN
└─────────────────────────────────────────────┘
```

**You own:** everything under `src/renderer/` — all HTML, CSS, and the UI JavaScript.
Build it however you like, in any framework.

**The hard contract — never changes:**
- `src/backend/**` — the servers. Your UI reaches them over the REST + WebSocket wire
  protocol in §4–§7. This is the real contract: any UI, on any stack, must speak it. The
  backend is off-limits to change without the owner.

**The provided host — recommended, but yours to replace:**
- `src/preload/**` + `src/main/**` are an Electron shell that hands you two things for
  free: secure token storage (OS keychain) and a working installer. **If you build inside
  it**, reach the backend through the `window.*` bridges (§3, §5, §8), speak the WebSocket
  protocol you open yourself (§6), and follow the build rules in §10 — and don't modify
  preload/main.
- **If you'd rather use a different stack**, you may replace the shell entirely. Then you
  talk to the backend directly over HTTPS/WSS with the same shapes, and you take on the
  shell's responsibilities yourself (secure token storage, packaging, CSP) — see §10.

Either way, the wire protocol in §4–§7 is fixed and everything under `src/renderer/` is
yours.

---

## 2. Conventions & architecture (build to these)

**Comments**
- A comment explains *how a non-obvious piece of code works*, for a future developer
  reading it cold. That is its only job.
- Do **not** write comments that narrate a change, restate what the diff did, address a
  reviewer, or reference a moment in time (no "no longer", "now does X", "temporary
  until", "was previously"). The code and its history are not the audience.
- If a line is self-explanatory, leave it uncommented. Prefer clear names over comments.

**Architecture — modular, not a monolith**
- Split the UI into small, focused modules/components grouped by feature (e.g. auth,
  chat list, message view, group management, calls, the realtime socket client, secure
  storage, shared UI primitives). One module, one responsibility. Avoid god-files.
- Keep server/session state in a clear central place; keep components presentational
  where practical, with a predictable one-way data flow.

**Weight — light, without cutting features**
- Keep the app reasonably lightweight: be deliberate about dependencies and bundle
  size, and reach for a library only when it earns its weight.
- Do **not** drop or degrade requested features to save size. Aim for a good balance —
  light *and* full-featured.

**Platform targets & technology**
- The app must be able to **run** on **Windows** and **Linux** (Debian/Ubuntu and Fedora
  families) at a minimum. You don't produce builds or installers — compiling and packaging
  are handled separately; just make sure the app runs on those platforms.
- You're not locked to any UI stack or app shell — use whatever technology you prefer, as
  long as it runs on those platforms and honours the backend contract (§4–§7).
- Target modern web standards; if you stay in the provided Electron (Chromium) shell,
  current Chromium features are safe — avoid non-standard or experimental APIs.
- Keep layouts responsive: don't hardcode a fixed window size — support resizing and a
  reasonable range of window dimensions.
- Don't bake in OS-specific assumptions (file paths, system fonts, key-combo labels).

---

## 3. Authentication & token lifecycle

Two token types come from the backend on login:
- **access token** — short-lived (1 day). Authenticates every request.
- **refresh token** — long-lived (60 days). Mints a new access token.

> **Naming:** the access token is stored under the key **`session_token`** and passed to
> REST endpoints in a field called **`session_token`**. "session token" and "access
> token" refer to the same value in this system.

**The recipe:**
- **REST authed endpoints:** put the access token in the JSON body as `session_token`,
  e.g. `{ "session_token": "<access>", "chatID": 12 }`.
- **WebSocket:** the first message sent after the socket opens must be
  `{ "type": "auth", "token": "<access>" }`.
- **Obtaining the access token:** `POST /user/login` returns it (§5). Persist it with
  `window.secureStore.set('session_token', <access>)` and the username with
  `window.secureStore.set('username', <name>)`.
- **Refreshing:** when a request fails auth, call `window.auth.refresh(username)` (§8).
  It returns `{ ok, access_token, refresh_token }`. Save the new access token and retry.

Login, verify, register, and refresh endpoints require no token.

---

## 4. Ground rules for REST

- Every endpoint is **HTTP POST** with a JSON body (including reads). There are no GET
  data endpoints.
- Base URL is `window.api.BASE_URL`.
- Call the typed helpers on `window.api` (§5) or call
  `window.api.request(path, { body: JSON.stringify({...}) })` directly. `request`
  unwraps the backend envelope:
  - backend `{ response: X }` → you get `X`
  - backend `{ message: "..." }` (single key) → you get the string
  - anything else → you get the object as-is
- On a non-2xx response, `request` **throws** an `Error` whose `.message` is the server's
  error message. Wrap calls in try/catch and surface `.message`.

---

## 5. REST API reference

Paths are relative to `window.api.BASE_URL`. "Auth" = needs `session_token` in the body.

Call authed endpoints via `window.api.request(path, { body: JSON.stringify({ session_token,
... }) })`. The typed chat helpers (`fetchChats()`, `fetchMessages()`, `createChat()`) do
**not** attach a token on their own — use `request()` for anything marked Auth. Table rows
show the server's response shape; because `request()` unwraps a lone `{message}`, those
endpoints reach you as a bare string (see §4).

### Auth / account

| Helper | Path | Body in | Returns | Auth |
|---|---|---|---|---|
| `window.api.login({username,password})` | `/user/login` | `{username,password}` | `{ message, access_token, refresh_token }` | no |
| `window.api.register({username,email,password,invite_code})` | `/user/register` | `{username,email,password,invite_code}` | success object | no |
| `window.api.verifyEmail({username,email_token})` | `/user/verify-email` | `{username,email_token}` | `{ message }` | no |
| `window.api.request('/user/resend-verification',…)` | `/user/resend-verification` | `{username}` | `{ message }` | no |
| `window.api.request('/user/reset-password-request',…)` | `/user/reset-password-request` | `{email}` | `{ message }` | no |
| `window.api.request('/user/refresh-token',…)` | `/user/refresh-token` | `{refresh_token}` | `{ access_token, refresh_token }` | no |

> Registration requires an **`invite_code`** (mandatory field). An invalid or exhausted
> code returns a thrown error with the message "Invalid or exhausted invite code."

> **Forgot-password** completes on a web page served by the backend, opened from an emailed
> link — not inside the app. `/user/reset-password-request` only triggers that email; don't
> build a reset-token screen in the client. You may redesign that page, but it must remain a
> **standalone, simple HTML page served by the backend**, not folded into the client app.

### Profile / account management (all Auth)

| Path | Body in | Returns |
|---|---|---|
| `/user/profile` | `{session_token}` | `{ username, email, … }` |
| `/user/submit-profile` | `{session_token, username, email}` or `{session_token, disable:1}` / `{session_token, delete:1}` | `{ message }` |
| `/user/change-password` | `{session_token, current_password, new_password}` | `{ message }` |
| `/user/logout` | `{session_token}` | `{ message }` |
| `/user/logout-all` | `{session_token}` | `{ message }` |

Changing username or email, disabling, deleting, or changing password each require a
re-login: after a success, clear stored tokens and route to the login screen.

### Chat / messages (all Auth)

| Path | Body in | Returns |
|---|---|---|
| `/chat/fetch-chats` | `{session_token}` | `[ { chatID, name, type }, … ]` — `type` is `"private"` \| `"group"`; `name` is the peer's username (private) or the group name (group) |
| `/chat/create-chat` | `{session_token, receiver}` | `{ chatID }` |
| `/chat/create-group` | `{session_token, name, members:[username,…]}` | `{ chatID }` |
| `/chat/messages` | `{session_token, chatID, limit?}` | `{ messages: [ Message, … ] }` (oldest→newest; `limit` 1–200, default 50) |
| `/chat/get-members` | `{session_token, chatID}` | `{ members: [username, …] }` |
| `/chat/add-members` | `{session_token, chatID, members:[…]}` | `{ message }` |
| `/chat/remove-members` | `{session_token, chatID, members:[…]}` | `{ message }` |
| `/chat/archive-chat` | `{session_token, chatID}` | `{ message }` |
| `/chat/unarchive-chat` | `{session_token, chatID}` | `{ message }` |
| `/chat/fetch-archived` | `{session_token}` | `[ { chatID, name, type }, … ]` |

**`Message` shape** (from `/chat/messages` and from live `new_message`/`edited_message`):
```jsonc
{
  "messageID": 123,
  "chatID": 12,
  "userID": 4,
  "username": "alice",
  "message": "hello world",
  "timestamp": "2026-07-15T18:30:00",   // ISO 8601
  "edited_at": null,                     // ISO string if edited, else null
  "deleted_at": null                     // ISO string if deleted, else null
}
```
A deleted message has `deleted_at` set and its `message` replaced by `"--deleted--"`.
Render deleted messages as a muted "(message deleted)" placeholder.

Timestamps are ISO 8601 and may have **no timezone suffix** (e.g. `2026-07-15T18:30:00`) —
parse defensively and treat them as the server's clock.

---

## 6. WebSocket protocol (chat, presence, calls)

One primary WebSocket carries chat + presence + call **signaling**: `window.api.WS_URL`.
A second socket (`window.api.CALL_URL` + `/call/{call_id}`) belongs to a WebRTC signaling
path that the LiveKit-based calls do not require; it is not needed for this UI.

### Connecting

```js
const ws = new WebSocket(window.api.WS_URL);
ws.addEventListener('open', () => {
  ws.send(JSON.stringify({ type: 'auth', token: accessToken }));
  ws.send(JSON.stringify({ type: 'join_idle' }));   // optional; the app sends it after auth
});
ws.addEventListener('message', (ev) => handle(JSON.parse(ev.data)));
```

- On success the server sends `{type:'auth_ack', status:'ok'}` then
  `{type:'online_users', users:[…]}`.
- **Close code `1008`** = auth failed → do not retry; return to login.
- **Close code `1000`** = server closed this session (a second login for the same user
  supersedes the first; one live socket per user) → do not retry; show a message, go to
  login.
- Any other close → reconnect with backoff, re-sending `auth` on each reconnect.

### Messages you SEND (client → server)

| type | payload | effect |
|---|---|---|
| `auth` | `{token}` | required first message |
| `join_idle` | `{}` | optional; the app sends it after auth — `chat_created` and calls reach your authenticated connection regardless |
| `join_chat` | `{chatID}` | subscribe to a chat's live messages (required to receive them) |
| `leave_chat` | `{chatID}` | unsubscribe |
| `post_msg` | `{chatID, text}` | send a message |
| `edit_msg` | `{chatID, messageID, text}` | edit your own message |
| `delete_msg` | `{chatID, messageID}` | delete your own message (soft delete) |
| `typing` | `{chatID}` | broadcast a typing ping to others in the chat |
| `chat_created` | `{chatID}` | notify participants they were added to a chat/group |
| `call_invite` | `{chatID}` | start a call in this chat |
| `call_accept` | `{chatID, call_id}` | accept/join the ringing call |
| `call_decline` | `{chatID}` | decline the ringing call |
| `call_end` | `{chatID}` | leave/end the call |

Notes:
- You receive live messages for a chat only after you `join_chat` it.
- `post_msg`/`edit_msg`/`delete_msg` are broadcast back to you as the corresponding
  `new_message`/`edited_message`/`deleted_message`. De-dupe on `messageID`, since your
  own sends echo back.
- The backend enforces no per-message character limit. If you cap message length in the
  UI, splitting overly long text into multiple messages is one workable approach.

### Messages you RECEIVE (server → client)

| type | payload | meaning |
|---|---|---|
| `auth_ack` | `{status:'ok'}` | auth succeeded |
| `online_users` | `{users:[username,…]}` | which of your contacts are online |
| `new_message` | `Message` (§5) | a new message in a chat you've joined |
| `edited_message` | `Message` (§5) | a message was edited |
| `deleted_message` | `{messageID, chatID, deleted_at}` | a message was deleted |
| `user_typing` | `{username, chatID}` | someone is typing (auto-expire after ~3s) |
| `user_status` | `{username, online}` | a contact went online/offline |
| `chat_created` | `{chatID, creator}` | you were added to a chat/group (reload chat list) |
| `error` | `{message}` | generic server-side error for your last action |

Call-related server → client messages are in §7.

---

## 7. Calls

**Status:** calls use **LiveKit**. They are not yet reliable end-to-end and function only
on a LAN. Build the call UI against the mock's call events (§9), which drive every visual
state cleanly. The call backend emits the messages below, so a UI built to them works once
calls are reliable. Do not try to make real calls connect end-to-end as part of this work.

### The call UI state machine

Model the call UI as a 4-state machine:

| state | meaning | entered when |
|---|---|---|
| `idle` | no call | default; after any call ends |
| `outgoing` | you started a call, waiting for someone to join (ringback) | you send `call_invite`; you are the caller in the `call_invite` broadcast |
| `incoming` | someone is calling a chat you're in (ringtone + accept/decline) | you receive `call_invite` where you are **not** the caller |
| `in-call` | connected, audio via LiveKit | you receive `call_accepted`, or `call_state` with `state:"active"` |

### Client → server call messages
`call_invite`, `call_accept`, `call_decline`, `call_end` (see §6).

### Server → client call messages

| type | payload | UI reaction |
|---|---|---|
| `call_invite` | `{chatID, call_id, caller, lk_token, lk_url}` | caller is you → go `outgoing` + join LiveKit room; else → go `incoming`, ring, show accept/decline |
| `call_accepted` | `{chatID, call_id, accepted_by, lk_token, lk_url}` | go `in-call`, stop ringback, join LiveKit room |
| `call_declined` | `{chatID, call_id, by, initiator}` | the other side declined → `idle` |
| `call_ended` | `{chatID, call_id, ended_by, initiator}` | call over → `idle` |
| `call_error` | `{chatID, code, message}` | show `message`; `code` ∈ `ACCESS_DENIED`, `CALL_NOT_FOUND`, `SESSION_NOT_FOUND` |
| `call_state` | `{chatID, call_id, initiator, state}` | current call state when you open a chat mid-call; `state` ∈ `ringing`\|`active`\|`ended`. Defined in the protocol but not currently emitted by the backend |

### LiveKit (media)

`call_invite` / `call_accepted` carry `lk_token` (a JWT) and `lk_url` (the LiveKit server
URL). Audio is handled by the **livekit-client** SDK: connect with `(lk_url, lk_token)`,
publish the mic track, subscribe to remote audio. The room name is the `chatID`. For UI
work this is stubbed — the mock drives the `in-call` visual state without real media.

Mic handling: request the mic; if none is present, the user can still *join* a call but
can't be heard — show a warning and disable the mute button.

---

## 8. Secure storage & token bridges (provided; you call them)

Backed by the OS keychain via the Electron main process. Under the browser + mock they
are faked with in-memory storage.

```js
// Access-token / small-value store (string values)
await window.secureStore.set('session_token', accessToken);
await window.secureStore.get('username');        // → string | null
await window.secureStore.delete('refresh_token');

// Refresh-token helper (keychain-backed), keyed by account/username
await window.auth.storeRefresh(username, refreshToken);
await window.auth.refresh(username);   // → { ok, access_token, refresh_token }
await window.auth.clear(username);     // logout: wipe stored refresh token
```

Keys in use: `username`, `email`, `session_token`, `refresh_token`.

Outside the Electron shell, provide an equivalent secure, persistent store for these
values on each target platform.

---

## 9. Building against the mock (no backend, no Electron)

`mock-bridges.js` installs fake `window.api`, `window.auth`, `window.secureStore` plus a
fake WebSocket, all with sample data. It lets you develop the whole UI in a plain browser
with hot-reload and drive every state — including all call states — by hand.

### Wire it up

At the top of your app entry (before anything reads `window.api`):

```js
import { installMocks, MockChatSocket } from './handoff/mock-bridges.js';

const USE_MOCK = import.meta.env?.DEV ?? true;   // or your own flag
if (USE_MOCK) installMocks();

// When you open the chat socket, pick the mock or the real one:
const ws = USE_MOCK ? new MockChatSocket() : new WebSocket(window.api.WS_URL);
```

That is the only mock-specific code. Guard it behind one flag so the production build uses
the real `window.*` and the real `WebSocket`.

### Drive the UI from the console

`window.__mock` is the control panel:

```js
__mock.incomingMessage(1, 'bob', 'hey, you around?'); // a message from someone else
__mock.userTyping(1, 'bob');                          // typing indicator
__mock.setOnline('bob', false);                       // presence change
__mock.incomingCall(1, 'bob');                        // ring an incoming call
__mock.callAccepted(1, 'bob');                        // remote accepted → in-call
__mock.callEnded(1, 'bob');                           // hang up
__mock.callError(1, 'ACCESS_DENIED', 'Not allowed.'); // error path
__mock.kick('Logged in elsewhere.');                  // server closes the session
__mock.reset();                                        // back to clean sample data
```

Any username/password logs in. The sample world (chats, groups, a long-scroll
conversation, edited/deleted/long/multi-line messages, presence) is defined at the top of
`mock-bridges.js` — edit the fixtures to taste.

The mock does **not** enforce authentication — it returns chat data without checking for a
`session_token`. Don't rely on it to catch a missing token; follow §5 and send
`session_token` on authed calls, or those calls will fail against the real backend.

---

## 10. Framework & build boundary

Any framework is fine (React/Vue/Svelte/etc.), and you may keep or replace the Electron
shell (§1). Target platforms are Windows and Linux (§2); compiling and packaging into
installers are handled by the owner, not you.

**If you build inside the provided Electron shell** — its build tooling is fragile and
expensive to reproduce, so:

1. **Emit plain static assets** — HTML/CSS/JS loaded by Electron via `file://`. Configure
   a **relative base** (Vite: `base: './'`) so paths resolve from `file://`. No dev server
   or remote origin in the shipped build.
2. **Do not change** `forge.config.js`, the packaging scripts, `src/main/**`, or
   `src/preload/**`. Electron loads the renderer's entry HTML; your build produces that
   entry + assets where the shell expects them. Coordinate that one path with the owner —
   it is the single integration point.
3. **Renderer code runs in the browser context:** use `window.api` / `window.auth` /
   `window.secureStore` and the browser `WebSocket` only. No Node built-ins or `require()`.
4. **External resources are CSP-restricted.** Bundle fonts and assets locally. Calls use
   the livekit-client SDK; account for it under the CSP if you keep calls (stubbed for UI
   work).
5. Keep bundle output self-contained and offline-capable.

Flow: build the UI in the browser against the mock, get it right, then do one integration
pass with the owner to drop the built assets into the Electron shell and smoke-test
against the real backend.

**If you replace the shell with a different stack**, you own what the shell provided:
- secure, persistent token storage on each platform (the keychain equivalent);
- a strict content-security posture (no loading remote code);
- talking to the backend directly over HTTPS/WSS with the shapes in §4–§7 — the `window.*`
  bridges won't exist, so call REST/WS yourself.

Pick a stack that can run on Windows and Linux, and coordinate the build with the owner
(who handles compiling and packaging) along with backend URLs and any CORS needs.

---

## 11. Screens & states to cover (checklist)

**Auth / onboarding**
- Welcome, Login, Register (includes an **invite code** field), Email verify (6-digit
  code + resend), Password-reset request. Form validation, inline errors, toasts.

**Main app**
- Chat list (private + group; online/offline indicator for private; archived section).
- Create private chat / create group (name + comma-separated members).
- Message view: messages clustered by author + time, own vs. others, avatars/initials,
  timestamps, "(edited)" indicator, "(message deleted)" placeholder, edit & delete actions
  on your own messages, typing indicator, long-message handling.
- Group management: view members, add/remove (participants only).
- Profile: view/edit username + email, change password, disable, delete (each requires
  re-login).
- Presence reflected live.

**Calls (build against the mock)**
- Call control per private chat with `idle`/`outgoing`/`incoming`/`in-call` visuals.
- Incoming-call modal (caller, accept/decline, ringtone).
- Outgoing ringback state.
- In-call controls: mute/unmute, leave; no-mic warning state.
- Error handling for `call_error`.

**Global**
- Reconnect / connection-lost UX, superseded-session close, session-expired → login.
- Light/dark theming via a token-based system (CSS custom properties).

---

*Questions about anything frozen (backend shapes, bridges, build) go to the owner.
Everything under `src/renderer/` is yours.*
