var REFUSED = [
  "sci-hub.",
  "libgen.",
  "annas-archive.org",
  "libgen.rs",
  "libgen.is",
  "libgen.li",
  "library.lol",
];

var port = null;
var waiters = {};
var seq = 1;
var cachedHello = null;

function isHttp(url) {
  try {
    var parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch (err) {
    return false;
  }
}

function blockedPage(url) {
  try {
    var protocol = new URL(url).protocol;
    return (
      protocol === "about:" ||
      protocol === "moz-extension:" ||
      protocol === "chrome:" ||
      protocol === "file:" ||
      protocol === "blob:" ||
      protocol === "data:" ||
      protocol === "view-source:"
    );
  } catch (err) {
    return true;
  }
}

function refusedHost(url) {
  var host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch (err) {
    return false;
  }
  var labels = host.split(".");
  var i;
  for (i = 0; i < REFUSED.length; i++) {
    var suffix = REFUSED[i];
    if (suffix.charAt(suffix.length - 1) === ".") {
      if (labels.indexOf(suffix.slice(0, -1)) !== -1) return true;
    } else if (host === suffix || host.slice(-(suffix.length + 1)) === "." + suffix) {
      return true;
    }
  }
  return false;
}

function normalizeUrl(url) {
  try {
    var parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    parsed.hash = "";
    if (parsed.pathname.length > 1 && parsed.pathname.charAt(parsed.pathname.length - 1) === "/") {
      parsed.pathname = parsed.pathname.slice(0, -1);
    }
    return parsed.href;
  } catch (err) {
    return "";
  }
}

function doiInUrl(url, doi) {
  if (!doi) return false;
  var lower = String(url || "").toLowerCase();
  return lower.indexOf(String(doi).toLowerCase()) !== -1;
}

function nativePort() {
  if (port) return port;
  port = browser.runtime.connectNative("paperful");
  port.onMessage.addListener(function (msg) {
    var id = msg && msg.id;
    var waiter = waiters[id];
    if (waiter) {
      delete waiters[id];
      waiter.resolve(msg);
    }
  });
  port.onDisconnect.addListener(function () {
    port = null;
    cachedHello = null;
    var ids = Object.keys(waiters);
    var i;
    for (i = 0; i < ids.length; i++) {
      var waiter = waiters[ids[i]];
      delete waiters[ids[i]];
      waiter.reject(new Error("Paperful capture host is not installed"));
    }
  });
  return port;
}

function request(msg) {
  return new Promise(function (resolve, reject) {
    var id = seq;
    seq += 1;
    if (seq > 100000000) seq = 1;
    msg.id = id;
    var timer = setTimeout(function () {
      if (!waiters[id]) return;
      delete waiters[id];
      reject(new Error("Paperful capture host timed out"));
    }, 180000);
    waiters[id] = {
      resolve: function (payload) {
        clearTimeout(timer);
        resolve(payload);
      },
      reject: function (err) {
        clearTimeout(timer);
        reject(err);
      },
    };
    try {
      nativePort().postMessage(msg);
    } catch (err) {
      delete waiters[id];
      clearTimeout(timer);
      reject(err);
    }
  });
}

function hello() {
  return request({ type: "hello" }).then(function (payload) {
    cachedHello = payload && payload.ok ? payload : null;
    return payload;
  });
}

function fromExtension(sender) {
  return Boolean(sender && sender.id && sender.id === browser.runtime.id);
}

function shapeDetect(raw) {
  if (!raw || typeof raw !== "object") return null;
  var authors = [];
  if (Array.isArray(raw.authors)) {
    authors = raw.authors.map(function (row) { return String(row || "").trim(); }).filter(Boolean).slice(0, 20);
  } else if (raw.authors) {
    authors = String(raw.authors).split(",").map(function (row) { return row.trim(); }).filter(Boolean).slice(0, 20);
  }
  var year = raw.year;
  if (year !== null && year !== undefined && year !== "") {
    year = Number(year);
    if (!year) year = null;
  } else {
    year = null;
  }
  return {
    doi: String(raw.doi || ""),
    pdf_url: String(raw.pdf_url || ""),
    title: String(raw.title || ""),
    url: String(raw.url || ""),
    is_pdf: Boolean(raw.is_pdf),
    year: year,
    authors: authors,
    abstract: String(raw.abstract || ""),
    publication_title: String(raw.publication_title || ""),
  };
}

function detectTab(tabId) {
  return browser.scripting
    .executeScript({ target: { tabId: tabId }, files: ["content.js"] })
    .then(function (injected) {
      var first = injected && injected[0];
      return shapeDetect(first && first.result);
    });
}

function fileName(detected, plan) {
  var raw = (detected && detected.doi) || (plan && plan.key) || "paper";
  raw = String(raw).replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 80);
  if (!raw) raw = "paper";
  return raw + ".pdf";
}

