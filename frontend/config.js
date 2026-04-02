/**
 * FILE    : frontend/config.js
 * FUNGSI  : Konfigurasi frontend — ganti API_BASE di sini sesuai environment (lokal / server / Docker).
 *
 * CARA PAKAI:
 *   - Semua halaman sudah include <script src="config.js">
 *   - Konstanta window.APP_CONFIG.API_BASE tersedia global
 */

window.APP_CONFIG = {
  // Ganti nilai ini sesuai environment:
  //   Lokal development  : "http://localhost:8000"
  //   Docker             : "http://<IP_SERVER>:8000"
  //   Nginx proxy (/api) : "/api"
  API_BASE: "http://localhost:8000",
};
