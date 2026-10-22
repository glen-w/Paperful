var pageState = {
  detected: null,
  plan: null,
  rows: [],
  hello: null,
  lastSave: null,
  reviews: [],
  tags: [],
  knownTags: [],
  pageTagHints: [],
  remoteTagHints: [],
  suggestIndex: -1,
  suggestTimer: null,
  suggestSeq: 0,
};

function byId(id) {
  return document.getElementById(id);
}

function say(text, kind) {
  var node = byId("status");
  node.textContent = text || "";
  node.className = "status" + (kind ? " " + kind : "");
}

function send(message) {
  return browser.runtime.sendMessage(message);
}

function showPage(on) {
  byId("page-view").hidden = !on;
  byId("tabs-view").hidden = on;
  byId("show-page").classList.toggle("active", on);
  byId("show-tabs").classList.toggle("active", !on);
}

function setChip(node, text, kind) {
  node.textContent = text || "";
  node.hidden = !text;
  node.className = "chip" + (kind ? " " + kind : "");
}

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function actionLine(plan) {
  if (!plan) return "";
  if (plan.action === "update" && plan.has_pdf) return "Have PDF";
  if (plan.action === "update") return "Update";
  if (plan.action === "create") return "Create";
  if (plan.action === "ambiguous") return "Ambiguous";
  if (plan.action === "blocked") return "Blocked";
  return plan.action || "";
}

function fillCollections(hello, selected) {
  var input = byId("collection");
  var list = byId("collection-list");
  clearNode(list);
  var paths = ((hello && hello.collections) || []).slice();
  var current = selected || input.value || (hello && hello.collection) || "Capture";
  if (paths.indexOf(current) === -1) paths = [current].concat(paths);
  var i;
  for (i = 0; i < paths.length; i++) {
    var opt = document.createElement("option");
    opt.value = paths[i];
    list.appendChild(opt);
  }
  if (!input.value) input.value = current;
  pageState.knownTags = ((hello && hello.tags) || []).slice();
}

function tagKey(name) {
  return String(name || "").trim().toLowerCase();
}

function renderTagChips() {
  var box = byId("tag-chips");
  clearNode(box);
  var i;
  for (i = 0; i < pageState.tags.length; i++) {
    (function (name) {
      var chip = document.createElement("span");
      chip.className = "tag-chip";
      var label = document.createElement("span");
      label.textContent = name;
      var remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", "Remove " + name);
      remove.textContent = "×";
      remove.addEventListener("click", function () {
        pageState.tags = pageState.tags.filter(function (row) {
          return tagKey(row) !== tagKey(name);
        });
        renderTagChips();
        hideTagSuggest();
      });
      chip.appendChild(label);
      chip.appendChild(remove);
      box.appendChild(chip);
    })(pageState.tags[i]);
  }
}

function addTag(raw) {
  var name = String(raw || "").trim();
  if (!name) return false;
  if (name.length > 100) name = name.slice(0, 100);
  if (pageState.tags.length >= 20) return false;
  var key = tagKey(name);
  var i;
  for (i = 0; i < pageState.tags.length; i++) {
    if (tagKey(pageState.tags[i]) === key) return false;
  }
  pageState.tags.push(name);
  renderTagChips();
  byId("tag-input").value = "";
  hideTagSuggest();
  return true;
}

function hideTagSuggest() {
  var list = byId("tag-suggest");
  list.hidden = true;
  clearNode(list);
  pageState.suggestIndex = -1;
}

function tagIsChosen(name) {
  var key = tagKey(name);
  var i;
  for (i = 0; i < pageState.tags.length; i++) {
    if (tagKey(pageState.tags[i]) === key) return true;
  }
  return false;
}

function matchingTags(query) {
  var needle = tagKey(query);
  var out = [];
  var seen = {};
  var pools = [];
  if (needle) pools.push(pageState.remoteTagHints, pageState.knownTags, pageState.pageTagHints);
  else pools.push(pageState.pageTagHints, pageState.knownTags);
  var p;
  var i;
  for (p = 0; p < pools.length; p++) {
    var pool = pools[p] || [];
    for (i = 0; i < pool.length; i++) {
      var name = pool[i];
      var key = tagKey(name);
      if (!name || seen[key] || tagIsChosen(name)) continue;
      if (needle && key.indexOf(needle) === -1) continue;
      seen[key] = true;
      out.push(name);
      if (out.length >= 8) break;
    }
    if (out.length >= 8) break;
  }
  return out;
}