function downloadToDisk(url, name) {
  return new Promise(function (resolve, reject) {
    if (!isHttp(url) || refusedHost(url)) {
      reject(new Error("refused"));
      return;
    }
    browser.downloads
      .download({
        url: url,
        filename: name,
        saveAs: false,
        conflictAction: "uniquify",
      })
      .then(function (id) {
        function done(delta) {
          if (!delta || delta.id !== id) return;
          if (delta.state && delta.state.current === "complete") {
            browser.downloads.onChanged.removeListener(done);
            browser.downloads.search({ id: id }).then(function (items) {
              var item = items && items[0];
              resolve((item && item.filename) || "");
            }, reject);
          } else if (delta.error) {
            browser.downloads.onChanged.removeListener(done);
            reject(new Error(String(delta.error.current || "download failed")));
          }
        }
        browser.downloads.onChanged.addListener(done);
      }, reject);
  });
}

function downloadBlob(filename, blob) {
  var objectUrl = URL.createObjectURL(blob);
  return new Promise(function (resolve, reject) {
    browser.downloads
      .download({
        url: objectUrl,
        filename: filename,
        saveAs: false,
        conflictAction: "uniquify",
      })
      .then(function (id) {
        function done(delta) {
          if (!delta || delta.id !== id) return;
          if (delta.state && delta.state.current === "complete") {
            browser.downloads.onChanged.removeListener(done);
            URL.revokeObjectURL(objectUrl);
            browser.downloads.search({ id: id }).then(function (items) {
              var item = items && items[0];
              resolve((item && item.filename) || "");
            }, reject);
          } else if (delta.error) {
            browser.downloads.onChanged.removeListener(done);
            URL.revokeObjectURL(objectUrl);
            reject(new Error(String(delta.error.current || "download failed")));
          }
        }
        browser.downloads.onChanged.addListener(done);
      }, function (err) {
        URL.revokeObjectURL(objectUrl);
        reject(err);
      });
  });
}

function stagePath(path) {
  if (!path) return Promise.resolve("");
  return request({ type: "capture.stage", path: path }).then(function (payload) {
    if (payload && payload.ok && payload.path) return payload.path;
    return "";
  }, function () {
    return "";
  });
}

function pageFields(detected) {
  return {
    doi: detected.doi,
    url: detected.url,
    title: detected.title,
    pdf_url: detected.pdf_url,
    year: detected.year,
    authors: detected.authors,
    abstract: detected.abstract,
    publication_title: detected.publication_title,
  };
}

function planFromDetect(detected) {
  var page = pageFields(detected);
  return request({
    type: "capture.plan",
    doi: page.doi,
    url: page.url,
    title: page.title,
    year: page.year,
    pdf_url: page.pdf_url,
    page: page,
  });
}

function applyDetected(detected, flags, pdfPath, htmlPath) {
  var page = pageFields(detected);
  return request({
    type: "capture.apply",
    apply: true,
    doi: page.doi,
    url: page.url,
    title: page.title,
    year: page.year,
    pdf_url: page.pdf_url,
    pdf_path: pdfPath || "",
    html_path: htmlPath || "",
    lanes: Boolean(flags.lanes),
    allow_unread: Boolean(flags.allowUnread),
    confirm_key: flags.confirmKey || "",
    collection: flags.collection || "",
    tags: flags.tags || [],
    note: flags.note || "",
    page: page,
  });
}

function captureSnapshot(tabId) {
  if (!tabId && tabId !== 0) return Promise.resolve("");
  return browser.scripting
    .executeScript({
      target: { tabId: tabId },
      files: ["content-snapshot.js"],
    })
    .then(function (injected) {
      var first = injected && injected[0];
      var result = first && first.result;
      if (!result || typeof result.html !== "string" || !result.html) return "";
      return result.html;
    }, function () {
      return "";
    });
}

