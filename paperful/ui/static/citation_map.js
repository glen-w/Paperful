(function () {
  var ROLE_FILL = {
    foundational: "#3d5a80",
    influential: "#c46a2a",
    emerging: "#2f6f4e",
    other: "#8d99a6",
  };
  var ROLE_LABEL = {
    foundational: "Foundational — older and highly cited",
    influential: "Influential — recent and highly cited",
    emerging: "Emerging — recent, fewer citations",
    other: "Other — older, fewer citations",
  };

  var state = {
    graphUrl: "",
    runId: "",
    watchName: "",
    compareRun: "",
    nodes: [],
    edges: [],
    triage: [],
    ghostNodes: [],
    ghostEdges: [],
    direction: "both",
    layout: "citation",
    similar: null,
    view: { color: "role", size_by: "citations", labels: "auto", fit: true, authors: 12, direction: "both" },
    directionRun: "",
    mapView: "papers",
    viewRun: "",
    authorNodes: [],
    authorEdges: [],
    authorTruncated: 0,
    authors: [],
    highlight: new Set(),
    highlightLabel: "",
    userZoomed: false,
    fitFn: null,
    focusFn: null,
    restyle: null,
    lastGraph: null,
    applyPath: null,
    showOccasional: false,
    showHalo: false,
    yearMin: 1900,
    yearMax: 2100,
    yearLo: 1900,
    yearHi: 2100,
    simulation: null,
    reduceMotion: false,
    selectedId: "",
    pathMode: false,
    pathFirst: "",
    pathEdges: [],
    expandBlocked: false,
    triageById: {},
    categoryLegend: [],
    categoryFilter: "",
    categoryById: {},
    metaCollections: [],
    metaTags: [],
    editMode: "both",
    largeView: false,
  };
  var els = {};

  function init() {
    var root = document.getElementById("citationMapApp");
    if (!root || typeof d3 === "undefined") {
      var status = document.getElementById("citationStatus");
      if (status && typeof d3 === "undefined") {
        status.textContent = "The map could not load its drawing library.";
      }
      return;
    }
    els.root = root;
    els.svg = d3.select("#citationCanvas");
    els.panel = document.getElementById("citationPanel");
    els.status = document.getElementById("citationStatus");
    els.triage = document.getElementById("citationTriage");
    els.thresholds = document.getElementById("citationThresholds");
    els.toggle = document.getElementById("citationShowOccasional");
    els.halo = document.getElementById("citationLibraryHalo");
    els.repair = document.getElementById("citationRepairLinks");
    els.pathMode = document.getElementById("citationPathMode");
    els.largeView = document.getElementById("citationLargeView");
    els.search = document.getElementById("citationSearch");
    root.querySelectorAll("[data-map-view]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setMapView(btn.getAttribute("data-map-view") || "papers");
      });
    });
    els.fit = document.getElementById("citationFit");
    els.exportSel = document.getElementById("citationExport");
    els.highlightNote = document.getElementById("citationHighlight");
    if (els.search) {
      els.search.addEventListener("input", onSearch);
      els.search.addEventListener("keydown", onSearchKey);
    }
    if (els.fit) {
      els.fit.addEventListener("click", function () {
        if (state.fitFn) state.fitFn(true);
      });
    }
    if (els.exportSel) {
      els.exportSel.addEventListener("change", function () {
        var kind = els.exportSel.value;
        els.exportSel.value = "";
        if (kind) exportMap(kind);
      });
    }
    els.popout = document.getElementById("citationPopout");
    els.yearMin = document.getElementById("citationYearMin");
    els.yearMax = document.getElementById("citationYearMax");
    els.yearLabel = document.getElementById("citationYearLabel");
    els.categoryFilters = document.getElementById("citationCategoryFilters");
    els.categoryLegend = document.getElementById("citationCategoryLegend");
    state.graphUrl = root.getAttribute("data-graph") || "";
    state.runId = root.getAttribute("data-run-id") || "";
    state.watchName = root.getAttribute("data-watch-name") || "";
    state.compareRun = root.getAttribute("data-compare-run") || "";
    state.reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function onLargeViewClick(event) {
      if (event) event.stopPropagation();
      setLargeView(!state.largeView);
    }
    if (els.largeView) els.largeView.addEventListener("click", onLargeViewClick);
    if (els.popout) els.popout.addEventListener("click", onLargeViewClick);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && state.largeView) setLargeView(false);
    });

    root.querySelectorAll(".citation-filters .citation-filter").forEach(function (btn) {
      btn.addEventListener("click", function () {
        root.querySelectorAll(".citation-filters .citation-filter").forEach(function (other) {
          var on = other === btn;
          other.classList.toggle("is-active", on);
          other.setAttribute("aria-pressed", on ? "true" : "false");
        });
        state.direction = btn.getAttribute("data-direction") || "both";
        renderGraph();
      });
    });
    if (els.toggle) {
      els.toggle.addEventListener("change", function () {
        state.showOccasional = Boolean(els.toggle.checked);
        renderGraph();
      });
    }
    if (els.halo) {
      els.halo.addEventListener("change", function () {
        state.showHalo = Boolean(els.halo.checked);
        if (state.showHalo && state.selectedId) {
          loadHalo(state.selectedId);
        } else {
          state.ghostNodes = [];
          state.ghostEdges = [];
          renderGraph();
        }
      });
    }
    if (els.repair) {
      els.repair.addEventListener("click", repairLinks);
    }
    if (els.pathMode) {
      els.pathMode.addEventListener("click", function () {
        state.pathMode = !state.pathMode;
        state.pathFirst = "";
        state.pathEdges = [];
        els.pathMode.classList.toggle("is-active", state.pathMode);
        setStatus(
          state.pathMode
            ? "Path mode: click two papers on the map."
            : "Path mode off."
        );
        renderGraph();
      });
    }
    if (els.yearMin && els.yearMax) {
      els.yearMin.addEventListener("input", onYearScrub);
      els.yearMax.addEventListener("input", onYearScrub);
    }
    window.addEventListener("resize", function () {
      if (state.nodes.length) renderGraph();
    });

    setStatus("Loading citation map…");
    fetch("/discover/graph/meta", { credentials: "same-origin" })
      .then(readJson)
      .then(function (meta) {
        state.metaCollections = meta.collections || [];
        state.metaTags = meta.tags || [];
        state.editMode = meta.edit || "both";
      })
      .catch(function () {});
    fetch(graphFetchUrl(), { credentials: "same-origin" })
      .then(readJson)
      .then(function (graph) {
        adopt(graph);
        clearPanel();
      })
      .catch(function (error) {
        setStatus(error.message || "Could not load the citation map.");
      });
  }

  function graphFetchUrl() {
    var url = state.graphUrl;
    var extra = [];
    if (state.watchName) extra.push("watch_name=" + encodeURIComponent(state.watchName));
    if (state.compareRun) extra.push("compare_run=" + encodeURIComponent(state.compareRun));
    if (!extra.length) return url;
    return url + (url.indexOf("?") >= 0 ? "&" : "?") + extra.join("&");
  }

  function adopt(graph) {
    state.nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    state.edges = Array.isArray(graph.edges) ? graph.edges : [];
    state.layout = graph.layout === "similarity" ? "similarity" : "citation";
    state.similar =
      state.layout === "similarity" && graph.similar && typeof graph.similar === "object"
        ? graph.similar
        : null;
    state.lastGraph = graph;
    state.view = Object.assign(
      { color: "role", size_by: "citations", labels: "auto", fit: true, authors: 12, direction: "both" },
      graph.view && typeof graph.view === "object" ? graph.view : {}
    );
    state.authors = Array.isArray(graph.authors) ? graph.authors : [];
    var network = graph.author_network && typeof graph.author_network === "object" ? graph.author_network : {};
    state.authorNodes = (Array.isArray(network.nodes) ? network.nodes : []).map(authorAsNode);
    state.authorEdges = Array.isArray(network.edges) ? network.edges : [];
    state.authorTruncated = network.truncated || 0;
    if (state.viewRun !== graph.run_id) {
      state.viewRun = graph.run_id || "";
      state.mapView = state.view.default_view === "authors" && state.authorNodes.length ? "authors" : "papers";
    }
    if (state.mapView === "authors" && !state.authorNodes.length) state.mapView = "papers";
    syncViewButtons();
    if (state.layout === "similarity") {
      state.direction = "both";
    } else if (state.directionRun !== graph.run_id) {
      // A new map opens on the configured direction; later re-renders keep the user's pick.
      state.directionRun = graph.run_id || "";
      state.direction = ["refs", "cites"].indexOf(state.view.direction) >= 0 ? state.view.direction : "both";
      syncDirectionButtons();
    }
    var known = new Set(
      state.nodes.map(function (n) {
        return n.id;
      })
    );
    state.highlight.forEach(function (id) {
      if (!known.has(id)) state.highlight.delete(id);
    });
    if (!state.highlight.size) state.highlightLabel = "";
    applyLayoutControls();
    state.triage = Array.isArray(graph.triage) ? graph.triage : [];
    state.triageById = {};
    state.triage.forEach(function (row) {
      state.triageById[row.id] = row;
    });
    state.categoryLegend = Array.isArray(graph.category_legend)
      ? graph.category_legend
      : [];
    state.categoryById = {};
    state.categoryLegend.forEach(function (row) {
      state.categoryById[row.id] = row;
    });
    if (
      state.categoryFilter &&
      !state.categoryById[state.categoryFilter]
    ) {
      state.categoryFilter = "";
    }
    setupYearScrubber();
    renderThresholds(graph);
    renderCategoryControls();
    renderTriage();
    renderGraph();
    if (state.selectedId) {
      var still = state.nodes.filter(function (node) {
        return node.id === state.selectedId;
      })[0];
      if (still) showNode(still);
    }
  }

  function isSimilarity() {
    return state.layout === "similarity";
  }

  // The similarity map has no edge direction and cannot be expanded.
  function applyLayoutControls() {
    if (!els.root) return;
    var sim = isSimilarity();
    var people = isAuthorView();
    if (els.pathMode) {
      els.pathMode.textContent = people ? "Path between two people" : "Path between two papers";
    }
    // Toolbar CSS sets display, which beats the hidden attribute.
    [
      els.root.querySelector(".citation-filters"),
      els.repair,
      els.toggle && els.toggle.parentNode,
    ].forEach(function (el) {
      if (el) el.style.display = sim || people ? "none" : "";
    });
    [els.halo && els.halo.parentNode, els.categoryFilters, els.categoryLegend].forEach(function (el) {
      if (el) el.style.display = people ? "none" : "";
    });
    var byYear = state.view.color === "year";
    var byCategory = state.view.color === "category";
    var show = function (id, on) {
      var el = document.getElementById(id);
      if (el) el.style.display = on ? "" : "none";
    };
    show("citationLedeSimilar", sim);
    show("citationLedeCitation", !sim);
    show("citationYearLegend", byYear && !people);
    show("citationRoleLegend", !byYear && !byCategory && !people);
    show("citationAuthorLegend", people);
    show("citationLedeAuthors", people);
    if (people) {
      show("citationLedeSimilar", false);
      show("citationLedeCitation", false);
    }
  }

  function isAuthorView() {
    return state.mapView === "authors";
  }

  function syncViewButtons() {
    if (!els.root) return;
    els.root.querySelectorAll("[data-map-view]").forEach(function (btn) {
      var on = btn.getAttribute("data-map-view") === state.mapView;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      if (btn.getAttribute("data-map-view") === "authors") {
        btn.disabled = !state.authorNodes.length;
        btn.title = state.authorNodes.length ? "" : "No author data on this map";
      }
    });
  }

  function setMapView(view, opts) {
    var next = view === "authors" && state.authorNodes.length ? "authors" : "papers";
    if (next === state.mapView && !(opts && opts.force)) return;
    state.mapView = next;
    state.pathEdges = [];
    state.pathFirst = "";
    state.pathMode = false;
    if (els.pathMode) els.pathMode.classList.remove("is-active");
    var keep = opts && opts.highlight;
    state.highlight = new Set(keep || []);
    state.highlightLabel = keep ? (opts.label || "") : "";
    if (els.search) els.search.value = "";
    state.selectedId = (opts && opts.select) || "";
    syncViewButtons();
    applyLayoutControls();
    renderThresholds(state.lastGraph || {});
    renderTriage();
    renderGraph();
    renderHighlightNote();
    var picked = state.selectedId
      ? activeNodes().filter(function (n) {
          return n.id === state.selectedId;
        })[0]
      : null;
    if (picked && !isAuthorView() && !isDrawn(picked)) {
      // The paper is behind a filter; lift the filters so it can be shown.
      revealPaper(picked);
      renderGraph();
    }
    if (picked) {
      if (isAuthorView()) showAuthor(picked);
      else showNode(picked);
      window.setTimeout(function () {
        if (state.focusFn) state.focusFn(picked.id);
      }, 650);
    } else {
      clearPanel();
    }
  }

  function isDrawn(n) {
    return visibleNodes().some(function (v) {
      return v.id === n.id;
    });
  }

  function revealPaper(n) {
    if (n.occasional && !state.showOccasional) {
      state.showOccasional = true;
      if (els.toggle) els.toggle.checked = true;
    }
    if (state.categoryFilter) {
      state.categoryFilter = "";
      renderCategoryControls();
    }
    if (n.year && (n.year < state.yearLo || n.year > state.yearHi)) {
      state.yearLo = Math.min(state.yearLo, n.year);
      state.yearHi = Math.max(state.yearHi, n.year);
      if (els.yearMin) els.yearMin.value = state.yearLo;
      if (els.yearMax) els.yearMax.value = state.yearHi;
      updateYearLabel();
    }
    if (state.direction !== "both" && !isDrawn(n)) {
      state.direction = "both";
      syncDirectionButtons();
    }
  }

  function authorAsNode(a) {
    return {
      id: a.id,
      kind: "author",
      key: a.key,
      title: a.name || a.key,
      name: a.name || a.key,
      openalex: a.openalex || "",
      orcid: a.orcid || "",
      count: a.count || 0,
      cited_by_count: a.citations || 0,
      node_ids: Array.isArray(a.node_ids) ? a.node_ids : [],
      seed: !!a.seed,
      followed: !!a.followed,
      library_papers: a.in_library || 0,
      year: a.year_to || null,
      year_from: a.year_from || null,
      year_to: a.year_to || null,
      coauthors: a.coauthors || 0,
      rank: (a.count || 0) * 1000000 + (a.citations || 0),
    };
  }

  function activeNodes() {
    return isAuthorView() ? state.authorNodes : state.nodes;
  }

  function activeEdges() {
    return isAuthorView() ? state.authorEdges : state.edges;
  }

  function syncDirectionButtons() {
    if (!els.root) return;
    els.root.querySelectorAll(".citation-filters .citation-filter").forEach(function (btn) {
      var on = (btn.getAttribute("data-direction") || "both") === state.direction;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function renderCategoryControls() {
    if (!els.categoryFilters || !els.categoryLegend) return;
    var legend = state.categoryLegend;
    if (!legend.length) {
      els.categoryFilters.hidden = true;
      els.categoryFilters.innerHTML = "";
      els.categoryLegend.hidden = true;
      els.categoryLegend.innerHTML = "";
      return;
    }
    els.categoryFilters.hidden = false;
    var html =
      '<button type="button" class="citation-filter citation-category-chip' +
      (state.categoryFilter ? "" : " is-active") +
      '" data-category="" aria-pressed="' +
      (state.categoryFilter ? "false" : "true") +
      '">All study types</button>';
    legend.forEach(function (row) {
      var on = state.categoryFilter === row.id;
      html +=
        '<button type="button" class="citation-filter citation-category-chip' +
        (on ? " is-active" : "") +
        '" data-category="' +
        escapeAttr(row.id) +
        '" aria-pressed="' +
        (on ? "true" : "false") +
        '"><span class="citation-swatch citation-category-swatch" style="background:' +
        escapeAttr(row.color || "#5c6b7a") +
        '" aria-hidden="true"></span>' +
        escapeHtml(row.label || row.id) +
        "</button>";
    });
    els.categoryFilters.innerHTML = html;
    els.categoryFilters.querySelectorAll("[data-category]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.categoryFilter = btn.getAttribute("data-category") || "";
        renderCategoryControls();
        renderGraph();
      });
    });
    els.categoryLegend.hidden = false;
    els.categoryLegend.innerHTML = legend
      .map(function (row) {
        return (
          "<li><span class=\"citation-swatch citation-category-swatch\" style=\"background:" +
          escapeAttr(row.color || "#5c6b7a") +
          '" aria-hidden="true"></span> ' +
          escapeHtml(row.label || row.id) +
          "</li>"
        );
      })
      .join("");
  }

  function renderThresholds(graph) {
    if (!els.thresholds) return;
    if (isAuthorView()) {
      var linksBy =
        state.view.author_links === "coauthor"
          ? "linked by co-authorship only"
          : "linked by co-authorship and by their papers' links";
      els.thresholds.textContent =
        linksBy.charAt(0).toUpperCase() +
        linksBy.slice(1) +
        (state.authorTruncated ? " · " + state.authorTruncated + " more authors not drawn (Settings → Maps)" : "");
      appendGraphWarnings(graph);
      return;
    }
    if (isSimilarity()) {
      renderSimilarReport();
      appendGraphWarnings(graph);
      return;
    }
    var t = graph.thresholds || graph.threshold || {};
    var recent = t.recent_from_year || t.recent_from_year;
    var cited = t.highly_cited;
    if (recent && cited) {
      els.thresholds.textContent =
        "Highly cited: ≥ " +
        cited +
        " · Recent: " +
        recent +
        " and later";
    } else {
      els.thresholds.textContent = "";
    }
    appendGraphWarnings(graph);
  }

  function appendGraphWarnings(graph) {
    var warnings = graph && Array.isArray(graph.warnings) ? graph.warnings : [];
    warnings.forEach(function (w) {
      els.thresholds.insertAdjacentHTML(
        "beforeend",
        '<br><span class="citation-warning">⚠ ' + escapeHtml(w) + "</span>"
      );
    });
  }

  var SOURCE_LABEL = {
    api: "live OpenAlex API",
    store: "your OpenAlex store (no live API)",
    "store+api": "your OpenAlex store, then the live API",
  };

  function renderSimilarReport() {
    var report = state.similar || {};
    var bits = [];
    if (report.source) bits.push("Source: " + (SOURCE_LABEL[report.source] || report.source));
    if (typeof report.pool_size === "number") bits.push(report.pool_size + " papers scored");
    if (typeof report.api_calls === "number") bits.push(report.api_calls + " API calls");
    if (report.hidden_in_library) bits.push(report.hidden_in_library + " library papers hidden");
    if (state.view.color === "year") bits.push("Colour: lighter is older");
    var warnings = Array.isArray(report.warnings) ? report.warnings : [];
    els.thresholds.innerHTML =
      escapeHtml(bits.join(" · ")) +
      warnings
        .map(function (w) {
          return '<br><span class="citation-warning">⚠ ' + escapeHtml(w) + "</span>";
        })
        .join("");
  }

  function yearFill(year) {
    if (!year) return ROLE_FILL.other;
    var years = state.nodes
      .map(function (n) {
        return n.year;
      })
      .filter(Boolean);
    var lo = Math.min.apply(null, years);
    var hi = Math.max.apply(null, years);
    var t = hi > lo ? (year - lo) / (hi - lo) : 1;
    return d3.interpolateRgb("#c9d6e3", "#1d3557")(Math.max(0, Math.min(1, t)));
  }

  function nodeFill(d) {
    if (d.kind === "author") {
      if (d.followed) return "#2f6f4e";
      if (d.seed) return "#c46a2a";
      var top = d3.max(state.authorNodes, function (a) { return a.count || 1; }) || 1;
      return d3.interpolateRgb("#9fb3c8", "#1d3557")(Math.min(1, (d.count || 1) / top));
    }
    if (state.view.color === "year") return yearFill(d.year);
    if (state.view.color === "category") {
      var cats = Array.isArray(d.categories) ? d.categories : [];
      var meta = cats.length ? state.categoryById[cats[0]] : null;
      return (meta && meta.color) || "#b8c1cb";
    }
    return ROLE_FILL[d.role] || ROLE_FILL.other;
  }

  // Start a new Similar map from a paper (map node or a prior/derivative row).
  function openSimilarMap(nodeId) {
    if (!nodeId || !/^(doi|openalex):/.test(nodeId)) {
      setStatus("This paper has no DOI or OpenAlex id to map from.");
      return;
    }
    var form = document.createElement("form");
    form.method = "post";
    form.action = "/discover/explore";
    var fields = [
      ["node_id", nodeId],
      ["map", "similar"],
    ];
    // Keep this map's own options (years, depth, …) for the next map.
    var current = (state.similar && state.similar.settings) || null;
    if (current) {
      ["nodes", "coupling_weight", "pool", "year_from", "year_to", "hide_in_library", "source"].forEach(
        function (key) {
          if (!(key in current)) return;
          var value = current[key];
          if (value === null || value === undefined) value = "";
          else if (value === true) value = "1";
          else if (value === false) value = "0";
          fields.push([key, String(value)]);
        }
      );
    }
    fields.forEach(function (pair) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = pair[0];
      input.value = pair[1];
      form.appendChild(input);
    });
    document.body.appendChild(form);
    setStatus("Building a Similar map from that paper…");
    form.submit();
  }

  function extrasHtml(title, hint, items, unit) {
    if (!Array.isArray(items) || !items.length) return "";
    return (
      '<div class="citation-extras"><h4>' +
      escapeHtml(title) +
      "</h4>" +
      '<p class="citation-meta">' +
      escapeHtml(hint) +
      "</p><ol>" +
      items
        .map(function (item) {
          var label =
            escapeHtml(item.title || item.id) +
            (item.year ? " (" + item.year + ")" : "") +
            ' <span class="citation-meta">· ' +
            (item.count || 0) +
            " " +
            unit +
            "</span>";
          var link = item.doi
            ? '<a href="https://doi.org/' +
              escapeAttr(item.doi) +
              '" rel="noopener noreferrer">' +
              label +
              "</a>"
            : label;
          return (
            "<li>" +
            link +
            ' <button type="button" class="secondary citation-mini" data-similar-map="' +
            escapeAttr(item.id) +
            '">Map this</button></li>'
          );
        })
        .join("") +
      "</ol></div>"
    );
  }

  function bindSimilarButtons(rootEl) {
    rootEl.querySelectorAll("[data-similar-map]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openSimilarMap(btn.getAttribute("data-similar-map") || "");
      });
    });
  }

  function renderTriage() {
    if (!els.triage) return;
    if (isAuthorView()) {
      var top = state.authorNodes.slice(0, 12);
      els.triage.innerHTML =
        '<h3>Most papers here</h3><ol class="citation-triage-list">' +
        top
          .map(function (a) {
            return (
              '<li><button type="button" class="citation-triage-btn" data-id="' +
              escapeAttr(a.id) +
              '">' +
              escapeHtml(a.name) +
              '</button><span class="citation-meta">' +
              a.count +
              (a.count === 1 ? " paper" : " papers") +
              (a.seed ? " · wrote the starting paper" : "") +
              "</span></li>"
            );
          })
          .join("") +
        "</ol>";
      els.triage.querySelectorAll(".citation-triage-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var hit = state.authorNodes.filter(function (n) {
            return n.id === btn.getAttribute("data-id");
          })[0];
          if (hit) {
            state.selectedId = hit.id;
            showAuthor(hit);
            if (state.focusFn) state.focusFn(hit.id);
          }
        });
      });
      return;
    }
    if (!state.triage.length) {
      els.triage.innerHTML = "";
      return;
    }
    var html =
      '<h3>Read first</h3><ol class="citation-triage-list">';
    state.triage.slice(0, 12).forEach(function (row) {
      var node = state.nodes.filter(function (n) {
        return n.id === row.id;
      })[0];
      var title = node ? shortTitle(node.title) : row.id;
      html +=
        '<li><button type="button" class="citation-triage-btn" data-id="' +
        escapeAttr(row.id) +
        '">' +
        escapeHtml(title) +
        '</button><span class="citation-meta">' +
        escapeHtml(row.reason || "") +
        "</span></li>";
    });
    html += "</ol>";
    els.triage.innerHTML = html;
    els.triage.querySelectorAll(".citation-triage-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-id") || "";
        var node = state.nodes.filter(function (n) {
          return n.id === id;
        })[0];
        if (node) {
          state.selectedId = id;
          showNode(node);
        }
      });
    });
  }

  function setupYearScrubber() {
    var years = state.nodes
      .map(function (n) {
        return n.year;
      })
      .filter(function (y) {
        return typeof y === "number" && y > 0;
      });
    if (!years.length || !els.yearMin || !els.yearMax) return;
    var lo = Math.min.apply(null, years);
    var hi = Math.max.apply(null, years);
    state.yearMin = lo;
    state.yearMax = hi;
    state.yearLo = lo;
    state.yearHi = hi;
    els.yearMin.min = String(lo);
    els.yearMin.max = String(hi);
    els.yearMin.value = String(lo);
    els.yearMax.min = String(lo);
    els.yearMax.max = String(hi);
    els.yearMax.value = String(hi);
    updateYearLabel();
  }

  function onYearScrub() {
    if (!els.yearMin || !els.yearMax) return;
    state.yearLo = parseInt(els.yearMin.value, 10);
    state.yearHi = parseInt(els.yearMax.value, 10);
    if (state.yearLo > state.yearHi) {
      var tmp = state.yearLo;
      state.yearLo = state.yearHi;
      state.yearHi = tmp;
      els.yearMin.value = String(state.yearLo);
      els.yearMax.value = String(state.yearHi);
    }
    updateYearLabel();
    renderGraph();
  }

  function updateYearLabel() {
    if (!els.yearLabel) return;
    if (state.yearLo <= state.yearMin && state.yearHi >= state.yearMax) {
      els.yearLabel.textContent = "all years";
    } else {
      els.yearLabel.textContent = state.yearLo + " – " + state.yearHi;
    }
  }

  function setStatus(text) {
    if (els.status) els.status.textContent = text || "";
  }

  function setLargeView(on) {
    state.largeView = Boolean(on);
    if (els.root) els.root.classList.toggle("is-large", state.largeView);
    document.body.classList.toggle("citation-large-open", state.largeView);
    if (els.largeView) {
      els.largeView.textContent = state.largeView ? "Exit large view" : "Large view";
      els.largeView.setAttribute("aria-pressed", state.largeView ? "true" : "false");
      els.largeView.classList.toggle("is-active", state.largeView);
    }
    if (els.popout) {
      els.popout.setAttribute(
        "aria-label",
        state.largeView ? "Exit large view" : "Open large view"
      );
      els.popout.title = state.largeView ? "Exit large view" : "Open large view";
    }
    window.requestAnimationFrame(function () {
      if (state.nodes.length) renderGraph();
    });
  }

  function visibleNodes() {
    if (isAuthorView()) {
      return state.authorNodes.filter(function (a) {
        if (a.seed || (!a.year_from && !a.year_to)) return true;
        return (a.year_to || 0) >= state.yearLo && (a.year_from || 9999) <= state.yearHi;
      });
    }
    return state.nodes.filter(function (node) {
      if (!isSimilarity() && !state.showOccasional && node.occasional && !node.seed) return false;
      if (!node.seed && node.year) {
        if (node.year < state.yearLo || node.year > state.yearHi) return false;
      }
      if (state.categoryFilter) {
        var cats = Array.isArray(node.categories) ? node.categories : [];
        if (cats.indexOf(state.categoryFilter) < 0) return false;
      }
      if (state.direction === "both" || node.seed) return true;
      return state.edges.some(function (edge) {
        return (
          edge.direction === state.direction &&
          (edge.source === node.id || edge.target === node.id)
        );
      });
    });
  }

  function visibleEdges(ids) {
    if (isAuthorView()) {
      return state.authorEdges.filter(function (edge) {
        return ids.has(edge.source) && ids.has(edge.target);
      });
    }
    return state.edges.filter(function (edge) {
      if (!ids.has(edge.source) || !ids.has(edge.target)) return false;
      if (state.direction === "both") return true;
      return edge.direction === state.direction;
    });
  }

  function renderGraph() {
    var papers = visibleNodes();
    var ghostPapers = state.showHalo && !isAuthorView() ? state.ghostNodes : [];
    var ids = new Set(
      papers
        .concat(ghostPapers)
        .map(function (paper) {
          return paper.id;
        })
    );
    var edges = visibleEdges(ids).concat(state.showHalo && !isAuthorView() ? state.ghostEdges : []);
    var hidden = isSimilarity() || isAuthorView()
      ? 0
      : state.nodes.filter(function (paper) {
          return paper.occasional && !paper.seed;
        }).length;

    if (!papers.length && !ghostPapers.length) {
      els.svg.selectAll("*").remove();
      setStatus("No papers to map yet. Search a topic, then come back.");
      return;
    }
    var linkNote =
      papers.length +
      " papers · " +
      edges.length +
      " links" +
      (state.showOccasional || !hidden ? "" : " (" + hidden + " other hidden)");
    if (isAuthorView()) {
      linkNote =
        papers.length +
        " authors · " +
        edges.length +
        " links · solid lines join co-authors, dashed lines join authors whose papers are linked on this map" +
        (state.authorTruncated ? " (" + state.authorTruncated + " more authors not drawn)" : "") +
        ".";
    } else if (isSimilarity()) {
      var origin = papers.filter(function (paper) {
        return paper.seed;
      })[0];
      linkNote =
        papers.length +
        " papers similar to " +
        shortTitle(origin ? origin.title : "the origin") +
        " · closer means more shared citations and references. Click a paper to trace its path to the origin.";
    } else if (!edges.length && papers.length > 1) {
      var allSeeds = papers.every(function (paper) {
        return paper.seed;
      });
      linkNote += allSeeds
        ? " — search hit list has no citation hops yet; expand a paper to draw links"
        : " — expand a paper to pull who it cites or who cites it";
    }
    setStatus(linkNote);

    var wrap = els.root.querySelector(".citation-canvas-wrap");
    if (wrap && wrap.clientWidth === 0) return;
    var width = Math.max(wrap ? wrap.clientWidth : 640, 320);
    var height = Math.max(wrap ? wrap.clientHeight : 480, 360);
    els.svg.attr("viewBox", "0 0 " + width + " " + height).attr("width", width).attr("height", height);
    els.svg.selectAll("*").remove();

    var defs = els.svg.append("defs");
    defs
      .append("marker")
      .attr("id", "citation-arrow")
      .attr("viewBox", "0 -4 8 8")
      .attr("refX", 12)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L8,0L0,4")
      .attr("fill", "#5c6b73");

    var maxCited =
      d3.max(papers.concat(ghostPapers), function (paper) {
        return paper.cited_by_count || 1;
      }) || 1;
    var radiusScale = d3.scaleSqrt().domain([0, maxCited]).range([7, 26]);
    var maxCount =
      d3.max(papers, function (p) {
        return p.count || 1;
      }) || 1;
    var countScale = d3.scaleSqrt().domain([0, maxCount]).range([7, 24]);
    function radius(paper) {
      if (state.view.size_by === "uniform") return paper.seed ? 13 : 10;
      if (paper.kind === "author") return countScale(paper.count || 0);
      return radiusScale(paper.cited_by_count || 0);
    }

    var crowded = papers.length > 35;
    var nodes = papers.concat(ghostPapers).map(function (paper) {
      return Object.assign({}, paper);
    });
    var nodeById = new Map(
      nodes.map(function (node) {
        return [node.id, node];
      })
    );
    var links = edges
      .map(function (edge) {
        return Object.assign({}, edge, {
          source: nodeById.get(edge.source),
          target: nodeById.get(edge.target),
        });
      })
      .filter(function (edge) {
        return edge.source && edge.target;
      });

    var pathKeys = new Set();
    state.pathEdges.forEach(function (edge) {
      pathKeys.add(edge.source + "|" + edge.target + "|" + edge.direction);
      pathKeys.add(edge.target + "|" + edge.source + "|" + edge.direction);
    });

    var seeds = nodes.filter(function (node) {
      return node.seed;
    });
    var labelCap =
      state.view.labels === "all"
        ? nodes.length
        : state.view.labels === "seeds" || state.view.labels === "none"
          ? 0
          : papers.length > 40
            ? 8
            : papers.length > 20
              ? 12
              : 18;
    var labeledIds = new Set(
      nodes
        .slice()
        .sort(function (a, b) {
          var rb = b.rank !== undefined ? b.rank : b.cited_by_count || 0;
          var ra = a.rank !== undefined ? a.rank : a.cited_by_count || 0;
          return rb - ra;
        })
        .slice(0, labelCap)
        .map(function (node) {
          return node.id;
        })
    );
    if (state.view.labels !== "none") {
      seeds.forEach(function (node) {
        labeledIds.add(node.id);
      });
    }
    state.userZoomed = false;

    function linkStroke(d) {
      if (d.direction === "coauthor" || d.direction === "linked") {
        var akey = d.source.id + "|" + d.target.id + "|" + d.direction;
        if (pathKeys.size && pathKeys.has(akey)) return "#c46a2a";
        return d.direction === "coauthor" ? "#3d5a80" : "#8d99a6";
      }
      if (d.direction === "similar") {
        var key = d.source.id + "|" + d.target.id + "|" + d.direction;
        return pathKeys.size && pathKeys.has(key) ? "#c46a2a" : "#8d99a6";
      }
      return d.direction === "cites" ? "#3d5a80" : "#c46a2a";
    }

    function linkWidth(d) {
      var key = d.source.id + "|" + d.target.id + "|" + d.direction;
      var onPath = pathKeys.size && pathKeys.has(key);
      if (d.direction === "similar" || d.direction === "coauthor" || d.direction === "linked") {
        return onPath ? 3.4 : 0.8 + 2.4 * (d.weight || 0);
      }
      return onPath ? 2.4 : 1.4;
    }

    var g = els.svg.append("g").attr("class", "citation-zoom");
    var zoom = d3
      .zoom()
      .scaleExtent([0.35, 4])
      .on("zoom", function (event) {
        g.attr("transform", event.transform);
        if (event.sourceEvent) state.userZoomed = true;
      });
    els.svg.call(zoom).on("dblclick.zoom", null);

    var link = g
      .append("g")
      .attr("class", "links")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", linkStroke)
      .attr("stroke-opacity", function (d) {
        var key = d.source.id + "|" + d.target.id + "|" + d.direction;
        if (pathKeys.size && pathKeys.has(key)) return 0.95;
        return crowded ? 0.35 : 0.55;
      })
      .attr("stroke-width", linkWidth)
      .attr("stroke-dasharray", function (d) {
        if (d.direction === "linked") return "4 3";
        return d.source.ghost || d.target.ghost ? "4 3" : null;
      })
      .attr("marker-end", function (d) {
        return d.direction === "refs" || d.direction === "cites" ? "url(#citation-arrow)" : null;
      })
      .style("cursor", "pointer")
      .on("click", function (event, d) {
        event.stopPropagation();
        showEdge(d);
      });

    var node = g
      .append("g")
      .attr("class", "nodes")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .style("cursor", "pointer")
      .call(
        d3
          .drag()
          .on("start", function (event, d) {
            if (!event.active && state.simulation) state.simulation.alphaTarget(0.2).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", function (event, d) {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", function (event, d) {
            if (!event.active && state.simulation) state.simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      )
      .attr("tabindex", 0)
      .attr("role", "button")
      .attr("aria-label", function (d) {
        return (d.title || "Untitled") + (d.year ? ", " + d.year : "") + (d.seed ? ", starting paper" : "");
      })
      .on("click", function (event, d) {
        event.stopPropagation();
        activateNode(d);
      })
      .on("keydown", function (event, d) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          activateNode(d);
        }
      })
      .on("focus", function (event, d) {
        setFocus(d.id);
      })
      .on("blur", function () {
        setFocus(null);
      })
      .on("mouseenter", function (event, d) {
        setFocus(d.id);
      })
      .on("mouseleave", function () {
        setFocus(null);
      });

    node
      .append("circle")
      .attr("r", radius)
      .attr("fill", nodeFill)
      .attr("stroke", function (d) {
        if (d.ghost) return "#101820";
        return d.in_library ? "#101820" : "#f7f1e8";
      })
      .attr("stroke-width", function (d) {
        return d.in_library || d.ghost ? 2.5 : 1;
      })
      .attr("stroke-dasharray", function (d) {
        return d.ghost ? "3 2" : null;
      })
      .style("opacity", function (d) {
        if (d.keep === false) return 0.35;
        if (d.watch_seen) return 0.45;
        return 1;
      });

    node
      .append("text")
      .attr("class", "citation-lib-badge")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("font-size", "8px")
      .attr("font-weight", "700")
      .attr("fill", "#f7f1e8")
      .attr("pointer-events", "none")
      .text(function (d) {
        if (d.kind === "author") return d.count > 1 ? String(d.count) : "";
        if (d.ghost) return "LIB";
        if (d.in_library) return "LIB";
        if (d.staged) return "…";
        return "";
      });

    node.each(function (d) {
      var cats = Array.isArray(d.categories) ? d.categories.slice(0, 3) : [];
      if (!cats.length || d.ghost) return;
      var g = d3.select(this);
      var r = radius(d) + 3;
      cats.forEach(function (cid, index) {
        var meta = state.categoryById[cid] || {};
        var color = meta.color || "#5c6b7a";
        var start = -Math.PI / 2 + index * ((2 * Math.PI) / Math.max(cats.length, 1));
        var end = start + (2 * Math.PI) / Math.max(cats.length, 1) - 0.12;
        var arc =
          "M " +
          Math.cos(start) * r +
          " " +
          Math.sin(start) * r +
          " A " +
          r +
          " " +
          r +
          " 0 0 1 " +
          Math.cos(end) * r +
          " " +
          Math.sin(end) * r;
        g.append("path")
          .attr("d", arc)
          .attr("fill", "none")
          .attr("stroke", color)
          .attr("stroke-width", 2.5)
          .attr("pointer-events", "none");
      });
    });

    node.append("title").text(function (d) {
      if (d.kind === "author") {
        var abits = [d.name, d.count + (d.count === 1 ? " paper" : " papers") + " on this map", d.cited_by_count + " citations"];
        if (d.year_from) abits.push(d.year_from === d.year_to ? String(d.year_from) : d.year_from + "–" + d.year_to);
        if (d.seed) abits.push("wrote the starting paper");
        if (d.followed) abits.push("following");
        return abits.join(" · ");
      }
      var bits = [
        d.title || "Untitled",
        d.year || "n.d.",
        (d.cited_by_count || 0) + " citations",
      ];
      var cats = Array.isArray(d.categories) ? d.categories : [];
      if (cats.length) {
        bits.push(
          cats
            .map(function (cid) {
              return (state.categoryById[cid] && state.categoryById[cid].label) || cid;
            })
            .join(", ")
        );
      }
      if (d.in_library) bits.push("in your library");
      if (d.staged) bits.push("staged edits");
      if (d.watch_new) bits.push("new since watch baseline");
      if (d.compare_new) bits.push("not in compare run");
      return bits.join(" · ");
    });

    var labels = g
      .append("g")
      .attr("class", "node-labels")
      .selectAll("text")
      .data(nodes)
      .join("text")
      .text(function (d) {
        var label = shortTitle(d.title);
        if (d.watch_new) label += " *";
        return label;
      })
      .attr("y", function (d) {
        return radius(d) + 14;
      })
      .attr("text-anchor", "middle")
      .attr("font-size", "11px")
      .attr("fill", "#101820")
      .attr("stroke", "#f7f1e8")
      .attr("stroke-width", 3)
      .attr("paint-order", "stroke")
      .attr("pointer-events", "none")
      .style("opacity", function (d) {
        return labeledIds.has(d.id) ? 1 : 0;
      });

    function setFocus(focusId) {
      if (!focusId) {
        node.style("opacity", baseOpacity);
        link.attr("stroke-opacity", function (d) {
          var key = d.source.id + "|" + d.target.id + "|" + d.direction;
          if (pathKeys.size && pathKeys.has(key)) return 0.95;
          return crowded ? 0.35 : 0.55;
        });
        labels.style("opacity", function (d) {
          if (state.highlight.size) return state.highlight.has(d.id) ? 1 : 0;
          return labeledIds.has(d.id) ? 1 : 0;
        });
        return;
      }
      var connected = new Set([focusId]);
      links.forEach(function (edge) {
        if (edge.source.id === focusId || edge.target.id === focusId) {
          connected.add(edge.source.id);
          connected.add(edge.target.id);
        }
      });
      node.style("opacity", function (d) {
        return connected.has(d.id) ? 1 : 0.12;
      });
      link.attr("stroke-opacity", function (d) {
        var key = d.source.id + "|" + d.target.id + "|" + d.direction;
        if (pathKeys.size && pathKeys.has(key)) return 0.95;
        return d.source.id === focusId || d.target.id === focusId ? 0.9 : 0.04;
      });
      labels.style("opacity", function (d) {
        return connected.has(d.id) ? 1 : 0;
      });
    }

    function baseOpacity(d) {
      if (state.highlight.size) return state.highlight.has(d.id) ? 1 : 0.12;
      if (d.keep === false) return 0.35;
      if (d.watch_seen) return 0.45;
      return 1;
    }

    state.restyle = function () {
      setFocus(null);
    };

    function fitView(animate) {
      var placed = nodes.filter(function (n) {
        return typeof n.x === "number" && !isNaN(n.x);
      });
      if (!placed.length) return;
      var x0 = d3.min(placed, function (n) { return n.x - radius(n); });
      var x1 = d3.max(placed, function (n) { return n.x + radius(n); });
      var y0 = d3.min(placed, function (n) { return n.y - radius(n); });
      var y1 = d3.max(placed, function (n) { return n.y + radius(n) + 18; });
      var w = Math.max(x1 - x0, 1);
      var h = Math.max(y1 - y0, 1);
      var k = Math.max(0.35, Math.min(2.2, 0.9 * Math.min(width / w, height / h)));
      var t = d3.zoomIdentity
        .translate(width / 2 - k * (x0 + w / 2), height / 2 - k * (y0 + h / 2))
        .scale(k);
      if (animate && !state.reduceMotion) els.svg.transition().duration(450).call(zoom.transform, t);
      else els.svg.call(zoom.transform, t);
    }
    state.fitFn = fitView;

    state.focusFn = function (id) {
      var n = nodes.filter(function (x) {
        return x.id === id;
      })[0];
      if (!n || typeof n.x !== "number") return;
      var current = d3.zoomTransform(els.svg.node());
      var k = Math.max(current.k, 1.2);
      var t = d3.zoomIdentity.translate(width / 2 - k * n.x, height / 2 - k * n.y).scale(k);
      if (state.reduceMotion) els.svg.call(zoom.transform, t);
      else els.svg.transition().duration(400).call(zoom.transform, t);
    };

    // Highlight a path without re-running the layout.
    state.applyPath = function (pathEdges) {
      state.pathEdges = pathEdges || [];
      pathKeys.clear();
      state.pathEdges.forEach(function (edge) {
        pathKeys.add(edge.source + "|" + edge.target + "|" + edge.direction);
        pathKeys.add(edge.target + "|" + edge.source + "|" + edge.direction);
      });
      link.attr("stroke", linkStroke).attr("stroke-width", linkWidth);
      setFocus(null);
    };

    els.svg.on("click", function () {
      state.selectedId = "";
      if (isSimilarity() && state.applyPath) state.applyPath([]);
      clearPanel();
    });

    if (state.simulation) state.simulation.stop();
    state.simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink(links)
          .id(function (d) {
            return d.id;
          })
          .distance(function (d) {
            if (d.direction === "similar") return 40 + (1 - (d.weight || 0)) * 140;
            if (d.direction === "coauthor" || d.direction === "linked") return 45 + (1 - (d.weight || 0)) * 120;
            return 70;
          })
          .strength(function (d) {
            if (d.direction === "similar" || d.direction === "coauthor" || d.direction === "linked") {
              return 0.15 + 0.85 * (d.weight || 0);
            }
            return 0.35;
          })
      )
      .force("charge", d3.forceManyBody().strength(crowded ? -220 : -160))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force(
        "collision",
        d3.forceCollide().radius(function (d) {
          return radius(d) + 10;
        })
      );

    if (seeds.length === 1) {
      seeds[0].fx = width / 2;
      seeds[0].fy = height / 2;
    }

    state.simulation.on("tick", function () {
      // Fit once the layout has mostly settled, not only when it fully stops.
      if (!fitted && state.view.fit && !state.userZoomed && state.simulation.alpha() < 0.12) {
        fitted = true;
        window.requestAnimationFrame(function () {
          fitView(true);
        });
      }
      link
        .attr("x1", function (d) {
          return d.source.x;
        })
        .attr("y1", function (d) {
          return d.source.y;
        })
        .attr("x2", function (d) {
          return d.target.x;
        })
        .attr("y2", function (d) {
          return d.target.y;
        });
      node.attr("transform", function (d) {
        return "translate(" + d.x + "," + d.y + ")";
      });
      labels.attr("transform", function (d) {
        return "translate(" + d.x + "," + d.y + ")";
      });
    });

    var fitted = false;
    state.simulation.on("end.fit", function () {
      if (state.view.fit && !state.userZoomed && !fitted) fitView(true);
      fitted = true;
    });

    if (state.reduceMotion) {
      state.simulation.stop();
      for (var i = 0; i < 200; i += 1) state.simulation.tick();
      state.simulation.on("tick")();
      if (state.view.fit) fitView(false);
    }
    setFocus(null);
  }

  function activateNode(d) {
    if (state.pathMode) {
      pickPathNode(d);
      return;
    }
    state.selectedId = d.id;
    if (d.kind === "author") {
      showAuthor(d);
      return;
    }
    if (isSimilarity() && state.applyPath) state.applyPath(d.origin_path || []);
    showNode(d);
    if (state.showHalo) loadHalo(d.id);
  }

  // --- highlight, search, authors, export ------------------------------------

  function setHighlight(ids, label) {
    state.highlight = new Set(ids || []);
    state.highlightLabel = state.highlight.size ? label || "" : "";
    if (state.restyle) state.restyle();
    renderHighlightNote();
  }

  function renderHighlightNote() {
    if (!els.highlightNote) return;
    if (!state.highlight.size) {
      els.highlightNote.hidden = true;
      els.highlightNote.innerHTML = "";
      return;
    }
    els.highlightNote.hidden = false;
    els.highlightNote.innerHTML =
      escapeHtml(
        state.highlight.size + " highlighted" + (state.highlightLabel ? ": " + state.highlightLabel : "")
      ) + ' <button type="button" class="secondary citation-mini" data-clear-highlight="1">Clear</button>';
    els.highlightNote.querySelector("[data-clear-highlight]").addEventListener("click", function () {
      if (els.search) els.search.value = "";
      setHighlight([], "");
    });
  }

  function nodeMatches(n, q) {
    if ((n.title || "").toLowerCase().indexOf(q) >= 0) return true;
    if ((n.doi || "").toLowerCase().indexOf(q) >= 0) return true;
    var names = Array.isArray(n.authors) ? n.authors : [];
    for (var i = 0; i < names.length; i += 1) {
      if (String(names[i]).toLowerCase().indexOf(q) >= 0) return true;
    }
    return false;
  }

  function onSearch() {
    var q = (els.search.value || "").trim().toLowerCase();
    if (q.length < 2) {
      setHighlight([], "");
      return;
    }
    var ids = activeNodes()
      .filter(function (n) {
        return nodeMatches(n, q);
      })
      .map(function (n) {
        return n.id;
      });
    setHighlight(ids, "“" + els.search.value.trim() + "”");
    if (!ids.length) setStatus("Nothing on this map matches “" + els.search.value.trim() + "”.");
  }

  function onSearchKey(event) {
    if (event.key === "Escape") {
      els.search.value = "";
      setHighlight([], "");
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault();
    var first = activeNodes().filter(function (n) {
      return state.highlight.has(n.id);
    })[0];
    if (!first) return;
    state.selectedId = first.id;
    if (first.kind === "author") showAuthor(first);
    else showNode(first);
    if (state.focusFn) state.focusFn(first.id);
  }

  function authorKeyNodes(key) {
    return state.nodes
      .filter(function (n) {
        return Array.isArray(n.author_keys) && n.author_keys.indexOf(key) >= 0;
      })
      .map(function (n) {
        return n.id;
      });
  }

  function authorsHtml() {
    var list = state.authors || [];
    if (!list.length) return "";
    return (
      '<details class="citation-extras" open><summary><h4>Authors on this map</h4></summary>' +
      '<p class="citation-meta">Click a name to highlight their papers. Follow adds them to People → followed.</p><ol>' +
      list
        .map(function (a, i) {
          var follow = a.followed
            ? '<span class="citation-meta">· following</span>'
            : '<button type="button" class="secondary citation-mini" data-follow-index="' +
              i +
              '">Follow</button>';
          return (
            '<li><button type="button" class="citation-link-btn" data-author-index="' +
            i +
            '">' +
            escapeHtml(a.name || a.key) +
            '</button> <span class="citation-meta">· ' +
            (a.count || 0) +
            (a.count === 1 ? " paper" : " papers") +
            "</span> " +
            follow +
            "</li>"
          );
        })
        .join("") +
      "</ol></details>"
    );
  }

  function bindAuthorButtons(rootEl) {
    rootEl.querySelectorAll("[data-author-index]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var a = state.authors[Number(btn.getAttribute("data-author-index"))];
        if (!a) return;
        if (isAuthorView()) {
          var hit = state.authorNodes.filter(function (n) {
            return n.key === a.key;
          })[0];
          if (hit) {
            state.selectedId = hit.id;
            showAuthor(hit);
            if (state.focusFn) state.focusFn(hit.id);
          }
          return;
        }
        var ids = a.node_ids && a.node_ids.length ? a.node_ids : authorKeyNodes(a.key);
        var same = state.highlightLabel === a.name && state.highlight.size === ids.length;
        setHighlight(same ? [] : ids, a.name);
      });
    });
    rootEl.querySelectorAll("[data-author-key]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.getAttribute("data-author-key") || "";
        setHighlight(authorKeyNodes(key), btn.textContent || "");
      });
    });
    rootEl.querySelectorAll("[data-follow-index]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var a = state.authors[Number(btn.getAttribute("data-follow-index"))];
        if (!a) return;
        btn.disabled = true;
        fetch("/discover/graph/follow", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: a.name, openalex: a.openalex || "", orcid: a.orcid || "" }),
        })
          .then(readJson)
          .then(function (body) {
            if (!body || body.ok === false) throw new Error((body && body.error) || "Could not follow.");
            markFollowed(a.key);
            setStatus("Following " + (a.name || "this author") + " (People → followed).");
            if (!state.selectedId) clearPanel();
          })
          .catch(function (error) {
            btn.disabled = false;
            setStatus(error.message || "Could not follow this author.");
          });
      });
    });
  }

  function download(name, type, text) {
    var blob = new Blob([text], { type: type });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function csvCell(value) {
    var text = value === null || value === undefined ? "" : String(value);
    // Guard spreadsheet formula injection from titles that start with = + - @.
    if (/^[=+\-@]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }

  function exportMap(kind) {
    var base = "paperful-map-" + (state.runId || "run");
    if (kind === "json") {
      download(base + ".json", "application/json", JSON.stringify(state.lastGraph || {}, null, 2));
    } else if (kind === "csv" && isAuthorView()) {
      var acols = ["name", "count", "cited_by_count", "year_from", "year_to", "coauthors", "seed", "followed", "openalex", "orcid"];
      var alines = [acols.map(csvCell).join(",")];
      state.authorNodes.forEach(function (a) {
        alines.push(
          acols
            .map(function (c) {
              return csvCell(a[c]);
            })
            .join(",")
        );
      });
      download(base + "-authors.csv", "text/csv", alines.join("\n") + "\n");
    } else if (kind === "csv") {
      var cols = ["id", "title", "year", "cited_by_count", "doi", "role", "similarity", "in_library", "keep", "seed", "authors"];
      var lines = [cols.join(",")];
      state.nodes.forEach(function (n) {
        lines.push(
          cols
            .map(function (c) {
              var v = n[c];
              if (c === "authors") v = (Array.isArray(n.authors) ? n.authors : []).join("; ");
              return csvCell(v);
            })
            .join(",")
        );
      });
      download(base + ".csv", "text/csv", lines.join("\n") + "\n");
    } else if (kind === "svg") {
      var node = els.svg.node();
      var clone = node.cloneNode(true);
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      var bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      bg.setAttribute("width", "100%");
      bg.setAttribute("height", "100%");
      bg.setAttribute("fill", "#fbf8f3");
      clone.insertBefore(bg, clone.firstChild);
      clone.setAttribute("font-family", "system-ui, sans-serif");
      download(base + ".svg", "image/svg+xml", new XMLSerializer().serializeToString(clone));
    }
    setStatus("Downloaded the map as " + kind.toUpperCase() + ".");
  }

  function pickPathNode(paper) {
    if (!state.pathFirst) {
      state.pathFirst = paper.id;
      setStatus("Path: choose the second paper.");
      return;
    }
    if (state.pathFirst === paper.id) {
      setStatus("Path: choose a different second paper.");
      return;
    }
    var path = bfsPath(state.pathFirst, paper.id);
    state.pathEdges = path || [];
    state.pathMode = false;
    if (els.pathMode) els.pathMode.classList.remove("is-active");
    state.pathFirst = "";
    // Render first: renderGraph writes its own status line.
    renderGraph();
    if (!path) {
      setStatus(
        isSimilarity()
          ? "No path between those papers on this map. Raise Links per paper in Settings for a denser map."
          : "No citation path between those papers on this map. Try Expand on each end."
      );
    } else {
      setStatus("Path: " + path.length + " link(s) on this map.");
      showPathPanel(path, paper);
    }
  }

  function bfsPath(start, end) {
    var adj = {};
    activeEdges().forEach(function (edge) {
      adj[edge.source] = adj[edge.source] || [];
      adj[edge.source].push({ next: edge.target, edge: edge });
      adj[edge.target] = adj[edge.target] || [];
      adj[edge.target].push({ next: edge.source, edge: edge });
    });
    var queue = [{ id: start, path: [] }];
    var seen = {};
    seen[start] = true;
    while (queue.length) {
      var item = queue.shift();
      if (item.path.length > 4) continue;
      var steps = adj[item.id] || [];
      for (var i = 0; i < steps.length; i += 1) {
        var step = steps[i];
        if (seen[step.next]) continue;
        var nextPath = item.path.concat([step.edge]);
        if (step.next === end) return nextPath;
        seen[step.next] = true;
        queue.push({ id: step.next, path: nextPath });
      }
    }
    return null;
  }

  function showPathPanel(path, endPaper) {
    var start = activeNodes().filter(function (n) {
      return n.id === path[0].source || n.id === path[0].target;
    })[0];
    var labels = path
      .map(function (edge) {
        if (edge.direction === "similar") return "similar to";
        if (edge.direction === "coauthor") return "co-wrote with";
        if (edge.direction === "linked") return "linked papers with";
        return edge.direction === "cites" ? "cites" : "references";
      })
      .join(" → ");
    els.panel.innerHTML =
      '<h3>Path on this map</h3><p class="citation-meta">' +
      escapeHtml((start && start.title) || "") +
      " … " +
      escapeHtml(endPaper.title || "") +
      "</p><p>" +
      escapeHtml(labels) +
      "</p>";
  }

  function markFollowed(key) {
    state.authors.forEach(function (a) {
      if (a.key === key) a.followed = true;
    });
    state.authorNodes.forEach(function (a) {
      if (a.key === key) a.followed = true;
    });
    // The renderer draws copies of each node; flag those too, then recolour
    // without moving the layout.
    els.svg.selectAll(".nodes > g").each(function (d) {
      if (d && d.key === key) d.followed = true;
    });
    if (isAuthorView()) {
      els.svg.selectAll(".nodes > g").select("circle").attr("fill", nodeFill);
    }
  }

  function followAuthor(a, btn) {
    if (btn) btn.disabled = true;
    return fetch("/discover/graph/follow", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: a.name, openalex: a.openalex || "", orcid: a.orcid || "" }),
    })
      .then(readJson)
      .then(function (body) {
        if (!body || body.ok === false) throw new Error((body && body.error) || "Could not follow.");
        markFollowed(a.key);
        setStatus("Following " + (a.name || "this author") + " (People → followed).");
        return true;
      })
      .catch(function (error) {
        if (btn) btn.disabled = false;
        setStatus(error.message || "Could not follow this author.");
        return false;
      });
  }

  function showAuthor(a) {
    var papers = state.nodes.filter(function (n) {
      return a.node_ids.indexOf(n.id) >= 0;
    });
    papers.sort(function (x, y) {
      return (y.year || 0) - (x.year || 0) || (y.cited_by_count || 0) - (x.cited_by_count || 0);
    });
    var span = a.year_from ? (a.year_from === a.year_to ? String(a.year_from) : a.year_from + "–" + a.year_to) : "";
    var links = [];
    if (a.openalex) {
      links.push(
        '<a href="https://openalex.org/' + escapeAttr(a.openalex) + '" rel="noopener noreferrer">OpenAlex</a>'
      );
    }
    if (a.orcid) {
      links.push(
        '<a href="https://orcid.org/' + escapeAttr(a.orcid) + '" rel="noopener noreferrer">ORCID</a>'
      );
    }
    var coauthors = state.authorEdges
      .filter(function (e) {
        return e.coauthored && (e.source === a.id || e.target === a.id);
      })
      .map(function (e) {
        var other = e.source === a.id ? e.target : e.source;
        return state.authorNodes.filter(function (n) {
          return n.id === other;
        })[0];
      })
      .filter(Boolean);
    els.panel.innerHTML =
      "<h3>" +
      escapeHtml(a.name) +
      "</h3>" +
      '<p class="citation-meta">' +
      a.count +
      (a.count === 1 ? " paper" : " papers") +
      " on this map · " +
      (a.cited_by_count || 0) +
      " citations" +
      (span ? " · " + escapeHtml(span) : "") +
      "</p>" +
      (a.seed ? "<p><strong>Wrote the starting paper</strong></p>" : "") +
      (a.library_papers ? '<p class="citation-meta">' + a.library_papers + " already in your library</p>" : "") +
      (links.length ? '<p class="citation-meta">' + links.join(" · ") + "</p>" : "") +
      '<div class="citation-actions">' +
      (a.followed
        ? '<span class="citation-meta">Following</span>'
        : '<button type="button" data-author-follow="1">Follow</button>') +
      '<button type="button" class="secondary" data-author-papers="1">Show their papers</button>' +
      "</div>" +
      (coauthors.length
        ? '<p class="citation-meta">Co-authors here: ' +
          coauthors
            .map(function (c) {
              return (
                '<button type="button" class="citation-link-btn" data-author-node="' +
                escapeAttr(c.id) +
                '">' +
                escapeHtml(c.name) +
                "</button>"
              );
            })
            .join(", ") +
          "</p>"
        : "") +
      '<div class="citation-extras"><h4>Their papers on this map</h4><ol>' +
      papers
        .map(function (p) {
          return (
            '<li><button type="button" class="citation-link-btn" data-paper-id="' +
            escapeAttr(p.id) +
            '">' +
            escapeHtml(p.title || p.id) +
            "</button>" +
            (p.year ? ' <span class="citation-meta">(' + p.year + ")</span>" : "") +
            (p.in_library ? ' <span class="citation-meta">· in library</span>' : "") +
            "</li>"
          );
        })
        .join("") +
      "</ol></div>";
    var follow = els.panel.querySelector("[data-author-follow]");
    if (follow) {
      follow.addEventListener("click", function () {
        followAuthor(a, follow).then(function (ok) {
          if (ok && state.selectedId === a.id) showAuthor(a);
        });
      });
    }
    els.panel.querySelector("[data-author-papers]").addEventListener("click", function () {
      setMapView("papers", { force: true, highlight: a.node_ids, label: a.name });
    });
    els.panel.querySelectorAll("[data-paper-id]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setMapView("papers", {
          force: true,
          highlight: a.node_ids,
          label: a.name,
          select: btn.getAttribute("data-paper-id"),
        });
      });
    });
    els.panel.querySelectorAll("[data-author-node]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var hit = state.authorNodes.filter(function (n) {
          return n.id === btn.getAttribute("data-author-node");
        })[0];
        if (hit) {
          state.selectedId = hit.id;
          showAuthor(hit);
          if (state.focusFn) state.focusFn(hit.id);
        }
      });
    });
  }

  function showNode(paper) {
    var year = paper.year || "year unknown";
    var library = paper.in_library
      ? "In your library" + (paper.item_key ? " · " + paper.item_key : "")
      : "Not in the library yet";
    var pdfLine =
      paper.in_library && paper.has_pdf === true
        ? "PDF on disk"
        : paper.in_library && paper.has_pdf === false
          ? "No PDF on disk yet"
          : "";
    var author = paper.first_author ? escapeHtml(paper.first_author) + " · " : "";
    var names = Array.isArray(paper.authors) ? paper.authors : [];
    var keys = Array.isArray(paper.author_keys) ? paper.author_keys : [];
    var authorLine = names.length
      ? '<p class="citation-meta citation-authors">By ' +
        names
          .map(function (name, i) {
            return keys[i]
              ? '<button type="button" class="citation-link-btn" data-author-key="' +
                  escapeAttr(keys[i]) +
                  '" title="Highlight this author\'s papers">' +
                  escapeHtml(name) +
                  "</button>"
              : escapeHtml(name);
          })
          .join(", ") +
        "</p>"
      : "";
    var doi = paper.doi
      ? '<p class="citation-meta"><a href="https://doi.org/' +
        escapeAttr(paper.doi) +
        '" rel="noopener noreferrer">doi:' +
        escapeHtml(paper.doi) +
        "</a></p>"
      : "";
    var why = paper.why ? "<p>" + escapeHtml(paper.why) + "</p>" : "";
    var triage = state.triageById[paper.id];
    var triageLine = triage
      ? '<p class="citation-meta">' + escapeHtml(triage.reason || "") + "</p>"
      : "";
    var cats = Array.isArray(paper.categories) ? paper.categories : [];
    var catLine = "";
    if (cats.length) {
      catLine =
        '<p class="citation-meta">Categories: ' +
        escapeHtml(
          cats
            .map(function (cid) {
              return (state.categoryById[cid] && state.categoryById[cid].label) || cid;
            })
            .join(", ")
        ) +
        "</p>";
    }
    var designs = Array.isArray(paper.study_designs) ? paper.study_designs : [];
    var designLine = designs.length
      ? '<p class="citation-meta">Study designs: ' +
        escapeHtml(designs.join(", ")) +
        "</p>"
      : "";
    var keep = "";
    if (paper.doi) {
      keep =
        '<div class="citation-actions">' +
        '<button type="button" class="secondary" data-keep="1">Keep</button>' +
        '<button type="button" class="secondary" data-keep="0">Skip</button>' +
        "</div>";
    }
    var canEdit = state.editMode !== "off";
    var libActions = "";
    var editForm = "";
    if (canEdit) {
      libActions = '<div class="citation-actions">';
      if (!paper.in_library && !paper.ghost) {
        libActions += '<button type="button" data-lib="add">Add to library</button>';
      }
      if (paper.in_library && paper.item_key) {
        libActions +=
          '<button type="button" class="secondary" data-lib="find-pdf">Find PDF</button>' +
          '<button type="button" class="secondary" data-lib="remove">Remove from library</button>' +
          '<a class="secondary" href="zotero://select/library/items/' +
          encodeURIComponent(paper.item_key) +
          '">Open in Zotero</a>';
        if (paper.has_pdf) {
          libActions +=
            '<a class="secondary" href="/item/' +
            encodeURIComponent(paper.item_key) +
            '/summary">Summary</a>';
        }
      }
      libActions += "</div>";
    }
    var seedSearchBtn =
      '<div class="citation-actions">' +
      '<button type="button" class="secondary" data-action="seed-search">Seed search</button>' +
      (paper.ghost
        ? ""
        : '<button type="button" class="secondary" data-similar-map="' +
          escapeAttr(paper.id) +
          '">' +
          (isSimilarity() && paper.seed ? "Rebuild Similar map" : "New Similar map from this paper") +
          "</button>") +
      "</div>";
    editForm = "";
    if (canEdit) {
      editForm =
        '<div class="citation-edit">' +
        '<label>Tags <input type="text" id="citationTags" value="' +
        escapeAttr((paper.tags || []).join(", ")) +
        '" placeholder="to-read, paperful:map"></label>' +
        '<label>Note <textarea id="citationNote" rows="2" placeholder="Why keep this?">' +
        escapeHtml(paper.note || "") +
        "</textarea></label>" +
        '<label>Collection <input type="text" id="citationCollection" value="' +
        escapeAttr(paper.target_collection || "") +
        '" placeholder="Inbox/Snowball" list="citationCollectionList"></label>' +
        '<datalist id="citationCollectionList"></datalist>' +
        '<button type="button" class="secondary" data-lib="save-meta">Save tags / note / collection</button>' +
        (paper.staged
          ? '<p class="citation-meta">Staged for Apply (or saved if already in library).</p>'
          : "") +
        "</div>";
    }
    var expandDisabled = state.expandBlocked ? " disabled" : "";
    var simLine = "";
    if (isSimilarity() && !paper.seed && typeof paper.similarity === "number") {
      simLine =
        '<p class="citation-meta">Similarity to origin: ' +
        Math.round(paper.similarity * 100) +
        "%" +
        (paper.origin_path && paper.origin_path.length
          ? " · " + paper.origin_path.length + " step(s) to the origin"
          : "") +
        "</p>";
    }
    var expandRow = isSimilarity()
      ? ""
      : '<div class="citation-actions">' +
        '<button type="button" class="secondary" data-expand="refs"' +
        expandDisabled +
        ">Papers it cites</button>" +
        '<button type="button" class="secondary" data-expand="cites"' +
        expandDisabled +
        ">Papers that cite it</button>" +
        "</div>";
    els.panel.innerHTML =
      "<h3>" +
      escapeHtml(paper.title || "Untitled") +
      "</h3>" +
      '<p class="citation-meta">' +
      author +
      year +
      " · " +
      (paper.cited_by_count || 0) +
      " citations</p>" +
      "<p><strong>" +
      escapeHtml(library) +
      "</strong>" +
      (pdfLine ? " · " + escapeHtml(pdfLine) : "") +
      "</p>" +
      "<p>" +
      escapeHtml(ROLE_LABEL[paper.role] || paper.role) +
      "</p>" +
      catLine +
      designLine +
      triageLine +
      authorLine +
      simLine +
      doi +
      why +
      keep +
      libActions +
      seedSearchBtn +
      editForm +
      expandRow;
    fillCollectionList();
    els.panel.querySelectorAll("[data-keep]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        submitKeep(paper, btn.getAttribute("data-keep") === "1");
      });
    });
    els.panel.querySelectorAll("[data-expand]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        expand(paper.id, btn.getAttribute("data-expand") || "both", btn);
      });
    });
    els.panel.querySelectorAll("[data-lib]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var action = btn.getAttribute("data-lib");
        if (action === "add") addToLibrary(paper, btn);
        else if (action === "find-pdf") findPdf(paper, btn);
        else if (action === "remove") removeFromLibrary(paper, btn);
        else if (action === "save-meta") saveMeta(paper, btn);
      });
    });
    els.panel.querySelectorAll("[data-action='seed-search']").forEach(function (btn) {
      btn.addEventListener("click", function () {
        seedSnowballForm(paper);
      });
    });
    bindSimilarButtons(els.panel);
    bindAuthorButtons(els.panel);
  }

  function seedSnowballForm(paper) {
    var title = paper.title || "";
    var doi = paper.doi || "";
    if (!doi && paper.id && paper.id.indexOf("doi:") === 0) {
      doi = paper.id.slice(4);
    }
    document.cookie = "pf_advanced=1; path=/; max-age=31536000; SameSite=Lax";
    sessionStorage.setItem(
      "paperfulDiscoverPrefill",
      JSON.stringify({ title: title, doi: doi })
    );
    window.location.href = "/discover?tab=topic";
  }

  function fillCollectionList() {
    var list = document.getElementById("citationCollectionList");
    if (!list || !state.metaCollections) return;
    list.innerHTML = state.metaCollections
      .map(function (p) {
        return '<option value="' + escapeAttr(p) + '"></option>';
      })
      .join("");
  }

  function postGraph(path, body) {
    return fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    }).then(readJson);
  }

  function addToLibrary(paper, btn) {
    if (btn) btn.disabled = true;
    setStatus("Adding to library…");
    postGraph("/discover/graph/add", { run_id: state.runId, node_id: paper.id })
      .then(function (payload) {
        if (payload.graph) adopt(payload.graph);
        var msg = "Added to library.";
        if (payload.searched) msg += " Searching for PDF…";
        if (payload.search_error) msg += " PDF search failed: " + payload.search_error;
        setStatus(msg);
        var updated = state.nodes.filter(function (n) { return n.id === paper.id; })[0];
        if (updated) showNode(updated);
      })
      .catch(function (error) {
        setStatus(error.message || "Could not add to library.");
        if (btn) btn.disabled = false;
      });
  }

  function findPdf(paper, btn) {
    if (btn) btn.disabled = true;
    setStatus("Finding PDF…");
    postGraph("/discover/graph/find-pdf", {
      run_id: state.runId,
      node_id: paper.id,
      item_key: paper.item_key || "",
    })
      .then(function (payload) {
        if (payload.graph) adopt(payload.graph);
        setStatus("PDF search finished for that item.");
        var updated = state.nodes.filter(function (n) { return n.id === paper.id; })[0];
        if (updated) showNode(updated);
      })
      .catch(function (error) {
        setStatus(error.message || "Could not find PDF.");
        if (btn) btn.disabled = false;
      });
  }

  function removeFromLibrary(paper, btn) {
    if (!window.confirm("Trash this item in Zotero? It will leave the library.")) return;
    if (btn) btn.disabled = true;
    setStatus("Removing from library…");
    postGraph("/discover/graph/remove", { run_id: state.runId, node_id: paper.id })
      .then(function (payload) {
        if (payload.graph) adopt(payload.graph);
        setStatus("Removed from library.");
        var updated = state.nodes.filter(function (n) { return n.id === paper.id; })[0];
        if (updated) showNode(updated);
      })
      .catch(function (error) {
        setStatus(error.message || "Could not remove from library.");
        if (btn) btn.disabled = false;
      });
  }

  function saveMeta(paper, btn) {
    var tagsInput = document.getElementById("citationTags");
    var noteInput = document.getElementById("citationNote");
    var collInput = document.getElementById("citationCollection");
    var tags = tagsInput
      ? tagsInput.value.split(/[,;]+/).map(function (t) { return t.trim(); }).filter(Boolean)
      : [];
    if (btn) btn.disabled = true;
    postGraph("/discover/graph/annotate", {
      run_id: state.runId,
      node_id: paper.id,
      tags: tags,
      note: noteInput ? noteInput.value : "",
      collection: collInput ? collInput.value : "",
    })
      .then(function (payload) {
        if (payload.graph) adopt(payload.graph);
        setStatus("Saved tags / note / collection.");
        var updated = state.nodes.filter(function (n) { return n.id === paper.id; })[0];
        if (updated) showNode(updated);
      })
      .catch(function (error) {
        setStatus(error.message || "Could not save.");
        if (btn) btn.disabled = false;
      });
  }

  function submitKeep(paper, keep) {
    if (!paper.doi) return;
    var body = new URLSearchParams();
    body.set("run_id", state.runId);
    body.set("doi", paper.doi);
    body.set("keep", keep ? "1" : "0");
    body.set("format", "json");
    fetch("/discover/keep", {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      body: body,
    })
      .then(readJson)
      .then(function (payload) {
        if (payload.graph) adopt(payload.graph);
        syncQueueRow(paper.doi, keep);
        var updated = state.nodes.filter(function (n) {
          return n.id === paper.id;
        })[0];
        if (updated) showNode(updated);
        setStatus(keep ? "Kept on this queue." : "Skipped on this queue.");
      })
      .catch(function (error) {
        setStatus(error.message || "Could not update Keep.");
      });
  }

  function syncQueueRow(doi, keep) {
    document.querySelectorAll('form[action="/discover/keep"]').forEach(function (form) {
      var input = form.querySelector('input[name="doi"]');
      if (input && input.value === doi) {
        var cell = form.closest("td");
        if (cell && cell.previousElementSibling) {
          var keepCell = cell.parentElement.querySelector("td:nth-child(3)");
          if (keepCell) keepCell.childNodes[0].textContent = keep ? "True" : "False";
        }
      }
    });
  }

  function showEdge(edge) {
    var source = edge.source.title || edge.source.id;
    var target = edge.target.title || edge.target.id;
    if (edge.direction === "coauthor" || edge.direction === "linked") {
      var bits = [];
      if (edge.coauthored) bits.push(edge.coauthored + (edge.coauthored === 1 ? " paper" : " papers") + " written together");
      if (edge.linked) bits.push("their papers are linked " + Math.round(edge.linked) + "× on this map");
      els.panel.innerHTML =
        "<h3>" + escapeHtml(source + " and " + target) + "</h3>" +
        '<p class="citation-meta">' + escapeHtml(bits.join(" · ") || "Linked on this map") + "</p>";
      return;
    }
    if (edge.direction === "similar") {
      els.panel.innerHTML =
        "<h3>" +
        escapeHtml(source + " is similar to " + target) +
        "</h3>" +
        '<p class="citation-meta">' +
        (edge.shared_refs || 0) +
        " shared references · " +
        (edge.co_citing || 0) +
        " papers cite both. Neither has to cite the other.</p>";
      return;
    }
    var label =
      edge.direction === "cites"
        ? source + " cites " + target
        : source + " references " + target;
    els.panel.innerHTML =
      "<h3>" + escapeHtml(label) + "</h3>" + '<p class="citation-meta">Arrow points to the cited paper.</p>';
  }

  function clearPanel() {
    if (!els.panel) return;
    var hint = isAuthorView()
      ? "Each circle is a person; bigger circles wrote more of the papers on this map. Click someone to see their papers, co-authors, and Follow."
      : isSimilarity()
      ? "Papers sit close together when they share citations and references, even if they never cite each other. Click a paper to see its strongest path to the origin."
      : state.edges && state.edges.length
        ? "Click a paper to see why it is on the map, then expand who it cites or who cites it."
        : "This map has no citation links yet. Click a paper, then use Papers it cites / Papers that cite it to pull neighbours from OpenAlex.";
    var extras = "";
    if (isSimilarity() && state.similar) {
      extras =
        extrasHtml(
          "Prior works",
          "Older papers many map papers cite. Often the field's foundations.",
          state.similar.prior,
          "map papers cite it"
        ) +
        extrasHtml(
          "Derivative works",
          "Papers citing many map papers. Often reviews or newer work that builds on this area.",
          state.similar.derivative,
          "map papers cited"
        );
    }
    els.panel.innerHTML =
      '<p class="citation-panel-empty">' +
      hint +
      (isAuthorView()
        ? ""
        : " A dark ring means it is already in your library." +
          (state.view.size_by === "uniform" ? "" : " Larger nodes have more citations.")) +
      "</p>" +
      authorsHtml() +
      extras;
    bindSimilarButtons(els.panel);
    bindAuthorButtons(els.panel);
  }

  function expand(nodeId, direction, btn) {
    if (state.expandBlocked) {
      setStatus("Expand is paused — OpenAlex budget is spent. Try again after it resets.");
      return;
    }
    if (btn) btn.disabled = true;
    var label =
      direction === "refs"
        ? "papers it cites"
        : direction === "cites"
          ? "papers that cite it"
          : "neighbours";
    setStatus("Loading " + label + "…");
    if (els.panel) {
      els.panel.innerHTML =
        '<p class="citation-panel-empty">Loading ' +
        escapeHtml(label) +
        " from OpenAlex…</p>";
    }
    fetch("/discover/graph/expand", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: state.runId,
        node_id: nodeId,
        direction: direction,
      }),
    })
      .then(readJson)
      .then(function (graph) {
        state.selectedId = nodeId;
        adopt(graph);
      })
      .catch(function (error) {
        var msg = error.message || "Could not expand that paper.";
        var budget =
          msg.toLowerCase().indexOf("budget") >= 0 ||
          msg.toLowerCase().indexOf("429") >= 0;
        if (budget) {
          state.expandBlocked = true;
          msg =
            "OpenAlex daily budget is spent — expand is paused until the budget resets (or you reload after it does).";
        }
        setStatus(msg);
        if (els.panel) {
          els.panel.innerHTML =
            "<h3>Could not expand</h3><p>" +
            escapeHtml(msg) +
            "</p><p class=\"citation-meta\">Citation links only appear after a refs/cites hop. A keyword search hit list has none until you expand.</p>";
        }
        if (btn) btn.disabled = state.expandBlocked;
      });
  }

  function repairLinks() {
    setStatus("Repairing citation links from seeds…");
    fetch("/discover/graph/repair", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: state.runId }),
    })
      .then(readJson)
      .then(function (graph) {
        adopt(graph);
        setStatus("Links repaired from OpenAlex for seeds on this queue.");
      })
      .catch(function (error) {
        setStatus(error.message || "Could not repair links.");
      });
  }

  function loadHalo(nodeId) {
    fetch("/discover/graph/halo", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: state.runId, node_id: nodeId }),
    })
      .then(readJson)
      .then(function (payload) {
        state.ghostNodes = payload.nodes || [];
        state.ghostEdges = payload.edges || [];
        renderGraph();
      })
      .catch(function () {
        state.ghostNodes = [];
        state.ghostEdges = [];
      });
  }

  function readJson(response) {
    return response.text().then(function (text) {
      var body = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch (error) {
        throw new Error("Could not read the map response.");
      }
      if (!response.ok || (body && body.ok === false)) {
        var err = (body && body.error) || "Could not update the map.";
        if (response.status === 429) state.expandBlocked = true;
        throw new Error(err);
      }
      if (body && body.graph) return body.graph;
      return body || {};
    });
  }

  function shortTitle(title) {
    var text = String(title || "Untitled").trim();
    if (text.length <= 22) return text;
    return text.slice(0, 20) + "…";
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/'/g, "&#39;");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