function queueTagSuggest(query) {
  var text = String(query || "");
  var doi = (pageState.detected && pageState.detected.doi) || "";
  if (pageState.suggestTimer) clearTimeout(pageState.suggestTimer);
  var seq = pageState.suggestSeq + 1;
  pageState.suggestSeq = seq;
  pageState.suggestTimer = setTimeout(function () {
    pageState.suggestTimer = null;
    send({ type: "tag-suggest", query: text, doi: doi }).then(function (payload) {
      if (seq !== pageState.suggestSeq) return;
      if (!payload || payload.ok === false) return;
      var rows = (payload && payload.tags) || [];
      if (text) pageState.remoteTagHints = rows;
      else pageState.pageTagHints = rows;
      renderTagSuggest();
    }, function () {});
  }, text ? 280 : 0);
}

function renderTagSuggest() {
  var input = byId("tag-input");
  var list = byId("tag-suggest");
  var rows = matchingTags(input.value);
  clearNode(list);
  if (!rows.length) {
    hideTagSuggest();
    return;
  }
  var i;
  for (i = 0; i < rows.length; i++) {
    (function (name, index) {
      var item = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = name;
      if (index === pageState.suggestIndex) btn.className = "active";
      btn.addEventListener("mousedown", function (ev) {
        ev.preventDefault();
        addTag(name);
        input.focus();
      });
      item.appendChild(btn);
      list.appendChild(item);
    })(rows[i], i);
  }
  list.hidden = false;
  if (pageState.suggestIndex >= rows.length) pageState.suggestIndex = rows.length - 1;
}

function commitTagInput() {
  var value = byId("tag-input").value;
  var rows = matchingTags(value);
  if (pageState.suggestIndex >= 0 && rows[pageState.suggestIndex]) {
    addTag(rows[pageState.suggestIndex]);
    return;
  }
  addTag(value);
}

function renderPage(payload) {
  var detected = (payload && payload.detected) || {};
  var plan = (payload && payload.plan) || {};
  pageState.detected = detected;
  pageState.plan = plan;
  pageState.hello = payload.hello || pageState.hello;
  pageState.lastSave = null;
  byId("saved-actions").hidden = true;
  byId("page-title").textContent = detected.title || "Untitled";
  setChip(byId("page-doi"), detected.doi || "no DOI", "");
  var bits = [];
  if (detected.year) bits.push(String(detected.year));
  if (detected.publication_title) bits.push(detected.publication_title);
  if (detected.authors && detected.authors.length) {
    bits.push(detected.authors.slice(0, 3).join(", "));
  }
  byId("page-meta").textContent = bits.join(" · ");
  byId("page-meta").hidden = !bits.length;
  var line = actionLine(plan);
  if (plan.reason) line += " (" + plan.reason + ")";
  setChip(byId("page-action"), line, line ? "action-" + (plan.action || "") : "");
  var maybe = plan.maybe || [];
  if (maybe.length) {
    byId("page-maybe").textContent =
      "Possible title match: " + maybe.map(function (row) { return row.key; }).join(", ");
  } else {
    byId("page-maybe").textContent = "";
  }
  var box = byId("candidates");
  clearNode(box);
  var candidates = plan.candidates || [];
  var i;
  for (i = 0; i < candidates.length; i++) {
    var label = document.createElement("label");
    var input = document.createElement("input");
    input.type = "radio";
    input.name = "confirm-key";
    input.value = String(candidates[i]);
    var span = document.createElement("span");
    span.textContent = String(candidates[i]);
    label.appendChild(input);
    label.appendChild(span);
    box.appendChild(label);
  }
  box.hidden = candidates.length === 0;
  byId("unread-label").hidden = plan.reason !== "zotero_unread";
  byId("allow-unread").checked = false;
  var canPdf = Boolean(detected.is_pdf || detected.pdf_url);
  byId("save-pdf").checked = canPdf;
  byId("pdf-label").hidden = !canPdf;
  byId("lanes-label").hidden = Boolean(plan.has_pdf);
  byId("search-lanes").checked = false;
  byId("save-page").disabled = plan.action === "blocked" && plan.reason === "refused_host";
  fillCollections(pageState.hello, pageState.hello && pageState.hello.collection);
  pageState.pageTagHints = [];
  pageState.remoteTagHints = [];
  queueTagSuggest("");
}

function selectedConfirm() {
  var chosen = document.querySelector("input[name='confirm-key']:checked");
  return chosen ? chosen.value : "";
}

function renderTabs(rows) {
  pageState.rows = rows || [];
  pageState.reviews = [];
  byId("tab-plans").hidden = true;
  clearNode(byId("tab-plans"));
  byId("save-tabs").hidden = true;
  byId("tabs-unread-label").hidden = true;
  var list = byId("tab-list");
  clearNode(list);
  var i;
  for (i = 0; i < pageState.rows.length; i++) {
    var row = pageState.rows[i];
    var label = document.createElement("label");
    var input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(row.checked);
    input.setAttribute("data-tab-id", String(row.tabId));
    var span = document.createElement("span");
    var prefix = row.sessionKey ? "walk · " : "";
    span.textContent = prefix + (row.host ? row.host + " — " : "") + (row.title || "");
    if (row.sessionKey) label.className = "from-walk";
    label.appendChild(input);
    label.appendChild(span);
    list.appendChild(label);
  }
  list.hidden = pageState.rows.length === 0;
}

