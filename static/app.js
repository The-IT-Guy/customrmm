(function () {
  const sidebar = document.getElementById("sidebar");
  const mobileToggle = document.getElementById("mobileToggle");
  const sidebarToggle = document.getElementById("sidebarToggle");

  function toggleSidebar() {
    if (!sidebar) return;
    sidebar.classList.toggle("open");
  }

  if (mobileToggle) mobileToggle.addEventListener("click", toggleSidebar);
  if (sidebarToggle) sidebarToggle.addEventListener("click", toggleSidebar);

  // Close on outside click (mobile)
  document.addEventListener("click", (e) => {
    if (!sidebar || !sidebar.classList.contains("open")) return;
    const target = e.target;
    const clickedInside = sidebar.contains(target) || (mobileToggle && mobileToggle.contains(target));
    if (!clickedInside) sidebar.classList.remove("open");
  });
})();