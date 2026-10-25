(function () {
  "use strict";

  var picker = document.getElementById("saved-contact-picker");
  var addButton = document.getElementById("add-saved-contacts");
  if (!picker || !addButton) return;

  addButton.addEventListener("click", function () {
    var target = document.getElementById(addButton.getAttribute("data-target"));
    if (!target) return;

    var addresses = target.value.split(/[,;\n]+/).map(function (item) {
      return item.trim().toLowerCase();
    }).filter(Boolean);
    var known = {};
    addresses.forEach(function (address) { known[address] = true; });

    Array.prototype.forEach.call(picker.selectedOptions, function (option) {
      var address = option.value.trim();
      if (address && !known[address.toLowerCase()]) {
        addresses.push(address);
        known[address.toLowerCase()] = true;
      }
    });

    target.value = addresses.join(", ");
    target.dispatchEvent(new Event("input", { bubbles: true }));
  });
})();
