/**
 * mock-bridges.js — a backend-free stand-in for ChatCLI's Electron bridges.
 *
 * Installs fake `window.api`, `window.auth`, `window.secureStore`, and a fake
 * `MockChatSocket` so a new UI can run in a plain browser (no Electron, no server)
 * and be driven through every state — including all call states — by hand.
 *
 * Usage (see handoff/UI-CONTRACT.md §8):
 *
 *   import { installMocks, MockChatSocket } from './handoff/mock-bridges.js';
 *   if (USE_MOCK) installMocks();
 *   const ws = USE_MOCK ? new MockChatSocket() : new WebSocket(window.api.WS_URL);
 *
 * Then drive the UI from the browser console via `window.__mock`.
 *
 * This file speaks exactly the shapes documented in UI-CONTRACT.md. It is the
 * contract made runnable — if the real backend and this file disagree, the doc wins
 * and this file should be corrected.
 */

/* ============================================================================
 * FIXTURES — edit these to change the sample world the mock serves.
 * ========================================================================== */

const SELF = 'alice'; // the account "you" are logged in as in the mock

const USERS = ['alice', 'bob', 'carol', 'dave', 'erin', 'frank', 'grace'];

const CHATS = [
  { chatID: 1, name: 'bob', type: 'private' },
  { chatID: 2, name: 'Weekend Plans', type: 'group' },
  { chatID: 3, name: 'carol', type: 'private' },
  { chatID: 4, name: 'Project Phoenix', type: 'group' },
  { chatID: 5, name: 'dave', type: 'private' },
  { chatID: 6, name: 'erin', type: 'private' },
];

const MEMBERS = {
  2: ['alice', 'bob', 'carol'],
  4: ['alice', 'bob', 'carol', 'dave', 'erin', 'frank', 'grace'],
};

const LONG_MESSAGE =
  'Alright, full brain-dump on the release plan so it\'s all in one place:\n\n' +
  '1. Freeze the schema Friday. 2. Cut a release branch and run the smoke test on ' +
  'both machines. 3. If calls hold up on LAN we tag it; if not we ship chat-only and ' +
  'follow up. 4. Somebody needs to write the changelog because last time we forgot ' +
  'half of it and people were confused for a week.\n\n' +
  'Also: please, PLEASE test on a fresh install and not your dev box. Every single ' +
  'time "works on my machine" has bitten us it was because nobody did a clean install.';

// Filler lines used to bulk out one chat so long-list / scroll behaviour is testable.
const FILLER_LINES = [
  'did you see the latest build?', 'yeah, looks way cleaner', 'the sidebar feels snappier now',
  'agreed', 'one sec, testing something', 'ok that works', 'nice', 'push it when you can',
  'done', 'pulling now', 'hmm getting an error', 'what does it say?', 'never mind, stale cache',
  'classic', 'lol', 'anyway lunch?', 'give me 20', 'sounds good', '👍', 'brb',
];

