var pageState = { detected: null, plan: null, rows: [] };

function byId(id) {
  return document.getElementById(id);
}

function say(text) {
  byId("status").textContent = text || "";
}

function send(message) {
  return browser.runtime.sendMessage(message);
}

function showPage(on) {
  byId("page-view").hidden = !on;
  byId("tabs-view").hidden = on;
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

function renderPage(payload) {
  var detected = (payload && payload.detected) || {};
  var plan = (payload && payload.plan) || {};
  pageState.detected = detected;
  pageState.plan = plan;
  byId("page-title").textContent = detected.title || "Untitled";
  byId("page-doi").textContent = detected.doi || "no DOI";
  var line = actionLine(plan);
  if (plan.reason) line += " (" + plan.reason + ")";
  byId("page-action").textContent = line;
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
  byId("unread-label").hidden = plan.reason !== "zotero_unread";
  byId("allow-unread").checked = false;
  var canPdf = Boolean(detected.is_pdf || detected.pdf_url);
  byId("save-pdf").checked = canPdf;
  byId("pdf-label").hidden = !canPdf;
  byId("lanes-label").hidden = Boolean(plan.has_pdf);
  byId("search-lanes").checked = false;
  byId("save-page").disabled = plan.action === "blocked" && plan.reason === "refused_host";
}

function selectedConfirm() {
  var chosen = document.querySelector("input[name='confirm-key']:checked");
  return chosen ? chosen.value : "";
}

function renderTabs(rows) {
  pageState.rows = rows || [];
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
    span.textContent = (row.host ? row.host + " — " : "") + (row.title || "");
    label.appendChild(input);
    label.appendChild(span);
    list.appendChild(label);
  }
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

byId("show-page").addEventListener("click", function () {
  showPage(true);
});
byId("show-tabs").addEventListener("click", function () {
  showPage(false);
  say("Loading tabs…");
  send({ type: "list-tabs" }).then(function (payload) {
    renderTabs((payload && payload.rows) || []);
    say("");
  }, function (err) {
    say(String(err && err.message ? err.message : err));
  });
});
byId("select-walk").addEventListener("click", function () { setChecks("walk"); });
byId("select-all").addEventListener("click", function () { setChecks("all"); });
byId("select-none").addEventListener("click", function () { setChecks("none"); });
byId("save-page").addEventListener("click", function () {
  say("Saving…");
  send({
    type: "save-active",
    savePdf: byId("save-pdf").checked,
    lanes: byId("search-lanes").checked,
    allowUnread: byId("allow-unread").checked,
    confirmKey: selectedConfirm(),
  }).then(function (result) {
    if (!result) {
      say("No result");
      return;
    }
    var line = result.action || (result.ok ? "saved" : "not saved");
    if (result.key) line += " " + result.key;
    if (result.pdf) line += " · " + result.pdf;
    if (result.snapshot && result.snapshot !== "none") line += " · snapshot " + result.snapshot;
    if (result.reason) line += " (" + result.reason + ")";
    say(line);
  }, function (err) {
    say(String(err && err.message ? err.message : err));
  });
});
byId("save-tabs").addEventListener("click", function () {
  var ids = selectedTabIds();
  say("Saving " + ids.length + "…");
  send({
    type: "save-tabs",
    tabIds: ids,
    savePdf: byId("tabs-pdf").checked,
    lanes: byId("tabs-lanes").checked,
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
    say((payload && payload.reason) || "This page can't be saved.");
    return;
  }
  renderPage(payload);
}, function (err) {
  say(String(err && err.message ? err.message : err));
});
