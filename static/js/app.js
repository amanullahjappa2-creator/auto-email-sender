
/* MailFlow Studio - lightweight interface helpers.
   No application data is sent anywhere by this script. */
(function () {
  "use strict";

  var root = document.documentElement;

  // ---------- Toast notifications ----------
  var toastBox = document.getElementById("toasts");

  function toast(message) {
    if (!toastBox) return;

    while (toastBox.children.length >= 3) {
      toastBox.removeChild(toastBox.firstChild);
    }

    var element = document.createElement("div");
    element.className = "toast";
    element.textContent = message;
    toastBox.appendChild(element);

    window.setTimeout(function () {
      if (element.parentNode) {
        element.parentNode.removeChild(element);
      }
    }, 4000);
  }

  document.addEventListener("click", function (event) {
    var target = event.target;

    if (!target || typeof target.closest !== "function") return;

    var trigger = target.closest("[data-soon]");
    if (!trigger) return;

    event.preventDefault();
    toast(trigger.getAttribute("data-soon"));
  });

  // ---------- Light and dark theme ----------
  var themeButton = document.getElementById("theme-toggle");

  function currentTheme() {
    var theme = root.getAttribute("data-theme");

    if (theme === "light" || theme === "dark") {
      return theme;
    }

    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function syncThemeButton() {
    if (!themeButton) return;

    themeButton.setAttribute(
      "aria-pressed",
      String(currentTheme() === "dark")
    );
  }

  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var nextTheme = currentTheme() === "dark" ? "light" : "dark";

      root.setAttribute("data-theme", nextTheme);

      try {
        localStorage.setItem("mf-theme", nextTheme);
      } catch (error) {
        // The selected theme still applies for this visit.
      }

      syncThemeButton();
    });

    syncThemeButton();
  }

  // ---------- Search keyboard shortcut: Ctrl+K / Cmd+K ----------
  var search = document.getElementById("search");
  var hint = document.getElementById("search-hint");

  if (hint && /Mac|iPhone|iPad/.test(navigator.platform)) {
    hint.textContent = "⌘ K";
  }

  if (search) {
    document.addEventListener("keydown", function (event) {
      if (
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === "k"
      ) {
        event.preventDefault();
        search.focus();
        search.select();
      }
    });

    search.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        toast(
          "Search will work once there are emails and contacts to look through."
        );
      }
    });
  }
})();
