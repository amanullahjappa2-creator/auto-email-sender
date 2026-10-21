/* MailFlow Studio - dashboard.js
   Keeps the date and time at the top of the dashboard ticking.
   It uses the time zone the server chose (data-tz), not the browser's. */
(function () {
  "use strict";

  var clock = document.getElementById("live-clock");
  var dateEl = document.getElementById("today-date");
  if (!clock || !window.Intl) return;

  var zone = clock.getAttribute("data-tz") || undefined;

  function tick() {
    var now = new Date();
    try {
      clock.textContent = new Intl.DateTimeFormat("en-US", {
        hour: "numeric", minute: "2-digit", timeZone: zone
      }).format(now);

      if (dateEl) {
        var p = {};
        new Intl.DateTimeFormat("en-GB", {
          weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: zone
        }).formatToParts(now).forEach(function (part) { p[part.type] = part.value; });
        dateEl.textContent = p.weekday + ", " + p.day + " " + p.month + " " + p.year;
      }
    } catch (error) {
      /* Unknown zone name: leave the server-written text as it is. */
    }
  }

  tick();
  window.setInterval(tick, 15000);
})();
