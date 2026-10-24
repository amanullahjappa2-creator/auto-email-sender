/* MailFlow Studio - Compose page helpers.
   The server does all the real checking (file types, sizes, addresses).
   This file only makes the page easier to use: counters, the "preview is
   out of date" warning, and keeping Confirm & send off until it is safe
   to press. */
(function () {
  "use strict";

  var form = document.getElementById("compose-form");
  if (!form) return;

  var fields = {
    recipient: document.getElementById("recipient"),
    subject: document.getElementById("subject"),
    body: document.getElementById("body")
  };
  var confirmBox = document.getElementById("confirmed");
  var sendButton = document.getElementById("send-btn");
  var hint = document.getElementById("send-hint");
  var staleNote = document.getElementById("stale-note");
  var stateBadge = document.getElementById("preview-state");
  var previewPanel = document.getElementById("preview-panel");
  var errorSummary = document.getElementById("error-summary");
  var attachInput = document.getElementById("attachments");
  var addressFile = document.getElementById("recipient_file");
  var attachCount = document.getElementById("attach-count");
  var toCount = document.getElementById("to-count");
  var maxFiles = parseInt(form.getAttribute("data-max-files"), 10) || 5;

  var previewed = form.getAttribute("data-previewed") === "true";

  function clean(value) {
    return value.replace(/\r\n/g, "\n").trim();
  }

  /* What the person last previewed. Any change after that makes it stale. */
  var snapshot = {
    recipient: clean(fields.recipient.value),
    subject: clean(fields.subject.value),
    body: clean(fields.body.value)
  };

  /* New files, an address file, or a ticked "Remove" only take effect when
     the page is previewed again, so they also make the preview out of date. */
  function extrasPending() {
    if (attachInput && attachInput.files && attachInput.files.length) return true;
    if (addressFile && addressFile.files && addressFile.files.length) return true;
    return form.querySelectorAll('input[name="remove_attachment"]:checked').length > 0;
  }

  function isStale() {
    return (
      clean(fields.recipient.value) !== snapshot.recipient ||
      clean(fields.subject.value) !== snapshot.subject ||
      clean(fields.body.value) !== snapshot.body ||
      extrasPending()
    );
  }

  var HINTS = {
    none: "Confirm & send turns on after you preview the email and tick the box. It sends a separate email to each recipient from your Gmail account.",
    stale: "Preview the email again to include your latest changes, files or addresses.",
    unticked: "Tick the box to turn on Confirm & send.",
    ready: "Ready. Confirm & send will email each recipient from your Gmail account."
  };

  function refresh() {
    var stale = previewed && isStale();
    var ready = previewed && !stale && confirmBox.checked;

    sendButton.disabled = !ready;

    if (staleNote) staleNote.hidden = !stale;
    if (previewPanel) previewPanel.classList.toggle("is-stale", stale);
    if (stateBadge) {
      stateBadge.classList.toggle("is-stale", stale);
      stateBadge.textContent = stale ? "Out of date" : "Up to date";
    }

    var key = !previewed ? "none" : stale ? "stale" : !confirmBox.checked ? "unticked" : "ready";
    if (hint && hint.textContent.trim() !== HINTS[key]) hint.textContent = HINTS[key];
  }

  /* ---------- Character counters ---------- */
  function bindCounter(field, counterId) {
    var counter = document.getElementById(counterId);
    if (!counter) return;
    var max = counter.getAttribute("data-max");
    function update() {
      counter.textContent = field.value.length + "/" + max;
    }
    field.addEventListener("input", update);
    update();
  }

  bindCounter(fields.subject, "subject-count");
  bindCounter(fields.body, "body-count");

  /* ---------- Recipient count ---------- */
  function updateToCount() {
    if (!toCount) return;
    var max = parseInt(toCount.getAttribute("data-max"), 10) || 120;
    var seen = {};
    var n = 0;
    fields.recipient.value.split(/[,;\n]+/).forEach(function (item) {
      var a = item.trim().toLowerCase();
      if (a && !seen[a]) { seen[a] = true; n += 1; }
    });
    toCount.textContent = n ? n + (n === 1 ? " address" : " addresses") + " (max " + max + ")" : "";
    toCount.classList.toggle("is-over", n > max);
  }

  /* ---------- Chosen files ---------- */
  function sizeText(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return Math.round(bytes / 1024) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  function updateAttachCount() {
    if (!attachCount || !attachInput) return;
    var files = attachInput.files || [];
    if (!files.length) { attachCount.textContent = ""; return; }
    var total = 0;
    for (var i = 0; i < files.length; i += 1) total += files[i].size;
    attachCount.textContent = files.length + (files.length === 1 ? " file chosen" : " files chosen") +
      " (" + sizeText(total) + ")" + (files.length > maxFiles ? " - too many" : "");
  }

  /* ---------- Wire up ---------- */
  Object.keys(fields).forEach(function (name) {
    fields[name].addEventListener("input", refresh);
  });
  fields.recipient.addEventListener("input", updateToCount);
  if (attachInput) attachInput.addEventListener("change", function () { updateAttachCount(); refresh(); });
  if (addressFile) addressFile.addEventListener("change", refresh);
  form.addEventListener("change", function (event) {
    if (event.target && event.target.name === "remove_attachment") refresh();
  });
  confirmBox.addEventListener("change", refresh);
  updateToCount();
  updateAttachCount();
  refresh();

  /* ---------- Stop accidental double sending ----------
     One click on Confirm & send is enough. After it, both buttons are locked
     until the server answers. */
  var sendLabel = document.getElementById("send-label");
  var previewButton = form.querySelector('button[value="preview"]');
  var originalLabel = sendLabel ? sendLabel.textContent : "";

  form.addEventListener("submit", function (event) {
    var submitter = event.submitter;
    if (!submitter || submitter.value !== "send") return;

    if (form.getAttribute("data-sending") === "true") {
      event.preventDefault(); // a second click while the first is in progress
      return;
    }
    form.setAttribute("data-sending", "true");

    // Lock the buttons on the next tick. A button disabled inside this handler
    // would be left out of the form data, and the server would not see "send".
    window.setTimeout(function () {
      sendButton.disabled = true;
      sendButton.setAttribute("aria-busy", "true");
      if (previewButton) previewButton.disabled = true;
      if (sendLabel) sendLabel.textContent = "Sending…";
      if (hint) hint.textContent = "Sending. Please wait and do not press the button again.";
    }, 0);
  });

  /* Coming back with the browser's Back button should not leave it locked. */
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    form.removeAttribute("data-sending");
    sendButton.removeAttribute("aria-busy");
    if (previewButton) previewButton.disabled = false;
    if (sendLabel) sendLabel.textContent = originalLabel;
    updateAttachCount();
    refresh();
  });

  /* Move keyboard and screen reader focus to the error list when the page
     comes back with problems. */
  if (errorSummary) errorSummary.focus();
})();
