function cleanDoi(raw) {
  var text = String(raw || "").trim().replace(/^doi:\s*/i, "");
  var match = text.match(/10\.\d{4,9}\/\S+/);
  if (!match) return "";
  return match[0].replace(/[.,;)\]]+$/, "");
}

function asList(value) {
  if (value == null || value === "") return [];
  if (Array.isArray(value)) return value;
  return [value];
}

function metaMaps() {
  var byName = {};
  var metas = document.getElementsByTagName("meta");
  var i;
  for (i = 0; i < metas.length; i++) {
    var name = String(
      metas[i].getAttribute("name") ||
        metas[i].getAttribute("property") ||
        metas[i].getAttribute("itemprop") ||
        ""
    ).toLowerCase();
    var content = String(metas[i].getAttribute("content") || "").trim();
    if (!name || !content) continue;
    if (!byName[name]) byName[name] = [];
    byName[name].push(content);
  }
  return byName;
}

function firstMeta(byName, names) {
  var i;
  for (i = 0; i < names.length; i++) {
    var rows = byName[names[i]];
    if (rows && rows[0]) return rows[0];
  }
  return "";
}

function allMeta(byName, names) {
  var out = [];
  var i;
  for (i = 0; i < names.length; i++) {
    var rows = byName[names[i]] || [];
    var r;
    for (r = 0; r < rows.length; r++) {
      if (rows[r] && out.indexOf(rows[r]) === -1) out.push(rows[r]);
    }
  }
  return out;
}

function yearFrom(text) {
  var match = String(text || "").match(/\b(1[89]\d{2}|20\d{2}|21\d{2})\b/);
  return match ? Number(match[1]) : null;
}

function authorName(row) {
  if (!row) return "";
  if (typeof row === "string") return row.trim();
  if (typeof row !== "object") return "";
  if (row.name) return String(row.name).trim();
  var given = String(row.givenName || row.given || "").trim();
  var family = String(row.familyName || row.family || "").trim();
  return (given + " " + family).trim();
}

function jsonLdFill(out) {
  var scripts = document.getElementsByTagName("script");
  var i;
  for (i = 0; i < scripts.length; i++) {
    var kind = String(scripts[i].getAttribute("type") || "").toLowerCase();
    if (kind.indexOf("ld+json") === -1) continue;
    var parsed;
    try {
      parsed = JSON.parse(scripts[i].textContent || "null");
    } catch (err) {
      continue;
    }
    var rows = asList(parsed);
    if (parsed && typeof parsed === "object" && parsed["@graph"]) {
      rows = rows.concat(asList(parsed["@graph"]));
    }
    var r;
    for (r = 0; r < rows.length; r++) {
      takeLd(out, rows[r]);
    }
  }
}

function ldType(row) {
  var types = asList(row && row["@type"]).map(function (value) {
    return String(value || "").split("/").pop();
  });
  var useful = ["ScholarlyArticle", "Article", "NewsArticle", "Report", "Book", "Chapter", "Thesis", "WebPage"];
  var i;
  for (i = 0; i < useful.length; i++) {
    if (types.indexOf(useful[i]) !== -1) return useful[i];
  }
  return "";
}

