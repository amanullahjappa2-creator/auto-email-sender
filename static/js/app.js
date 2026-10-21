/* MailFlow Studio - small interface helpers. No data leaves the page here. */
(function () {
  "use strict";

  var root = document.documentElement;

  /* ---------- Toasts (used for features that are not built yet) ---------- */
  var toastBox = document.getElementById("toasts");

  function toast(message) {
    if (!toastBox) return;
    while (toastBox.children.length >= 3) {
      toastBox.removeChild(toastBox.firstChild);
    }
    var el = document.createElement("div");
    el.className = "toast";
    el.textContent = message; // textContent, never innerHTML
    toastBox.appendChild(el);
    window.setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 4000);
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-soon]");
    if (!trigger) return;
    event.preventDefault();
    toast(trigger.getAttribute("data-soon"));
  });

  /* ---------- Theme toggle ---------- */
  var themeButton = document.getElementById("theme-toggle");

  function currentTheme() {
    var set = root.getAttribute("data-theme");
    if (set === "light" || set === "dark") return set;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function syncThemeButton() {
    if (themeButton) {
      themeButton.setAttribute("aria-pressed", String(currentTheme() === "dark"));
    }
  }

  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        localStorage.setItem("mf-theme", next);
      } catch (e) {
        /* Not saved, but the choice still applies for this visit. */
      }
      syncThemeButton();
    });
    syncThemeButton();
  }

  /* ---------- Search box: Ctrl+K (or Cmd+K on Mac) ---------- */
  var search = document.getElementById("search");
  var hint = document.getElementById("search-hint");

  if (hint && /Mac|iPhone|iPad/.test(navigator.platform)) {
    hint.textContent = "⌘ K";
  }

  if (search) {
    document.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        search.focus();
        search.select();
      }
    });
    search.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        toast("Search will work once there are emails and contacts to look through.");
      }
    });
  }
})();
