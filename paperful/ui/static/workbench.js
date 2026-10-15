(function () {
  function loadDrawerSummary(dlg) {
    if (!dlg) return;
    dlg.querySelectorAll("iframe.summary-frame[data-src]").forEach(function (frame) {
      if (!frame.getAttribute("src")) {
        frame.setAttribute("src", frame.getAttribute("data-src"));
      }
    });
  }

  window.openDrawer = function (id) {
    var dlg = document.getElementById(id);
    if (!dlg) return;
    loadDrawerSummary(dlg);
    if (dlg.showModal) dlg.showModal();
  };

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
          if (!body || body.ok === false || !body.status) {
            if (iv) clearInterval(iv);
            sessionStorage.setItem(key, "1");
            if (btn) btn.classList.remove("spinning");
            return;
          }
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

  function placeHelpBubble(tip) {
    var bubble = tip.querySelector(".help-tip-bubble");
    if (!bubble) return;
    bubble.classList.remove("help-tip-bubble--left", "help-tip-bubble--right", "help-tip-bubble--below");
    var rect = bubble.getBoundingClientRect();
    var hPad = 8;
    var vPad = 8;
    var chrome = document.querySelector("header.wb-chrome");
    var nav = document.querySelector("nav.wb-nav");
    if (chrome) vPad = Math.max(vPad, chrome.getBoundingClientRect().bottom + 8);
    if (nav) vPad = Math.max(vPad, nav.getBoundingClientRect().bottom + 8);
    if (rect.top < vPad && !tip.closest("header.wb-chrome")) {
      bubble.classList.add("help-tip-bubble--below");
      rect = bubble.getBoundingClientRect();
    }
    if (rect.right > window.innerWidth - hPad) {
      bubble.classList.add("help-tip-bubble--left");
    } else if (rect.left < hPad) {
      bubble.classList.add("help-tip-bubble--right");
    }
  }
  document.querySelectorAll(".help-tip").forEach(function (tip) {
    tip.addEventListener("mouseenter", function () { placeHelpBubble(tip); });
    tip.addEventListener("focus", function () { placeHelpBubble(tip); });
  });

  var lastRun = document.body.getAttribute("data-poll-run");
  if (!lastRun) {
    var params = new URLSearchParams(window.location.search);
    lastRun = params.get("run") || params.get("poll") || "";
  }
  document.querySelectorAll("[data-run-id]").forEach(function (row) {
    var id = row.getAttribute("data-run-id");
    if (id && id === lastRun) return;
    var st = row.querySelector(".cmd-status");
    if (st && (st.textContent === "queued" || st.textContent === "running")) {
      pollRun(id, null);
    }
  });
  if (lastRun) {
    pollRun(
      lastRun,
      document.querySelector("[data-poll-button]")
        || document.getElementById("preview-btn")
        || document.getElementById("grab-btn")
    );
  }
})();
