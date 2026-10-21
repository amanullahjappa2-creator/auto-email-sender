/* MailFlow Studio - account pages (login, register, settings).
   Show/hide password buttons and the live password checklist.
   The server still does all real validation. */
(function () {
  "use strict";

  /* ---------- Show / hide password ----------
     The buttons start hidden in the HTML and appear only when this script
     runs, so nobody gets a button that does nothing. */
  var toggles = document.querySelectorAll("[data-toggle-password]");

  Array.prototype.forEach.call(toggles, function (button) {
    var input = document.getElementById(button.getAttribute("aria-controls"));
    if (!input) return;

    var hiddenLabel = button.getAttribute("aria-label"); // e.g. "Show password"
    var shownLabel = hiddenLabel.replace(/^Show/, "Hide");

    button.hidden = false;
    button.addEventListener("click", function () {
      var reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      button.setAttribute("data-visible", String(reveal));
      button.setAttribute("aria-label", reveal ? shownLabel : hiddenLabel);
    });
  });

  /* ---------- Register: live password checklist ---------- */
  var password = document.getElementById("password");
  var confirm = document.getElementById("confirm_password");
  var rules = document.getElementById("password-rules");

  if (password && confirm && rules) {
    var MIN_LENGTH = 12; // same number as the minlength on the inputs

    var lengthRule = rules.querySelector('[data-rule="length"]');
    var matchRule = rules.querySelector('[data-rule="match"]');

    function setRule(item, met) {
      if (!item) return;
      item.classList.toggle("is-met", met);
      var state = item.querySelector(".rule-state");
      if (state) state.textContent = met ? " (met)" : " (not met yet)";
    }

    function update() {
      setRule(lengthRule, password.value.length >= MIN_LENGTH);
      setRule(matchRule, confirm.value.length > 0 && confirm.value === password.value);
    }

    password.addEventListener("input", update);
    confirm.addEventListener("input", update);
    update();
  }
})();
