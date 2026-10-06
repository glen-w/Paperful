(function () {
  function updateToolbarLabels() {
    var form = document.getElementById("wanted-form");
    if (!form) return;
    var boxes = form.querySelectorAll(".row-select:checked:not(:disabled)");
    var any = boxes.length > 0;
    ["preview-btn", "grab-btn"].forEach(function (id) {
      var btn = document.getElementById(id);
      if (!btn) return;
      var all = btn.getAttribute("data-label-all");
      var sel = btn.getAttribute("data-label-sel");
      btn.textContent = any ? sel : all;
    });
  }
  document.querySelectorAll(".row-select").forEach(function (el) {
    el.addEventListener("change", updateToolbarLabels);
  });
  updateToolbarLabels();

  function pollRun(id, btn) {
    if (!id) return;
    var key = "pf-poll-" + id;
    if (sessionStorage.getItem(key)) return;
    if (btn) btn.classList.add("spinning");
    var iv = null;
    function tick() {
      fetch("/v1/runs/" + id)
        .then(function (r) { return r.json(); })
        .then(function (body) {
          var st = body.status;
          if (st === "done" || st === "failed") {
            if (iv) clearInterval(iv);
            sessionStorage.setItem(key, "1");
            if (btn) btn.classList.remove("spinning");
            location.reload();
          }
        })
        .catch(function () {});
    }
    tick();
    iv = setInterval(tick, 2000);
  }

  document.querySelectorAll("[data-run-id]").forEach(function (row) {
    var id = row.getAttribute("data-run-id");
    var st = row.querySelector(".cmd-status");
    if (st && (st.textContent === "queued" || st.textContent === "running")) {
      pollRun(id, null);
    }
  });

  var lastRun = document.body.getAttribute("data-poll-run");
  if (!lastRun) {
    var params = new URLSearchParams(window.location.search);
    lastRun = params.get("run") || params.get("poll") || "";
  }
  if (lastRun) {
    pollRun(lastRun, document.getElementById("preview-btn") || document.getElementById("grab-btn"));
  }
})();