// Seed messages per chat. Optional flags: edited:true, deleted:true.
const SEED_MESSAGES = {
  1: [
    { username: 'bob', message: 'yo', minsAgo: 2880 },
    { username: 'alice', message: 'hey! what\'s up', minsAgo: 2878 },
    { username: 'bob', message: 'not much. you around this weekend?', minsAgo: 2875 },
    { username: 'alice', message: 'should be, why?', minsAgo: 2870 },
    { username: 'bob', message: 'thinking of doing the thing we talked about', minsAgo: 2869 },
    { username: 'bob', message: 'this message had a typo in it originally', minsAgo: 1500, edited: true },
    { username: 'alice', message: 'oops ignore that', minsAgo: 1400, deleted: true },
    { username: 'bob', message: LONG_MESSAGE, minsAgo: 1200 },
    { username: 'alice', message: 'ok that\'s a lot but yes, agreed on all of it', minsAgo: 1180 },
    { username: 'bob', message: 'multi\nline\nmessage\nto test wrapping + height', minsAgo: 60 },
    { username: 'alice', message: 'looks fine on my end 🎉', minsAgo: 55 },
    { username: 'bob', message: 'you around later?', minsAgo: 3 },
  ],
  2: [
    { username: 'carol', message: 'who\'s free saturday?', minsAgo: 400 },
    { username: 'alice', message: 'i am', minsAgo: 395 },
    { username: 'bob', message: 'same', minsAgo: 393 },
    { username: 'carol', message: 'great, i\'ll book something', minsAgo: 390 },
  ],
  3: [
    { username: 'carol', message: 'sent you the doc', minsAgo: 5000 },
    { username: 'alice', message: 'got it, reading now', minsAgo: 4990 },
    { username: 'carol', message: 'no rush', minsAgo: 4980 },
  ],
  4: [
    { username: 'dave', message: 'kickoff for phoenix — everyone here?', minsAgo: 6000 },
    { username: 'frank', message: 'present', minsAgo: 5998 },
    { username: 'grace', message: 'here', minsAgo: 5997 },
    { username: 'alice', message: 'ready', minsAgo: 5996 },
    // long-scroll filler is appended programmatically in seed()
  ],
  5: [
    { username: 'dave', message: 'thanks for the review!', minsAgo: 300 },
  ],
  6: [
    { username: 'alice', message: 'hey erin, welcome aboard 👋', minsAgo: 120 },
    { username: 'erin', message: 'thanks! excited to be here', minsAgo: 118 },
  ],
};

const ONLINE = new Set(['bob', 'carol', 'grace']); // online at start (besides you)

/* ============================================================================
 * Internal mutable state
 * ========================================================================== */

let nextMessageID = 1000;
const messagesByChat = {}; // chatID -> Message[]
const liveSockets = new Set(); // all open MockChatSocket instances
const ARCHIVED = new Set(); // chatIDs the mock currently considers archived

function nowISO(minsAgo = 0) {
  // The backend stamps rows with `datetime.now()` — the server's *local* clock,
  // serialised without a timezone suffix. Formatting UTC and stripping the "Z"
  // would produce the right shape but the wrong instant, so build the string
  // from local components and let the client read it as its own clock.
  const d = new Date(Date.now() - minsAgo * 60_000);
  const pad = (n, width = 2) => String(n).padStart(width, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
  );
}

function userId(username) {
  const i = USERS.indexOf(username);
  return i >= 0 ? i + 1 : 99;
}

function makeMessage({ chatID, username, message, messageID, edited_at = null, deleted_at = null, edited = false, deleted = false, minsAgo = 0 }) {
  return {
    messageID: messageID ?? nextMessageID++,
    chatID,
    userID: userId(username),
    username,
    message: deleted ? '--deleted--' : message,
    timestamp: nowISO(minsAgo),
    edited_at: edited ? nowISO(Math.max(0, minsAgo - 1)) : edited_at,
    deleted_at: deleted ? nowISO(Math.max(0, minsAgo - 1)) : deleted_at,
  };
}

function seed() {
  nextMessageID = 1000;
  ARCHIVED.clear();
  for (const c of CHATS) messagesByChat[c.chatID] = [];
  for (const [chatID, msgs] of Object.entries(SEED_MESSAGES)) {
    for (const m of msgs) {
      messagesByChat[chatID].push(makeMessage({ chatID: Number(chatID), ...m }));
    }
  }

  // Bulk one chat out to a long list so scroll / virtualisation is testable.
  const fillerChat = 4;
  const authors = MEMBERS[fillerChat] || USERS;
  for (let i = 0; i < 40; i++) {
    messagesByChat[fillerChat].push(makeMessage({
      chatID: fillerChat,
      username: authors[i % authors.length],
      message: FILLER_LINES[i % FILLER_LINES.length],
      minsAgo: 1200 - i * 25,
    }));
  }
}
seed();

