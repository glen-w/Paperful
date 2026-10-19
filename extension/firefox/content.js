function cleanDoi(raw) {
  var text = String(raw || "").trim().replace(/^doi:\s*/i, "");
  var match = text.match(/10\.\d{4,9}\/\S+/);
  if (!match) return "";
  return match[0].replace(/[.,;)\]]+$/, "");
}

function paperfulDetect() {
  var out = {
    doi: "",
    pdf_url: "",
    title: "",
    url: "",
    is_pdf: false,
  };
  try {
    out.url = String(document.location.href || "");
  } catch (err) {
    out.url = "";
  }
  out.title = String(document.title || "");
  var path = "";
  var kind = "";
  try {
    path = String(document.location.pathname || "");
    kind = String(document.contentType || "");
  } catch (err) {
    path = "";
  }
  if (kind === "application/pdf" || /\.pdf$/i.test(path)) {
    out.is_pdf = true;
  }
  var names = ["citation_doi", "dc.identifier", "dc.identifier.doi", "prism.doi"];
  var metas = document.getElementsByTagName("meta");
  var i;
  for (i = 0; i < metas.length; i++) {
    var metaName = String(metas[i].getAttribute("name") || "").toLowerCase();
    var content = String(metas[i].getAttribute("content") || "");
    if (!out.doi && names.indexOf(metaName) !== -1) out.doi = cleanDoi(content);
    if (!out.pdf_url && metaName === "citation_pdf_url") out.pdf_url = content.trim();
  }
  if (!out.doi) {
    var links = document.getElementsByTagName("a");
    for (i = 0; i < links.length; i++) {
      var href = String(links[i].getAttribute("href") || "");
      var at = href.toLowerCase().indexOf("doi.org/");
      if (at !== -1) {
        out.doi = cleanDoi(href.slice(at + "doi.org/".length));
        if (out.doi) break;
      }
    }
  }
  if (!out.doi && document.body) {
    var found = String(document.body.textContent || "").match(/10\.\d{4,9}\/\S+/);
    if (found) out.doi = cleanDoi(found[0]);
  }
  return out;
}

paperfulDetect();
