const fetch = require('node-fetch');
const { BASE_URL } = require('../../preload/config.js');

let sessionToken      = null;
let refreshTokenValue = null;

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };

  // Only add Authorization header for non-login/register/verifyEmail
  if (
    sessionToken &&
    !['/user/login', '/user/register', '/user/verify-email'].includes(path)
  ) {
    headers['Authorization'] = `Bearer ${sessionToken}`;
  }

  // Parse body and inject session_token if required by docs
  let bodyObj = {};
  if (options.body) {
    try { bodyObj = JSON.parse(options.body); } catch { bodyObj = {}; }
  }

  // Inject session_token for chat endpoints (except login/register/verify)
  if (
    sessionToken &&
    (
      path.startsWith('/chat/') ||
      path === '/chat/fetch-chats' ||
      path === '/chat/create-chat' ||
      path === '/chat/messages'
    )
  ) {
    bodyObj.session_token = sessionToken;
    options.body = JSON.stringify(bodyObj);
  }

  const res = await fetch(`${BASE_URL}${path}`, { method: 'POST', ...options, headers });

  // Handle expired session
  if (res.status === 401 && refreshTokenValue) {
    const refreshed = await refreshToken();
    if (refreshed) {
      return request(path, options);
    } else {
      throw new Error('Session expired');
    }
  }

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

async function refreshToken() {
  if (!refreshTokenValue) return false;
  const res = await fetch(`${BASE_URL}/user/refresh-token`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ refresh_token: refreshTokenValue }),
  });

  if (!res.ok) return false;

  const data = await res.json();
  sessionToken = data.access_token;
  refreshTokenValue = data.refresh_token;
  return data;
}

// Add token initialization & getters
async function initializeTokens() {
  const refreshTok = await secureStore.get('refresh_token');
  if (refreshTok) {
    refreshTokenValue = refreshTok;
    return true;
  }
  return false;
}

function setRefreshToken(token) {
  refreshTokenValue = token;
}
function setSessionToken(token) {
  sessionToken = token;
}
function getSessionToken() {
  return sessionToken;
}

module.exports = {
  request,
  verifyConnection,
  login,
  register,
  verifyEmail,
  fetchChats,
  fetchMessages,
  createChat,
  refreshToken,
  setRefreshToken,
  setSessionToken,
  getSessionToken,
  initializeTokens,
};