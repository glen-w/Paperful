var lastHello = null;

function flash(text) {
  document.getElementById("flash").textContent = text || "";
}

function setStatus(text, kind) {
  var node = document.getElementById("status");
  node.textContent = text || "";
  node.className = "chip" + (kind ? " " + kind : "");
}

function detail(text) {
  document.getElementById("detail").textContent = text || "";
}

function dropLine(text) {
  document.getElementById("drop").textContent = text || "";
}

function hello() {
  flash("");
  setStatus("Checking the capture host…", "health-amber");
  browser.runtime.sendMessage({ type: "hello" }).then(function (payload) {
    lastHello = payload;
    if (!payload || payload.ok === false) {
      setStatus("Host not installed", "health-red");
      detail("Run paperful capture install-host, then reload this add-on.");
      dropLine("");
      return;
    }
    setStatus("Connected", "health-green");
    detail(
      "snapshot " + (payload.snapshot || "") +
      " · collection " + (payload.collection || "") +
      " · concurrency " + (payload.concurrency || "")
    );
    dropLine(payload.drop || "");
  }, function () {
    lastHello = null;
    setStatus("Host not installed", "health-red");
    detail("Run paperful capture install-host, then reload this add-on.");
    dropLine("");
  });
}

document.getElementById("retry").addEventListener("click", hello);
document.getElementById("copy-drop").addEventListener("click", function () {
  var path = lastHello && lastHello.drop;
  if (!path) {
    flash("No drop path yet");
    return;
  }
  navigator.clipboard.writeText(path).then(function () {
    flash("Copied drop path");
  }, function () {
    flash(path);
  });
});
document.getElementById("open-drop").addEventListener("click", function () {
  browser.runtime.sendMessage({ type: "open-target", target: "drop" }).then(function (payload) {
    if (!payload || payload.ok === false) {
      flash((payload && payload.reason) || "Could not open the drop folder");
    }
  }, function () {
    flash("Could not open the drop folder");
  });
});
hello();