function saveDetected(detected, flags, tabId) {
  if (!detected || blockedPage(detected.url) || !isHttp(detected.url)) {
    return Promise.resolve({ ok: false, action: "blocked", reason: "blocked_page" });
  }
  if (refusedHost(detected.url) || refusedHost(detected.pdf_url)) {
    return Promise.resolve({ ok: false, action: "blocked", reason: "refused_host" });
  }
  return planFromDetect(detected).then(function (plan) {
    if (plan && plan.action === "blocked" && plan.reason === "zotero_unread" && flags.allowUnread) {
      return finishSave(detected, plan, flags, tabId);
    }
    if (plan && plan.action === "ambiguous" && flags.confirmKey) {
      return finishSave(detected, plan, flags, tabId);
    }
    if (!plan || plan.action === "blocked" || plan.action === "ambiguous") {
      return plan || { ok: false, reason: "invalid" };
    }
    return finishSave(detected, plan, flags, tabId);
  });
}

function finishSave(detected, plan, flags, tabId) {
  var pdfUrl = "";
  if (flags.savePdf) {
    pdfUrl = detected.is_pdf ? detected.url : detected.pdf_url;
  }
  var downloaded = Promise.resolve("");
  if (pdfUrl && isHttp(pdfUrl) && !refusedHost(pdfUrl)) {
    downloaded = downloadToDisk(pdfUrl, fileName(detected, plan)).then(stagePath, function () {
      return "";
    });
  }
  return downloaded.then(function (pdfPath) {
    if (pdfPath || (plan && plan.has_pdf) || detected.is_pdf) {
      return applyDetected(detected, flags, pdfPath, "");
    }
    return captureSnapshot(tabId).then(function (html) {
      if (!html) return applyDetected(detected, flags, pdfPath, "");
      var name = fileName(detected, plan).replace(/\.pdf$/, "") + "-snapshot.html";
      return downloadBlob(name, new Blob([html], { type: "text/html" })).then(function (htmlPath) {
        return stagePath(htmlPath).then(function (staged) {
          return applyDetected(detected, flags, pdfPath, staged);
        });
      }, function () {
        return applyDetected(detected, flags, pdfPath, "");
      });
    });
  });
}

function activeTab() {
  return browser.tabs.query({ active: true, currentWindow: true }).then(function (tabs) {
    return tabs && tabs[0];
  });
}

function planActive() {
  return activeTab().then(function (tab) {
    if (!tab || blockedPage(tab.url || "")) {
      return { ok: false, reason: "blocked_page" };
    }
    return detectTab(tab.id).then(function (detected) {
      if (!detected) return { ok: false, reason: "no_page" };
      return planFromDetect(detected).then(function (plan) {
        return hello().then(function (info) {
          return { ok: true, detected: detected, plan: plan, hello: info };
        }, function () {
          return { ok: true, detected: detected, plan: plan, hello: null };
        });
      });
    });
  });
}

function saveActive(flags) {
  return activeTab().then(function (tab) {
    if (!tab) return { ok: false, reason: "no_page" };
    return detectTab(tab.id).then(function (detected) {
      return saveDetected(detected, flags || {}, tab.id);
    });
  }).then(function (result) {
    refreshBadge();
    return result;
  });
}

function sessionIndex(session) {
  var byUrl = {};
  var byDoi = {};
  var items = (session && session.items) || [];
  var i;
  for (i = 0; i < items.length; i++) {
    var row = items[i] || {};
    if (row.saved_at) continue;
    var norm = normalizeUrl(row.url);
    if (norm) byUrl[norm] = row;
    if (row.doi) byDoi[String(row.doi).toLowerCase()] = row;
  }
  return { byUrl: byUrl, byDoi: byDoi };
}

function matchSession(url, doi, index) {
  var hit = index.byUrl[normalizeUrl(url)];
  if (hit) return hit;
  if (doi && index.byDoi[String(doi).toLowerCase()]) return index.byDoi[String(doi).toLowerCase()];
  var keys = Object.keys(index.byDoi);
  var i;
  for (i = 0; i < keys.length; i++) {
    if (doiInUrl(url, keys[i])) return index.byDoi[keys[i]];
  }
  return null;
}