/** Push a server→client frame to every open mock socket. */
function pushToSockets(obj) {
  for (const s of liveSockets) s._deliver(obj);
}

/* ============================================================================
 * MockChatSocket — mimics the browser WebSocket interface closely enough for a
 * UI to use it as a drop-in replacement.
 * ========================================================================== */

export class MockChatSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(_url) {
    this.url = _url || (window.api && window.api.WS_URL) || 'mock://ws';
    this.readyState = MockChatSocket.CONNECTING;
    this._listeners = { open: [], message: [], close: [], error: [] };
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;

    liveSockets.add(this);
    // Open on next tick, like a real socket.
    setTimeout(() => {
      if (this.readyState !== MockChatSocket.CONNECTING) return;
      this.readyState = MockChatSocket.OPEN;
      this._emit('open', {});
    }, 0);
  }

  addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    const arr = this._listeners[type];
    if (arr) this._listeners[type] = arr.filter((f) => f !== fn);
  }

  _emit(type, event) {
    const handler = this['on' + type];
    if (typeof handler === 'function') handler(event);
    for (const fn of this._listeners[type] || []) fn(event);
  }

  /** Deliver a server→client object as a `message` event. */
  _deliver(obj) {
    if (this.readyState !== MockChatSocket.OPEN) return;
    this._emit('message', { data: JSON.stringify(obj) });
  }

  send(raw) {
    let msg;
    try { msg = JSON.parse(raw); } catch { return; }
    this._handleClientMessage(msg);
  }

  close(code = 1000, reason = '') {
    if (this.readyState === MockChatSocket.CLOSED) return;
    this.readyState = MockChatSocket.CLOSED;
    liveSockets.delete(this);
    this._emit('close', { code, reason, wasClean: true });
  }

  /** Emulate the server's reaction to each client→server message type. */
  _handleClientMessage(msg) {
    switch (msg.type) {
      case 'auth':
        this._deliver({ type: 'auth_ack', status: 'ok' });
        this._deliver({ type: 'online_users', users: [...ONLINE] });
        break;

      case 'join_idle':
      case 'join_chat':
      case 'leave_chat':
      case 'typing':
        // no direct server reply
        break;

      case 'post_msg': {
        const m = makeMessage({ chatID: msg.chatID, username: SELF, message: msg.text });
        messagesByChat[msg.chatID] ||= [];
        messagesByChat[msg.chatID].push(m);
        pushToSockets({ type: 'new_message', ...m });
        break;
      }

      case 'edit_msg': {
        const list = messagesByChat[msg.chatID] || [];
        const m = list.find((x) => x.messageID === msg.messageID);
        if (m) {
          m.message = msg.text;
          m.edited_at = nowISO();
          pushToSockets({ type: 'edited_message', ...m });
        }
        break;
      }

      case 'delete_msg': {
        const list = messagesByChat[msg.chatID] || [];
        const m = list.find((x) => x.messageID === msg.messageID);
        if (m) {
          m.message = '--deleted--';
          m.deleted_at = nowISO();
          pushToSockets({ type: 'deleted_message', messageID: m.messageID, chatID: m.chatID, deleted_at: m.deleted_at });
        }
        break;
      }

      case 'chat_created':
        // server would notify *other* participants; nothing to echo to sender
        break;

      // ---- calls: echo the server's broadcast back so the caller's UI advances ----
      case 'call_invite':
        pushToSockets({
          type: 'call_invite', chatID: msg.chatID, call_id: mockCallId(),
          caller: SELF, lk_token: 'mock-token', lk_url: 'mock://livekit',
        });
        break;

      case 'call_accept':
        pushToSockets({
          type: 'call_accepted', chatID: msg.chatID, call_id: msg.call_id || mockCallId(),
          accepted_by: SELF, lk_token: 'mock-token', lk_url: 'mock://livekit',
        });
        break;

      case 'call_decline':
        pushToSockets({ type: 'call_declined', chatID: msg.chatID, call_id: mockCallId(), by: SELF, initiator: SELF });
        break;

      case 'call_end':
        pushToSockets({ type: 'call_ended', chatID: msg.chatID, call_id: mockCallId(), ended_by: SELF, initiator: SELF });
        break;

      default:
        this._deliver({ type: 'error', message: `Unknown action: ${msg.type}` });
    }
  }
}

