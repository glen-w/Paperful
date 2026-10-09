(function () {
  function updateToolbarLabels() {
    var form = document.getElementById("wanted-form");
    if (!form) return;
    // Row checkboxes live in the items table and point at the form via
    // the ``form`` attribute, so they are not descendants of #wanted-form.
    var boxes = document.querySelectorAll(
      "input.row-select:checked:not(:disabled)"
    );
    var any = boxes.length > 0;
    ["preview-btn", "grab-btn", "attach-btn"].forEach(function (id) {
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

  function finishRun(id, btn) {
    var key = "pf-poll-" + id;
    sessionStorage.setItem(key, "1");
    if (btn) btn.classList.remove("spinning");
    location.reload();
  }

  function applyStatusToRow(id, status) {
    var row = document.querySelector('[data-run-id="' + id + '"]');
    if (!row) return;
    var st = row.querySelector(".cmd-status");
    if (st) st.textContent = status;
  }

  function pollRunJson(id, btn) {
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
          applyStatusToRow(id, st);
          if (st === "done" || st === "failed") {
            if (iv) clearInterval(iv);
            finishRun(id, btn);
          }
        })
        .catch(function () {});
    }
    tick();
    iv = setInterval(tick, 2000);
  }

  function pollRun(id, btn) {
    if (!id) return;
    var key = "pf-poll-" + id;
    if (sessionStorage.getItem(key)) return;
    if (btn) btn.classList.add("spinning");
    if (typeof EventSource === "undefined") {
      pollRunJson(id, btn);
      return;
    }
    var finished = false;
    var es = new EventSource("/v1/runs/" + id + "/events");
    es.addEventListener("status", function (ev) {
      try {
        var body = JSON.parse(ev.data);
        var st = body.status;
        applyStatusToRow(id, st);
        if (st === "done" || st === "failed") {
          finished = true;
          es.close();
          finishRun(id, btn);
        }
      } catch (e) {
        finished = true;
        es.close();
        pollRunJson(id, btn);
      }
    });
    es.onerror = function () {
      if (finished) return;
      es.close();
      pollRunJson(id, btn);
    };
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