function setChecks(mode) {
  var boxes = byId("tab-list").querySelectorAll("input");
  var i;
  for (i = 0; i < boxes.length; i++) {
    if (mode === "all") boxes[i].checked = true;
    else if (mode === "none") boxes[i].checked = false;
    else boxes[i].checked = Boolean(pageState.rows[i] && pageState.rows[i].checked);
  }
}

function selectedTabIds() {
  var boxes = byId("tab-list").querySelectorAll("input");
  var ids = [];
  var i;
  for (i = 0; i < boxes.length; i++) {
    if (boxes[i].checked) ids.push(Number(boxes[i].getAttribute("data-tab-id")));
  }
  return ids;
}

function rowForTab(tabId) {
  var i;
  for (i = 0; i < pageState.rows.length; i++) {
    if (Number(pageState.rows[i].tabId) === Number(tabId)) return pageState.rows[i];
  }
  return null;
}

function renderReviews(rows) {
  pageState.reviews = rows || [];
  var box = byId("tab-plans");
  box.hidden = false;
  clearNode(box);
  var unread = false;
  var i;
  for (i = 0; i < pageState.reviews.length; i++) {
    var row = pageState.reviews[i] || {};
    var plan = row.plan || {};
    var detected = row.detected || {};
    var wrap = document.createElement("div");
    wrap.className = "plan-row";
    wrap.setAttribute("data-tab-id", String(row.tabId));
    var chip = document.createElement("p");
    var act = actionLine(plan);
    if (plan.reason) act += " (" + plan.reason + ")";
    setChip(chip, act, act ? "action-" + (plan.action || "") : "");
    wrap.appendChild(chip);
    var line = document.createElement("p");
    line.className = "meta";
    line.textContent = detected.title || detected.url || "tab " + row.tabId;
    wrap.appendChild(line);
    if (plan.action === "ambiguous") {
      var candidates = plan.candidates || [];
      var c;
      for (c = 0; c < candidates.length; c++) {
        var label = document.createElement("label");
        var input = document.createElement("input");
        input.type = "radio";
        input.name = "confirm-" + row.tabId;
        input.value = String(candidates[c]);
        if (c === 0) input.checked = true;
        var span = document.createElement("span");
        span.textContent = String(candidates[c]);
        label.appendChild(input);
        label.appendChild(span);
        wrap.appendChild(label);
      }
    }
    if (plan.reason === "zotero_unread") unread = true;
    box.appendChild(wrap);
  }
  byId("tabs-unread-label").hidden = !unread;
  byId("save-tabs").hidden = pageState.reviews.length === 0;
}

function reviewConfirm(tabId) {
  var chosen = document.querySelector("input[name='confirm-" + tabId + "']:checked");
  return chosen ? chosen.value : "";
}

function showSaved(result) {
  pageState.lastSave = result || null;
  var canOpen = Boolean(result && result.ok && result.key);
  byId("saved-actions").hidden = !canOpen;
}

