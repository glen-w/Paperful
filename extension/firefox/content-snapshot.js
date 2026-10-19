var SNAPSHOT_MAX = 2000000;
var CSS_MAX = 300000;

function readableCss() {
  var chunks = [];
  var used = 0;
  var sheets = document.styleSheets;
  var i;
  for (i = 0; i < sheets.length; i++) {
    var rules;
    try {
      rules = sheets[i].cssRules;
    } catch (err) {
      continue;
    }
    if (!rules) continue;
    var r;
    for (r = 0; r < rules.length; r++) {
      var text = "";
      try {
        text = String(rules[r].cssText || "");
      } catch (err) {
        text = "";
      }
      if (!text || used + text.length > CSS_MAX) continue;
      chunks.push(text);
      used += text.length;
    }
  }
  return chunks.join("\n");
}

function quietClone(node) {
  var root = node.cloneNode(true);
  var blocked = root.querySelectorAll("script, noscript, iframe, object, embed");
  var i;
  for (i = blocked.length - 1; i >= 0; i--) {
    if (blocked[i].parentNode) blocked[i].parentNode.removeChild(blocked[i]);
  }
  var all = root.querySelectorAll("*");
  for (i = 0; i < all.length; i++) {
    var el = all[i];
    var attrs = el.attributes;
    if (!attrs) continue;
    var names = [];
    var a;
    for (a = 0; a < attrs.length; a++) names.push(attrs[a].name);
    for (a = 0; a < names.length; a++) {
      var attrName = String(names[a] || "");
      var lower = attrName.toLowerCase();
      if (lower.slice(0, 2) === "on") el.removeAttribute(attrName);
      else if (lower === "href" || lower === "src" || lower === "action") {
        var value = String(el.getAttribute(attrName) || "").replace(/^\s+/, "").toLowerCase();
        if (value.slice(0, 11) === "javascript:") el.removeAttribute(attrName);
      }
    }
  }
  var css = readableCss();
  if (css) {
    var style = document.createElement("style");
    style.textContent = css;
    var head = root.querySelector("head");
    if (!head) {
      head = document.createElement("head");
      root.insertBefore(head, root.firstChild);
    }
    head.insertBefore(style, head.firstChild);
  }
  var base = document.createElement("base");
  try {
    base.setAttribute("href", String(document.location.href || ""));
  } catch (err) {
    base.setAttribute("href", "");
  }
  var head2 = root.querySelector("head");
  if (head2) head2.insertBefore(base, head2.firstChild);
  return root;
}

function serialize(node) {
  if (!node) return "";
  try {
    return String(new XMLSerializer().serializeToString(quietClone(node)) || "");
  } catch (err) {
    return "";
  }
}

function paperfulSnapshot() {
  var full = serialize(document.documentElement);
  var html = full;
  if (!html || html.length > SNAPSHOT_MAX) {
    var smaller = document.querySelector("article") || document.querySelector("main") || document.body;
    html = serialize(smaller);
  }
  if (!html || html.length > SNAPSHOT_MAX) {
    return { html: "", title: String(document.title || ""), url: "" };
  }
  var url = "";
  try {
    url = String(document.location.href || "");
  } catch (err) {
    url = "";
  }
  return {
    html: "<!DOCTYPE html>\n" + html,
    title: String(document.title || ""),
    url: url,
  };
}

paperfulSnapshot();
