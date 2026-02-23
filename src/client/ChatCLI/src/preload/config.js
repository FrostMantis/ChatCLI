const API_HOST = 'chat.puam.be';
const WS_HOST = 'ws.chat.puam.be';
const API_PORT = 443;
const WS_PORT = 443;

module.exports = {
  BASE_URL: `https://${API_HOST}:${API_PORT}`,
  WS_URL: `wss://${WS_HOST}:${WS_PORT}/ws`,
  CALL_URL: `wss://${WS_HOST}:${WS_PORT}/call/`,
};