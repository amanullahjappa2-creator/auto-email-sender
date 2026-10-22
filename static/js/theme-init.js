
/* Apply the saved theme before the page renders to prevent flashing. */
(function () {
  "use strict";

  try {
    var savedTheme = localStorage.getItem("mf-theme");

    if (savedTheme === "light" || savedTheme === "dark") {
      document.documentElement.setAttribute("data-theme", savedTheme);
    }
  } catch (error) {
    // If storage is unavailable, fall back to the system theme.
  }
})();
