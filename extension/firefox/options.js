function say(text) {
  document.getElementById("status").textContent = text || "";
}

function detail(text) {
  document.getElementById("detail").textContent = text || "";
}

function hello() {
  say("Checking the capture host…");
  browser.runtime.sendMessage({ type: "hello" }).then(function (payload) {
    if (!payload || payload.ok === false) {
      say("Paperful capture host is not installed");
      detail("");
      return;
    }
    say("Connected");
    detail(
      "snapshot " + (payload.snapshot || "") +
      " · collection " + (payload.collection || "") +
      " · drop " + (payload.drop || "")
    );
  }, function () {
    say("Paperful capture host is not installed");
    detail("");
  });
}

document.getElementById("retry").addEventListener("click", hello);
hello();
