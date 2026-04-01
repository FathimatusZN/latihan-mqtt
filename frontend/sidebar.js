/**
 * FILE    : frontend/sidebar.js
 * FUNGSI  : Shared sidebar collapse/expand logic
 *           Include AFTER sidebar markup in every page
 */

(function () {
  const STORAGE_KEY = "sidebar_collapsed";
  const sidebar = document.getElementById("appSidebar");
  const toggleBtn = document.getElementById("sidebarToggle");

  if (!sidebar || !toggleBtn) return;

  // Restore state from localStorage
  const isCollapsed = localStorage.getItem(STORAGE_KEY) === "true";
  if (isCollapsed) sidebar.classList.add("collapsed");

  toggleBtn.addEventListener("click", () => {
    const nowCollapsed = sidebar.classList.toggle("collapsed");
    localStorage.setItem(STORAGE_KEY, nowCollapsed);
  });
})();
