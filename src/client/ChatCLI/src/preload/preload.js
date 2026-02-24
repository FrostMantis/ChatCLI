const { contextBridge, ipcRenderer } = require('electron');
const api = require('../renderer/scripts/api.js');
const { WS_URL, BASE_URL, CALL_URL } = require('./config.js');
const WebSocket = require('ws');

/* -------- Expose REST API wrapper -------- */
contextBridge.exposeInMainWorld('api', {
  request:          api.request,
  verifyConnection: api.verifyConnection,
  login:            api.login,
  register:         api.register,
  verifyEmail:      api.verifyEmail,
  fetchChats:       api.fetchChats,
  fetchMessages:    api.fetchMessages,
  createChat:       api.createChat,
  refreshToken:     api.refreshToken,
  initializeTokens:   api.initializeTokens,
  WS_URL,
  BASE_URL,
  CALL_URL,
});

/* -------- Expose secureStore via keytar -------- */
contextBridge.exposeInMainWorld('auth', {
  storeRefresh: (accountId, token) => ipcRenderer.invoke('auth:storeRefresh', { accountId, refreshToken: token }),
  refresh: (accountId) => ipcRenderer.invoke('auth:refresh', { accountId }),
  clear: (accountId) => ipcRenderer.invoke('auth:clear', { accountId }),
})

contextBridge.exposeInMainWorld('chatAPI', {
  connect: (token) => {
    const ws = new WebSocket(WS_URL);
    ws.on('open', () => ws.send(JSON.stringify({ type: 'auth', token })));
    ws.on('message', (data) => {
      window.dispatchEvent(new CustomEvent('ws-message', {
        detail: JSON.parse(data)
      }));
    });
    return ws;
  }
});

contextBridge.exposeInMainWorld('secureStore', {
  set:    (account, token) => ipcRenderer.invoke('secureStore:set', account, token),
  get:    (account)        => ipcRenderer.invoke('secureStore:get', account),
  delete: (account)        => ipcRenderer.invoke('secureStore:delete', account),
});