let _callSeq = 0;
function mockCallId() { return `mock-call-${++_callSeq}`; }

/* ============================================================================
 * Fake window.api (REST)
 * ========================================================================== */

function buildApi() {
  const ok = (v) => Promise.resolve(v);
  const fail = (message) => Promise.reject(new Error(message));

  const api = {
    BASE_URL: 'mock://api',
    WS_URL: 'mock://ws',
    CALL_URL: 'mock://call',

    // Generic passthrough mirroring the real request() unwrapping.
    request(path, options = {}) {
      let body = {};
      try { body = options.body ? JSON.parse(options.body) : {}; } catch { body = {}; }
      return routeRest(path, body, ok, fail);
    },

    login: ({ username }) => ok({ message: 'Login successful', access_token: 'mock-access', refresh_token: 'mock-refresh', username }),
    register: () => ok({ message: 'Account created. Check your email for a code.' }),
    verifyEmail: () => ok({ message: 'Email verified.' }),
    fetchChats: () => ok(CHATS.filter((c) => !ARCHIVED.has(c.chatID))),
    fetchMessages: (chatID, limit = 100) => ok({ messages: (messagesByChat[chatID] || []).slice(-limit) }),
    createChat: (receiver) => ok({ chatID: nextChatId(receiver) }),
  };
  return api;
}

// Route direct request(path, body) calls to the same fixtures.
function routeRest(path, body, ok, fail) {
  switch (path) {
    case '/user/login': return ok({ message: 'Login successful', access_token: 'mock-access', refresh_token: 'mock-refresh' });
    case '/user/register': return ok({ message: 'Account created.' });
    case '/user/verify-email': return ok({ message: 'Email verified.' });
    case '/user/resend-verification': return ok({ message: 'Verification code sent.' });
    case '/user/reset-password-request': return ok({ message: 'If that email exists, a reset link is on its way.' });
    case '/user/refresh-token': return ok({ access_token: 'mock-access-2', refresh_token: 'mock-refresh-2' });
    case '/user/profile': return ok({ username: SELF, email: `${SELF}@example.com` });
    case '/user/submit-profile': return ok({ message: 'Saved.' });
    case '/user/change-password': return ok({ message: 'Password updated.' });
    case '/user/logout':
    case '/user/logout-all': return ok({ message: 'Logged out.' });
    // The real endpoints partition the same set, so archiving has to move a chat
    // between the two lists rather than leave both unchanged.
    case '/chat/fetch-chats': return ok(CHATS.filter((c) => !ARCHIVED.has(c.chatID)));
    case '/chat/fetch-archived': return ok(CHATS.filter((c) => ARCHIVED.has(c.chatID)));
    case '/chat/messages': return ok({ messages: (messagesByChat[body.chatID] || []).slice(-(body.limit || 50)) });
    case '/chat/create-chat': return ok({ chatID: nextChatId(body.receiver) });
    case '/chat/create-group': return ok({ chatID: nextChatId(body.name) });
    case '/chat/get-members': return ok({ members: MEMBERS[body.chatID] || [] });
    case '/chat/add-members':
    case '/chat/remove-members': return ok({ chatID: body.chatID });
    case '/chat/archive-chat': ARCHIVED.add(Number(body.chatID)); return ok({ message: 'Done.' });
    case '/chat/unarchive-chat': ARCHIVED.delete(Number(body.chatID)); return ok({ message: 'Done.' });
    default: return fail(`Mock has no route for ${path}`);
  }
}

