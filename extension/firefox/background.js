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
var waiters = [];

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

function nativePort() {
  if (port) return port;
  port = browser.runtime.connectNative("paperful");
  port.onMessage.addListener(function (msg) {
    var waiter = waiters.shift();
    if (waiter) waiter.resolve(msg);
  });
  port.onDisconnect.addListener(function () {
    port = null;
    while (waiters.length) {
      waiters.shift().reject(new Error("Paperful capture host is not installed"));
    }
  });
  return port;
}

function request(msg) {
  return new Promise(function (resolve, reject) {
    try {
      nativePort().postMessage(msg);
    } catch (err) {
      reject(err);
      return;
    }
    waiters.push({ resolve: resolve, reject: reject });
  });
}

function fromExtension(sender) {
  return Boolean(sender && sender.id && sender.id === browser.runtime.id);
}

function shapeDetect(raw) {
  if (!raw || typeof raw !== "object") return null;
  return {
    doi: String(raw.doi || ""),
    pdf_url: String(raw.pdf_url || ""),
    title: String(raw.title || ""),
    url: String(raw.url || ""),
    is_pdf: Boolean(raw.is_pdf),
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

function downloadPdf(url, name) {
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

function planFromDetect(detected) {
  return request({
    type: "capture.plan",
    doi: detected.doi,
    url: detected.url,
    title: detected.title,
    pdf_url: detected.pdf_url,
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

function applyDetected(detected, plan, flags, pdfPath, htmlPath) {
  return request({
    type: "capture.apply",
    apply: true,
    doi: detected.doi,
    url: detected.url,
    title: detected.title,
    pdf_url: detected.pdf_url,
    pdf_path: pdfPath || "",
    html_path: htmlPath || "",
    lanes: Boolean(flags.lanes),
    allow_unread: Boolean(flags.allowUnread),
    confirm_key: flags.confirmKey || "",
    page: {
      doi: detected.doi,
      url: detected.url,
      title: detected.title,
      pdf_url: detected.pdf_url,
    },
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
    downloaded = downloadPdf(pdfUrl, fileName(detected, plan)).catch(function () {
      return "";
    });
  }
  return downloaded.then(function (pdfPath) {
    if (pdfPath || (plan && plan.has_pdf) || detected.is_pdf) {
      return applyDetected(detected, plan, flags, pdfPath, "");
    }
    return captureSnapshot(tabId).then(function (html) {
      if (!html) return applyDetected(detected, plan, flags, pdfPath, "");
      var name = fileName(detected, plan).replace(/\.pdf$/, "") + "-snapshot.html";
      return downloadBlob(name, new Blob([html], { type: "text/html" })).then(function (htmlPath) {
        return applyDetected(detected, plan, flags, pdfPath, htmlPath);
      }, function () {
        return applyDetected(detected, plan, flags, pdfPath, "");
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
        return { ok: true, detected: detected, plan: plan };
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
  });
}

function listTabs() {
  return Promise.all([
    browser.tabs.query({ currentWindow: true }),
    request({ type: "handoff.session" }).catch(function () {
      return { items: [] };
    }),
  ]).then(function (pair) {
    var tabs = pair[0] || [];
    var session = pair[1] || {};
    var wanted = {};
    var items = session.items || [];
    var i;
    for (i = 0; i < items.length; i++) {
      var norm = normalizeUrl(items[i] && items[i].url);
      if (norm) wanted[norm] = true;
    }
    var rows = [];
    for (i = 0; i < tabs.length; i++) {
      var tab = tabs[i];
      var url = tab.url || "";
      if (!isHttp(url) || blockedPage(url)) continue;
      var host = "";
      try {
        host = new URL(url).hostname;
      } catch (err) {
        host = "";
      }
      rows.push({
        tabId: tab.id,
        title: tab.title || url,
        host: host,
        url: url,
        checked: Boolean(wanted[normalizeUrl(url)]),
      });
    }
    return { ok: true, rows: rows };
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
        cursor += 1;
        active += 1;
        Promise.resolve(worker(item)).then(
          function (value) {
            results.push(value);
            active -= 1;
            pump();
          },
          function () {
            results.push({ ok: false, reason: "error" });
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

function saveTabs(message) {
  var ids = message.tabIds || [];
  var flags = {
    savePdf: Boolean(message.savePdf),
    lanes: Boolean(message.lanes),
    allowUnread: false,
    confirmKey: "",
  };
  return request({ type: "hello" })
    .catch(function () {
      return { concurrency: 2 };
    })
    .then(function (hello) {
      var limit = Number(hello && hello.concurrency) || 2;
      return runPool(ids, limit, function (tabId) {
        return detectTab(tabId).then(function (detected) {
          return saveDetected(detected, flags, tabId);
        });
      }).then(function (results) {
        var summary = { created: 0, updated: 0, pdfs: 0, snapshots: 0, blocked: 0 };
        var i;
        for (i = 0; i < results.length; i++) {
          var row = results[i] || {};
          if (row.action === "create") summary.created += 1;
          else if (row.action === "update") summary.updated += 1;
          else summary.blocked += 1;
          if (row.pdf === "saved") summary.pdfs += 1;
          if (row.snapshot === "saved") summary.snapshots += 1;
        }
        return { ok: true, summary: summary };
      });
    });
}

browser.runtime.onMessage.addListener(function (message, sender) {
  if (!fromExtension(sender)) return undefined;
  if (!message || typeof message !== "object" || !message.type) return undefined;
  if (message.type === "hello") return request({ type: "hello" });
  if (message.type === "plan-active") return planActive();
  if (message.type === "save-active") return saveActive(message);
  if (message.type === "list-tabs") return listTabs();
  if (message.type === "save-tabs") return saveTabs(message);
  return undefined;
});