function tabRows(session) {
  return browser.tabs.query({ currentWindow: true }).then(function (tabs) {
    var index = sessionIndex(session || {});
    var rows = [];
    var i;
    for (i = 0; i < (tabs || []).length; i++) {
      var tab = tabs[i];
      var url = tab.url || "";
      if (!isHttp(url) || blockedPage(url)) continue;
      var host = "";
      try {
        host = new URL(url).hostname;
      } catch (err) {
        host = "";
      }
      var hit = matchSession(url, "", index);
      rows.push({
        tabId: tab.id,
        title: tab.title || url,
        host: host,
        url: url,
        checked: Boolean(hit),
        sessionKey: hit ? hit.key || "" : "",
        sessionDoi: hit ? hit.doi || "" : "",
      });
    }
    return rows;
  });
}

function listTabs() {
  return Promise.all([
    request({ type: "handoff.session" }).catch(function () {
      return { items: [] };
    }),
    hello().catch(function () {
      return null;
    }),
  ]).then(function (pair) {
    var session = pair[0] || {};
    var info = pair[1];
    return tabRows(session).then(function (rows) {
      setBadgeCount(rows.filter(function (row) { return row.checked; }).length);
      return { ok: true, rows: rows, hello: info };
    });
  });
}

function runPool(items, limit, worker) {
  var cursor = 0;
  var active = 0;
  var results = [];
  var cap = limit > 0 ? limit : 1;
  return new Promise(function (resolve) {
    function pump() {
      if (cursor >= items.length && active === 0) {
        resolve(results);
        return;
      }
      while (active < cap && cursor < items.length) {
        var item = items[cursor];
        var slot = cursor;
        cursor += 1;
        active += 1;
        Promise.resolve(worker(item)).then(
          function (value) {
            results[slot] = value;
            active -= 1;
            pump();
          },
          function () {
            results[slot] = { ok: false, reason: "error" };
            active -= 1;
            pump();
          }
        );
      }
    }
    if (!items.length) resolve(results);
    else pump();
  });
}

function mergeSessionDoi(detected, sessionDoi) {
  if (!detected) return detected;
  if (!detected.doi && sessionDoi) detected.doi = String(sessionDoi);
  return detected;
}

function planTabs(message) {
  var ids = message.tabIds || [];
  return Promise.all([
    hello().catch(function () {
      return { concurrency: 2 };
    }),
    request({ type: "handoff.session" }).catch(function () {
      return { items: [] };
    }),
  ]).then(function (pair) {
    var info = pair[0];
    var index = sessionIndex(pair[1] || {});
    var limit = Number(info && info.concurrency) || 2;
    return runPool(ids, limit, function (tabId) {
      return detectTab(tabId).then(function (detected) {
        if (!detected) {
          return { tabId: tabId, ok: false, reason: "no_page" };
        }
        var hit = matchSession(detected.url, detected.doi, index);
        detected = mergeSessionDoi(detected, hit && hit.doi);
        return planFromDetect(detected).then(function (plan) {
          return { tabId: tabId, ok: true, detected: detected, plan: plan };
        });
      });
    }).then(function (results) {
      return { ok: true, rows: results, hello: info };
    });
  });
}

function saveTabs(message) {
  var jobs = message.jobs || [];
  var flags = {
    savePdf: Boolean(message.savePdf),
    lanes: Boolean(message.lanes),
    allowUnread: Boolean(message.allowUnread),
    collection: message.collection || "",
    tags: message.tags || [],
    note: message.note || "",
  };
  return hello()
    .catch(function () {
      return { concurrency: 2 };
    })
    .then(function (info) {
      var limit = Number(info && info.concurrency) || 2;
      return runPool(jobs, limit, function (job) {
        var tabId = job.tabId;
        var rowFlags = {
          savePdf: flags.savePdf,
          lanes: flags.lanes,
          allowUnread: flags.allowUnread,
          confirmKey: job.confirmKey || "",
          collection: flags.collection,
          tags: flags.tags,
          note: flags.note,
        };
        return detectTab(tabId).then(function (detected) {
          detected = mergeSessionDoi(detected, job.sessionDoi);
          return saveDetected(detected, rowFlags, tabId);
        });
      }).then(function (results) {
        var summary = { created: 0, updated: 0, pdfs: 0, snapshots: 0, blocked: 0, notes: 0 };
        var i;
        for (i = 0; i < results.length; i++) {
          var row = results[i] || {};
          if (row.action === "create") summary.created += 1;
          else if (row.action === "update") summary.updated += 1;
          else summary.blocked += 1;
          if (row.pdf === "saved") summary.pdfs += 1;
          if (row.snapshot === "saved") summary.snapshots += 1;
          if (row.note === "saved") summary.notes += 1;
        }
        refreshBadge();
        return { ok: true, summary: summary, results: results };
      });
    });
}

