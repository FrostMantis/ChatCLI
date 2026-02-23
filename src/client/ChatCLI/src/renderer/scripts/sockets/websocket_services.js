import { store } from '../core/store.js';
import { showToast } from '../ui/toasts.js';

let ws;
let isConnecting = false;

// ---- Reconnect backoff (unbounded, capped at MAX) ----
let reconnectAttempts = 0;
const RETRY_DELAYS_MS = [5000, 10000, 20000]; // 3 attempts

// ---------- Utility: reconnect scheduling ----------
function nextDelay() {
  const raw = Math.min(BACKOFF_MAX, BACKOFF_BASE * 2 ** reconnectAttempts);
  // jitter 80–120%
  return Math.floor(raw * (0.8 + Math.random() * 0.4));
}

function shouldHoldReconnect() {
  if (navigator && 'onLine' in navigator && !navigator.onLine) return true;
  if (document && typeof document.hidden === 'boolean' && document.hidden) return true;
  return false;
}

function scheduleReconnect(reason = '') {
  if (shouldHoldReconnect()) return;

  if (reconnectAttempts >= RETRY_DELAYS_MS.length) {
    console.error('[CHAT-WS] Max retries reached. Redirecting to index.html.');

    // Tell index *why* we’re going back + avoid auto-login spam
    try {
      sessionStorage.setItem(
        'redirect_reason',
        'Unable to connect to the server. Please try again later.'
      );
      sessionStorage.setItem('skip_auto_login_once', '1');
    } catch (_) {}

    store.preventReconnect = true;
    window.location.href = 'index.html';
    return;
  }

  const delay = RETRY_DELAYS_MS[reconnectAttempts++];
  console.warn(`[CHAT-WS] Reconnecting in ${delay}ms (${reason})`);
  setTimeout(connectWS, delay);
}

// ---------- Main connect ----------
export function connectWS() {
  if (isConnecting || (ws && ws.readyState === WebSocket.OPEN)) return;
  if (shouldHoldReconnect()) return;

  isConnecting = true;
  try {
    ws = new WebSocket(window.api.WS_URL);
    store.WS_URL = window.api.WS_URL;
    store.ws = ws;
  } catch (e) {
    isConnecting = false;
    scheduleReconnect('ctor-failed');
    return;
  }

  ws.addEventListener('open', () => {
    reconnectAttempts = 0;
    isConnecting = false;
    console.log('[CHAT-WS] Connected ✅');

    if (store.token) {
      ws.send(JSON.stringify({ type: 'auth', token: store.token }));
    }
    ws.send(JSON.stringify({ type: 'join_idle' }));
  });

  ws.addEventListener('close', (event) => {
    console.warn('[CHAT-WS] Closed ❌', event.code, event.reason);
    isConnecting = false;

    // 1008: policy / auth failure → do NOT retry
    if (event.code === 1008) {
      console.error('[CHAT-WS] Authentication failed. Not retrying.');

      try {
        sessionStorage.setItem(
          'redirect_reason',
          'Authentication failed. Please log in again.'
        );
        sessionStorage.setItem('skip_auto_login_once', '1');
      } catch (_) {}

      store.preventReconnect = true;
      window.location.href = 'index.html';
      return;
    }

    // 1000: normal closure used by server to kick this client
    if (event.code === 1000) {
      console.warn('[CHAT-WS] Closed by server with code 1000. Not retrying.');

      const msg =
        (event.reason && event.reason.trim()) ||
        'You were logged out from this session (for example by logging in from another location).';

      try {
        sessionStorage.setItem('redirect_reason', msg);
        sessionStorage.setItem('skip_auto_login_once', '1');
      } catch (_) {}

      store.preventReconnect = true;
      window.location.href = 'index.html';
      return;
    }

    // Other close codes → 3-step retry
    scheduleReconnect('close');
  });

  ws.addEventListener('error', (error) => {
    console.error('[CHAT-WS] Error', error);
    isConnecting = false;
    showToast('Connection issue. Reconnecting…', 'error');
    scheduleReconnect('error');
  });

  // ---------- Main message handler (ASYNC) ----------
  ws.addEventListener('message', async (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      console.warn('[CHAT-WS] Bad JSON', event.data);
      return;
    }

    if (msg === null) {
        return; 
    }

    // Handle the "online_users" message type
    if (msg.type === 'online_users') {
      window.dispatchEvent(new CustomEvent('chat:online-users', { detail: msg.users }));
      return;
    }

    // Chat messages
    if (msg.type === 'new_message') {
      if (store.seenMessageIDs.has(msg.messageID)) return;
      store.seenMessageIDs.add(msg.messageID);
      window.dispatchEvent(new CustomEvent('chat:new-message', { detail: msg }));
      return;
    }

    if (msg.type === 'edited_message') {
      console.log('Dispatching edited_message event:', msg);
      window.dispatchEvent(new CustomEvent('chat:edited-message', { detail: msg }));
      return;
    }

    if (msg.type === 'deleted_message') {
      console.log('Dispatching deleted_message event:', msg);
      window.dispatchEvent(new CustomEvent('chat:deleted-message', { detail: msg }));
      return;
    }

    if (msg.type === 'user_typing' &&
        msg.chatID === store.currentChatID &&
        msg.username.toLowerCase() !== (store.username || '').toLowerCase()) {
      window.dispatchEvent(new CustomEvent('chat:user-typing', { detail: msg.username }));
      return;
    }

    if (msg.type === 'user_status') {
      window.dispatchEvent(new CustomEvent('chat:user-status', { detail: msg }));
      return;
    }

    if (msg.type === 'chat_created') {
      console.log("chat_created called");
      window.dispatchEvent(new CustomEvent('chat:chat_created', { detail: msg }));
      return;
    }
    window.dispatchEvent(new CustomEvent('global:msg', { detail: msg }));
  });
}

// ---------- Sending ----------
export function WSSend(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
  }
}

// ---------- Resume logic ----------
function resumeIfNeeded() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  reconnectAttempts = Math.max(0, reconnectAttempts - 1);
  connectWS();
}

export function initChatSocketAutoResume() {
  window.addEventListener('online', resumeIfNeeded);
  window.addEventListener('focus', resumeIfNeeded);
  window.addEventListener('visibilitychange', () => { if (!document.hidden) resumeIfNeeded(); });
  window.addEventListener('pageshow', resumeIfNeeded);
}