let _chatSeq = 100;
function nextChatId(name) {
  const id = ++_chatSeq;
  CHATS.push({ chatID: id, name: name || `chat-${id}`, type: 'private' });
  messagesByChat[id] = [];
  return id;
}

/* ============================================================================
 * Fake window.auth + window.secureStore (in-memory)
 * ========================================================================== */

function buildSecureStore() {
  const mem = new Map([['username', SELF], ['session_token', 'mock-access']]);
  return {
    set: (k, v) => { mem.set(k, v); return Promise.resolve(true); },
    get: (k) => Promise.resolve(mem.has(k) ? mem.get(k) : null),
    delete: (k) => { mem.delete(k); return Promise.resolve(true); },
  };
}

function buildAuth() {
  return {
    storeRefresh: () => Promise.resolve(true),
    // The real handler rotates the refresh token into the keychain itself and
    // hands back only the access token; failures come back as { ok: false, reason }.
    refresh: () => Promise.resolve({ ok: true, access_token: 'mock-access-2' }),
    clear: () => Promise.resolve(true),
  };
}

/* ============================================================================
 * __mock — the console control panel for driving server-pushed events.
 * ========================================================================== */

function buildControlPanel() {
  return {
    /** A message arrives from another user in `chatID`. */
    incomingMessage(chatID, username, text) {
      const m = makeMessage({ chatID, username, message: text });
      (messagesByChat[chatID] ||= []).push(m);
      pushToSockets({ type: 'new_message', ...m });
    },
    userTyping(chatID, username) { pushToSockets({ type: 'user_typing', username, chatID }); },
    setOnline(username, online) {
      if (online) ONLINE.add(username); else ONLINE.delete(username);
      pushToSockets({ type: 'user_status', username, online: !!online });
    },
    chatCreated(chatID, creator) { pushToSockets({ type: 'chat_created', chatID, creator }); },

    /** Ring an incoming call from `caller` in `chatID`. */
    incomingCall(chatID, caller) {
      pushToSockets({ type: 'call_invite', chatID, call_id: mockCallId(), caller, lk_token: 'mock-token', lk_url: 'mock://livekit' });
    },
    callAccepted(chatID, by) {
      pushToSockets({ type: 'call_accepted', chatID, call_id: mockCallId(), accepted_by: by, lk_token: 'mock-token', lk_url: 'mock://livekit' });
    },
    callDeclined(chatID, by) { pushToSockets({ type: 'call_declined', chatID, call_id: mockCallId(), by, initiator: SELF }); },
    callEnded(chatID, by) { pushToSockets({ type: 'call_ended', chatID, call_id: mockCallId(), ended_by: by, initiator: SELF }); },
    callState(chatID, state, initiator = SELF) { pushToSockets({ type: 'call_state', chatID, call_id: mockCallId(), initiator, state }); },
    callError(chatID, code, message) { pushToSockets({ type: 'call_error', chatID, code, message }); },

    /** Simulate the server kicking this session (logged in elsewhere). */
    kick(reason = 'Logged in elsewhere.') { for (const s of liveSockets) s.close(1000, reason); },

    /** Reset fixtures to their seeded state. */
    reset() { seed(); },

    // Expose fixtures for inspection/editing at runtime.
    _state: { CHATS, MEMBERS, messagesByChat, ONLINE, SELF },
  };
}

/* ============================================================================
 * installMocks — call once, before anything reads window.api.
 * ========================================================================== */

export function installMocks() {
  if (window.__mockInstalled) return window.__mock;
  window.api = buildApi();
  window.auth = buildAuth();
  window.secureStore = buildSecureStore();
  window.__mock = buildControlPanel();
  window.__mockInstalled = true;
  // Optional convenience: let code that does `new WebSocket()` get the mock too.
  // (Leave the real WebSocket in place by default; opt in explicitly if you want this.)
  console.info('[mock] bridges installed. Drive the UI with window.__mock — e.g. __mock.incomingCall(1, "bob").');
  return window.__mock;
}

export default installMocks;