function takeLd(out, row) {
  if (!row || typeof row !== "object") return;
  var kind = ldType(row);
  if (!kind && !row.doi && !row.identifier) return;
  if (!out.doi) {
    var ids = asList(row.identifier).concat(asList(row.doi), asList(row["@id"]));
    var i;
    for (i = 0; i < ids.length; i++) {
      var value = ids[i];
      var text = typeof value === "string" ? value : String((value && (value.value || value.propertyID === "doi" && value.value)) || "");
      if (typeof value === "object" && value && value.propertyID) {
        var prop = String(value.propertyID || "").toLowerCase();
        if (prop.indexOf("doi") !== -1) text = String(value.value || "");
      }
      var doi = cleanDoi(text);
      if (!doi && String(text).indexOf("doi.org/") !== -1) {
        doi = cleanDoi(String(text).split("doi.org/").pop());
      }
      if (doi) {
        out.doi = doi;
        break;
      }
    }
  }
  if (!out.title && row.name) out.title = String(row.name).trim();
  if (!out.title && row.headline) out.title = String(row.headline).trim();
  if (!out.abstract && row.description) out.abstract = String(row.description).trim();
  if (!out.year) out.year = yearFrom(row.datePublished || row.dateCreated || "");
  if (!out.authors.length) {
    out.authors = asList(row.author).map(authorName).filter(Boolean).slice(0, 20);
  }
  if (!out.publication_title) {
    var part = row.isPartOf;
    if (typeof part === "string") out.publication_title = part;
    else if (part && typeof part === "object" && part.name) {
      out.publication_title = String(part.name).trim();
    }
  }
  if (!out.pdf_url && row.encoding) {
    var enc = asList(row.encoding);
    var e;
    for (e = 0; e < enc.length; e++) {
      var url = enc[e] && (enc[e].contentUrl || enc[e].url);
      if (url && /\.pdf(\?|$)/i.test(String(url))) {
        out.pdf_url = String(url).trim();
        break;
      }
    }
  }
}

function pdfLink() {
  var links = document.getElementsByTagName("link");
  var i;
  for (i = 0; i < links.length; i++) {
    var rel = String(links[i].getAttribute("rel") || "").toLowerCase();
    var type = String(links[i].getAttribute("type") || "").toLowerCase();
    var href = String(links[i].getAttribute("href") || "").trim();
    if (!href) continue;
    if (type === "application/pdf" || (rel.indexOf("alternate") !== -1 && /\.pdf(\?|$)/i.test(href))) {
      return href;
    }
  }
  var anchors = document.getElementsByTagName("a");
  for (i = 0; i < anchors.length; i++) {
    var text = String(anchors[i].textContent || "").trim().toLowerCase();
    var ahref = String(anchors[i].getAttribute("href") || "").trim();
    if (!ahref) continue;
    if ((text === "pdf" || text.indexOf("download pdf") !== -1) && /\.pdf(\?|$)/i.test(ahref)) {
      return ahref;
    }
  }
  var embed = document.querySelector("embed[type='application/pdf'], object[type='application/pdf']");
  if (embed) {
    var src = String(embed.getAttribute("src") || embed.getAttribute("data") || "").trim();
    if (src) return src;
  }
  return "";
}

function paperfulDetect() {
  var out = {
    doi: "",
    pdf_url: "",
    title: "",
    url: "",
    is_pdf: false,
    year: null,
    authors: [],
    abstract: "",
    publication_title: "",
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
  var byName = metaMaps();
  out.doi = cleanDoi(
    firstMeta(byName, [
      "citation_doi",
      "dc.identifier",
      "dc.identifier.doi",
      "prism.doi",
      "bepress_citation_doi",
    ])
  );
  var citedTitle = firstMeta(byName, ["citation_title", "dc.title", "citation_conference_title"]);
  if (citedTitle) out.title = citedTitle;
  out.pdf_url = firstMeta(byName, ["citation_pdf_url", "citation_fulltext_pdf_url"]);
  out.abstract = firstMeta(byName, ["citation_abstract", "dc.description", "description", "og:description"]);
  out.publication_title = firstMeta(byName, [
    "citation_journal_title",
    "citation_journal",
    "prism.publicationname",
    "dc.source",
  ]);
  out.year = yearFrom(
    firstMeta(byName, [
      "citation_year",
      "citation_date",
      "citation_publication_date",
      "citation_online_date",
      "prism.publicationdate",
      "dc.date",
    ])
  );
  out.authors = allMeta(byName, ["citation_author", "dc.creator", "citation_authors"]).slice(0, 20);
  jsonLdFill(out);
  if (!out.doi) {
    var links = document.getElementsByTagName("a");
    var i;
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
  if (!out.pdf_url) out.pdf_url = pdfLink();
  if (out.abstract.length > 8000) out.abstract = out.abstract.slice(0, 8000);
  if (out.title.length > 500) out.title = out.title.slice(0, 500);
  return out;
}

paperfulDetect();