function setBadgeCount(count) {
  var text = count > 0 ? String(count) : "";
  browser.action.setBadgeBackgroundColor({ color: "#c46a2a" });
  browser.action.setBadgeText({ text: text });
}

var badgeTimer = null;
function refreshBadge() {
  if (badgeTimer) clearTimeout(badgeTimer);
  badgeTimer = setTimeout(function () {
    badgeTimer = null;
    request({ type: "handoff.session" })
      .catch(function () {
        return { items: [] };
      })
      .then(tabRows)
      .then(function (rows) {
        setBadgeCount(rows.filter(function (row) { return row.checked; }).length);
      })
      .catch(function () {
        setBadgeCount(0);
      });
  }, 800);
}

function openWorkbench(message) {
  return hello().then(function (info) {
    var base = (info && info.workbench) || "";
    if (!base) return { ok: false, reason: "no_workbench" };
    var query = message.doi || message.key || "";
    var url = base + "/wanted";
    if (query) url += "?q=" + encodeURIComponent(query);
    return browser.tabs.create({ url: url }).then(function () {
      return { ok: true };
    });
  });
}

function saveTabById(tabId, flags) {
  return detectTab(tabId).then(function (detected) {
    return saveDetected(detected, flags || { savePdf: true, lanes: false }, tabId);
  }).then(function (result) {
    refreshBadge();
    return result;
  });
}

browser.runtime.onMessage.addListener(function (message, sender) {
  if (!fromExtension(sender)) return undefined;
  if (!message || typeof message !== "object" || !message.type) return undefined;
  if (message.type === "hello") return hello();
  if (message.type === "plan-active") return planActive();
  if (message.type === "save-active") return saveActive(message);
  if (message.type === "list-tabs") return listTabs();
  if (message.type === "plan-tabs") return planTabs(message);
  if (message.type === "save-tabs") return saveTabs(message);
  if (message.type === "open-target") {
    return request({
      type: "capture.open",
      target: message.target || "",
      key: message.key || "",
    });
  }
  if (message.type === "open-workbench") return openWorkbench(message);
  if (message.type === "tag-suggest") {
    return request({
      type: "capture.tag_suggest",
      query: message.query || "",
      doi: message.doi || "",
    }).then(function (payload) {
      return payload || { ok: false };
    });
  }
  return undefined;
});

browser.contextMenus.removeAll().then(function () {
  browser.contextMenus.create({
    id: "paperful-save-page",
    title: "Save to Paperful",
    contexts: ["page", "tab", "frame"],
  });
  browser.contextMenus.create({
    id: "paperful-save-link",
    title: "Save link to Paperful",
    contexts: ["link"],
  });
});

browser.contextMenus.onClicked.addListener(function (info, tab) {
  var flags = { savePdf: true, lanes: false };
  if (info.menuItemId === "paperful-save-page" && tab && tab.id != null) {
    saveTabById(tab.id, flags);
    return;
  }
  if (info.menuItemId === "paperful-save-link" && info.linkUrl && isHttp(info.linkUrl)) {
    if (refusedHost(info.linkUrl)) return;
    var detected = shapeDetect({
      url: info.linkUrl,
      title: info.linkText || info.linkUrl,
      is_pdf: /\.pdf(\?|$)/i.test(info.linkUrl),
      pdf_url: /\.pdf(\?|$)/i.test(info.linkUrl) ? info.linkUrl : "",
    });
    saveDetected(detected, flags, tab && tab.id);
  }
});

browser.commands.onCommand.addListener(function (name) {
  if (name !== "save-page") return;
  saveActive({ savePdf: true, lanes: false });
});

browser.tabs.onUpdated.addListener(function () {
  refreshBadge();
});
browser.tabs.onRemoved.addListener(function () {
  refreshBadge();
});
refreshBadge();
