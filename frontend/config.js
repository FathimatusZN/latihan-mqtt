/**
 * FILE    : frontend/config.js
 * FUNGSI  : Konfigurasi frontend — ganti API_BASE sesuai environment
 */

window.APP_CONFIG = {
  // Lokal development  : "http://localhost:8000"
  // Docker / server    : "http://<IP_SERVER>:8000"
  // Nginx proxy (/api) : "/api"
  API_BASE: "http://localhost:8000",
};
