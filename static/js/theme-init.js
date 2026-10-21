/* Applies a saved theme choice before the page paints, so it does not flash. */
(function () {
  try {
    var saved = localStorage.getItem("mf-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  } catch (e) {
    /* Storage can be blocked. The page then follows the system theme. */
  }
})();
