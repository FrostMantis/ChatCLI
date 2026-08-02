/*
 * Loaded by src/preload/preload.js and re-exposed as `window.api` — it runs in
 * the preload's Node scope, not in the page, despite living under src/renderer.
 *
 * Token handling deliberately lives outside this file. The renderer holds the
 * access token and puts it in each request body as `session_token`; refreshing
 * goes through `window.auth.refresh`, which is backed by the OS keychain in the
 * main process.
 */

const fetch = require('node-fetch');
const { BASE_URL } = require('../../preload/config.js');

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };

  const res = await fetch(`${BASE_URL}${path}`, { method: 'POST', ...options, headers });

  // Parse JSON payload
  let payload;
  try {
    payload = await res.json();
  } catch {
    payload = {};
  }

  // Handle errors
  if (!res.ok) {
    const errMsg = payload.message || payload.error || res.statusText;
    throw new Error(errMsg);
  }

  // Normalize response shape:
  // - Envelope: { status, message, response }
  // - Bare: { message } or custom
  if (payload.hasOwnProperty('response')) {
    return payload.response;
  }
  if (payload.hasOwnProperty('message') && Object.keys(payload).length === 1) {
    return payload.message;
  }
  return payload;
}

/* Convenience wrappers */
const verifyConnection = (body)              => request('/verify-connection', { body: JSON.stringify(body) });
const login            = ({ username, password })   => request('/user/login',    { body: JSON.stringify({ username, password }) });
const register         = ({ username, email, password, invite_code }) => request('/user/register', { body: JSON.stringify({ username, email, password, invite_code }) });
const verifyEmail      = ({ username, email_token }) =>
  request('/user/verify-email', { body: JSON.stringify({ username, email_token }) });
const fetchChats       = ()          => request('/chat/fetch-chats',  {});
const fetchMessages    = (chatID, limit=100, order='ASC') => request('/chat/messages', { body: JSON.stringify({ chatID, limit, order }) });
const createChat       = (receiver)          => request('/chat/create-chat',  { body: JSON.stringify({ receiver }) });

module.exports = {
  request,
  verifyConnection,
  login,
  register,
  verifyEmail,
  fetchChats,
  fetchMessages,
  createChat,
};