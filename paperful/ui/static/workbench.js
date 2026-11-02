(function () {
  // No inline handlers anywhere in the templates (CSP script-src 'self').
  // Behaviour hangs off data-* attributes and is wired here by delegation.

  function loadDrawerSummary(dlg) {
    if (!dlg) return;
    dlg.querySelectorAll("iframe.summary-frame[data-src]").forEach(function (frame) {
      if (!frame.getAttribute("src")) {
        frame.setAttribute("src", frame.getAttribute("data-src"));
      }
    });
  }

  // Row details are server-rendered into inert <template> elements; one
  // shared <dialog id="row-drawer"> shows whichever row was asked for.
  window.openDrawer = function (id) {
    var target = document.getElementById(id);
    if (!target) return;
    var dlg = target;
    if (target.tagName === "TEMPLATE") {
      dlg = document.getElementById("row-drawer");
      if (!dlg) return;
      var body = dlg.querySelector(".drawer-body");
      body.innerHTML = "";
      body.appendChild(target.content.cloneNode(true));
      var title = dlg.querySelector("#row-drawer-title");
      if (title) title.textContent = target.getAttribute("data-drawer-title") || "Details";
    }
    loadDrawerSummary(dlg);
    if (dlg.showModal && !dlg.open) dlg.showModal();
  };

  // data-drawer="dialog-id" on a button opens that <dialog>.
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-drawer]");
    if (!btn) return;
    ev.preventDefault();
    window.openDrawer(btn.getAttribute("data-drawer"));
  });

  // data-autosubmit on a select/checkbox submits its form on change.
  document.addEventListener("change", function (ev) {
    var el = ev.target.closest("[data-autosubmit]");
    if (el && el.form) el.form.submit();
  });

  // data-confirm="message" on a form asks before submitting.
  document.addEventListener("submit", function (ev) {
    var form = ev.target.closest("form[data-confirm]");
    if (!form) return;
    if (!window.confirm(form.getAttribute("data-confirm") || "Continue?")) {
      ev.preventDefault();
    }
  });

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
    var attachBtn = document.getElementById("attach-btn");
    if (attachBtn) {
      var attachCount = parseInt(attachBtn.getAttribute("data-attach-count") || "0", 10);
      var attachableAny = document.querySelectorAll(
        "input.row-select:checked:not(:disabled)[data-attachable='1']"
      ).length > 0;
      // Enable only when pending attachables exist, or the selection includes
      // an attachable row (mismatch/short ticks alone stay disabled).
      attachBtn.disabled = attachCount === 0 && !attachableAny;
    }
    var count = document.getElementById("wanted-selected-count");
    if (count) count.textContent = any ? boxes.length + " selected" : "";
  }
  document.querySelectorAll(".row-select").forEach(function (el) {
    el.addEventListener("change", updateToolbarLabels);
  });
  updateToolbarLabels();

  // Wanted: secondary forms (attach / recover / handoff / reachout) carry the
  // ticked row keys from the main table, plus the recover limit alias.
  (function () {
    var main = document.getElementById("wanted-form");
    if (!main) return;
    document.querySelectorAll("form.keys-form").forEach(function (form) {
      form.addEventListener("submit", function () {
        document.querySelectorAll(".row-select:checked").forEach(function (box) {
          var input = document.createElement("input");
          input.type = "hidden";
          input.name = "keys";
          input.value = box.value;
          form.appendChild(input);
        });
        var lim = form.querySelector("[name=recover_limit]");
        if (lim && lim.value) {
          var hidden = document.createElement("input");
          hidden.type = "hidden";
          hidden.name = "limit";
          hidden.value = lim.value;
          form.appendChild(hidden);
        }
      });
    });
  })();

  // Discover: the citation map stores a "seed search" prefill before
  // redirecting to the Topic tab.
  (function () {
    var query = document.getElementById("discoverQuery");
    if (!query) return;
    var raw = sessionStorage.getItem("paperfulDiscoverPrefill");
    if (!raw) return;
    sessionStorage.removeItem("paperfulDiscoverPrefill");
    try {
      var data = JSON.parse(raw);
      var kind = document.getElementById("discoverKind");
      var seeds = document.getElementById("discoverSeeds");
      if (data.title) query.value = data.title;
      if (data.doi && seeds && kind) {
        kind.value = "doi";
        seeds.value = data.doi;
      } else if (data.doi) {
        query.value = data.doi;
      }
    } catch (e) {}
  })();

  // ---- Run status (SSE with JSON fallback) -------------------------------

  var TERMINAL = { done: true, failed: true };
  var MAX_SSE_RETRIES = 3;
  var POLL_MS = 2000;
  var MAX_POLL_MS = 30 * 60 * 1000; // stop polling a row after 30 minutes
  var pollKey = function (id) { return "pf-poll-" + id; };

  function finishRun(id, btn) {
    sessionStorage.setItem(pollKey(id), "1");
    if (btn) btn.classList.remove("spinning");
    location.reload();
  }

  function applyStatusToRow(id, status) {
    document.querySelectorAll('[data-run-id="' + id + '"]').forEach(function (row) {
      var st = row.querySelector(".cmd-status");
      if (st) st.textContent = status;
      row.setAttribute("data-run-status", status);
    });
  }

  function pollRunJson(id, btn) {
    if (!id) return;
    var key = pollKey(id);
    if (sessionStorage.getItem(key)) return;
    if (btn) btn.classList.add("spinning");
    var iv = null;
    var started = Date.now();
    function stop() {
      if (iv) clearInterval(iv);
      sessionStorage.setItem(key, "1");
      if (btn) btn.classList.remove("spinning");
    }
    function tick() {
      if (Date.now() - started > MAX_POLL_MS) { stop(); return; }
      fetch("/v1/runs/" + id, { headers: { Accept: "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (body) {
          if (!body || body.ok === false || !body.status) { stop(); return; }
          var st = body.status;
          applyStatusToRow(id, st);
          if (TERMINAL[st]) {
            if (iv) clearInterval(iv);
            finishRun(id, btn);
          }
        })
        .catch(function () {});
    }
    tick();
    iv = setInterval(tick, POLL_MS);
  }

  function pollRun(id, btn) {
    if (!id) return;
    var key = pollKey(id);
    if (sessionStorage.getItem(key)) return;
    if (btn) btn.classList.add("spinning");
    if (typeof EventSource === "undefined") {
      pollRunJson(id, btn);
      return;
    }
    var finished = false;
    var retries = 0;
    var es = new EventSource("/v1/runs/" + id + "/events");
    es.addEventListener("status", function (ev) {
      try {
        var body = JSON.parse(ev.data);
        var st = body.status;
        applyStatusToRow(id, st);
        if (TERMINAL[st]) {
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
      retries += 1;
      if (retries >= MAX_SSE_RETRIES) {
        finished = true;
        es.close();
        pollRunJson(id, btn);
      }
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

  // Relative "3 min ago" labels for data-ts="<unix seconds>".
  function relTime(ts) {
    var d = Date.now() / 1000 - ts;
    if (d < 60) return "just now";
    if (d < 3600) return Math.round(d / 60) + " min ago";
    if (d < 86400) return Math.round(d / 3600) + " h ago";
    return Math.round(d / 86400) + " d ago";
  }
  document.querySelectorAll("[data-ts]").forEach(function (el) {
    var ts = parseFloat(el.getAttribute("data-ts"));
    if (ts) el.textContent = relTime(ts);
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
    if (!st) return;
    var status = st.textContent.trim();
    if (status !== "queued" && status !== "running") return;
    // Rows the server already knows are stale (restart reconciliation) or
    // that are older than the polling window are left alone.
    var created = parseFloat(row.getAttribute("data-created") || "0");
    if (created && Date.now() / 1000 - created > MAX_POLL_MS / 1000) return;
    pollRun(id, null);
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
