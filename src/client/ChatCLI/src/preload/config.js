const API_HOST = '172.27.27.29';
const WS_HOST = '172.27.27.29';
const API_PORT = 5123;
const WS_PORT = 8765;

module.exports = {
  BASE_URL: `http://${API_HOST}:${API_PORT}`,
  WS_URL: `ws://${WS_HOST}:${WS_PORT}/ws`,
  CALL_URL: `ws://${WS_HOST}:${WS_PORT}/call/`,
};