byId("show-page").addEventListener("click", function () {
  showPage(true);
});
byId("show-tabs").addEventListener("click", function () {
  showPage(false);
  say("Loading tabs…");
  send({ type: "list-tabs" }).then(function (payload) {
    if (payload && payload.hello) pageState.hello = payload.hello;
    renderTabs((payload && payload.rows) || []);
    say("");
  }, function (err) {
    say(String(err && err.message ? err.message : err));
  });
});
byId("tag-input").addEventListener("input", function () {
  pageState.suggestIndex = -1;
  queueTagSuggest(byId("tag-input").value);
  renderTagSuggest();
});
byId("tag-input").addEventListener("focus", function () {
  if (!pageState.pageTagHints.length && (pageState.detected && pageState.detected.doi)) {
    queueTagSuggest("");
  }
  renderTagSuggest();
});
byId("tag-input").addEventListener("keydown", function (ev) {
  var rows = matchingTags(byId("tag-input").value);
  if (ev.key === "ArrowDown" && rows.length) {
    ev.preventDefault();
    pageState.suggestIndex = Math.min(pageState.suggestIndex + 1, rows.length - 1);
    renderTagSuggest();
    return;
  }
  if (ev.key === "ArrowUp" && rows.length) {
    ev.preventDefault();
    pageState.suggestIndex = Math.max(pageState.suggestIndex - 1, 0);
    renderTagSuggest();
    return;
  }
  if (ev.key === "Enter" || ev.key === ",") {
    ev.preventDefault();
    commitTagInput();
    return;
  }
  if (ev.key === "Tab" && byId("tag-input").value.trim()) {
    ev.preventDefault();
    commitTagInput();
    return;
  }
  if (ev.key === "Escape") {
    hideTagSuggest();
    return;
  }
  if (ev.key === "Backspace" && !byId("tag-input").value && pageState.tags.length) {
    pageState.tags.pop();
    renderTagChips();
  }
});
byId("tag-input").addEventListener("blur", function () {
  window.setTimeout(hideTagSuggest, 120);
});
byId("select-walk").addEventListener("click", function () { setChecks("walk"); });
byId("select-all").addEventListener("click", function () { setChecks("all"); });
byId("select-none").addEventListener("click", function () { setChecks("none"); });
byId("save-page").addEventListener("click", function () {
  say("Saving…");
  byId("saved-actions").hidden = true;
  send({
    type: "save-active",
    savePdf: byId("save-pdf").checked,
    lanes: byId("search-lanes").checked,
    allowUnread: byId("allow-unread").checked,
    confirmKey: selectedConfirm(),
    collection: byId("collection").value,
    tags: pageState.tags.slice(),
    note: byId("note").value,
  }).then(function (result) {
    if (!result) {
      say("No result");
      return;
    }
    var line = result.action || (result.ok ? "saved" : "not saved");
    if (result.key) line += " " + result.key;
    if (result.pdf) line += " · " + result.pdf;
    if (result.snapshot && result.snapshot !== "none") line += " · snapshot " + result.snapshot;
    if (result.note === "saved") line += " · note";
    if (result.tags && result.tags.length) line += " · tags " + result.tags.length;
    if (result.reason) line += " (" + result.reason + ")";
    say(line);
    showSaved(result);
  }, function (err) {
    say(String(err && err.message ? err.message : err));
  });
});
byId("open-folder").addEventListener("click", function () {
  var key = pageState.lastSave && pageState.lastSave.key;
  if (!key) return;
  send({ type: "open-target", target: "item", key: key }).then(function (payload) {
    if (!payload || payload.ok === false) say((payload && payload.reason) || "Could not open folder");
  }, function (err) {
    say(String(err && err.message ? err.message : err));
  });
});
byId("open-wanted").addEventListener("click", function () {
  var saved = pageState.lastSave || {};
  send({
    type: "open-workbench",
    key: saved.key || "",
    doi: (pageState.detected && pageState.detected.doi) || "",
  }).then(function (payload) {
    if (!payload || payload.ok === false) say((payload && payload.reason) || "Workbench is not running");
  }, function (err) {
    say(String(err && err.message ? err.message : err));
  });
});
byId("review-tabs").addEventListener("click", function () {
  var ids = selectedTabIds();
  if (!ids.length) {
    say("Select at least one tab");
    return;
  }
  say("Reviewing " + ids.length + "…");
  send({ type: "plan-tabs", tabIds: ids }).then(function (payload) {
    if (payload && payload.hello) pageState.hello = payload.hello;
    renderReviews((payload && payload.rows) || []);
    say("Review the list, then save.");
  }, function (err) {
    say(String(err && err.message ? err.message : err));
  });
});
byId("save-tabs").addEventListener("click", function () {
  var jobs = [];
  var i;
  for (i = 0; i < pageState.reviews.length; i++) {
    var row = pageState.reviews[i];
    var listed = rowForTab(row.tabId) || {};
    jobs.push({
      tabId: row.tabId,
      confirmKey: reviewConfirm(row.tabId),
      sessionDoi: listed.sessionDoi || (row.detected && row.detected.doi) || "",
    });
  }
  say("Saving " + jobs.length + "…");
  send({
    type: "save-tabs",
    jobs: jobs,
    savePdf: byId("tabs-pdf").checked,
    lanes: byId("tabs-lanes").checked,
    allowUnread: byId("tabs-unread").checked,
    collection: byId("collection").value,
    tags: pageState.tags.slice(),
    note: byId("note").value,
  }).then(function (payload) {
    var summary = (payload && payload.summary) || {};
    byId("tabs-summary").textContent =
      "created " + (summary.created || 0) +
      " · updated " + (summary.updated || 0) +
      " · pdfs " + (summary.pdfs || 0) +
      " · snapshots " + (summary.snapshots || 0) +
      " · blocked " + (summary.blocked || 0);
    say("");
  }, function (err) {
    say(String(err && err.message ? err.message : err));
  });
});

send({ type: "plan-active" }).then(function (payload) {
  if (!payload || payload.ok === false) {
    say((payload && payload.reason) || "This page can't be saved.", "warn");
    send({ type: "hello" }).then(function (info) {
      pageState.hello = info;
      fillCollections(info, info && info.collection);
    }, function () {});
    return;
  }
  renderPage(payload);
}, function (err) {
  say(String(err && err.message ? err.message : err));
});
