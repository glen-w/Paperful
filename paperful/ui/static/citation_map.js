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
  }

  function renderTriage() {
    if (!els.triage) return;
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

  function visibleNodes() {
    return state.nodes.filter(function (node) {
      if (!state.showOccasional && node.occasional && !node.seed) return false;
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
    return state.edges.filter(function (edge) {
      if (!ids.has(edge.source) || !ids.has(edge.target)) return false;
      if (state.direction === "both") return true;
      return edge.direction === state.direction;
    });
  }

  function renderGraph() {
    var papers = visibleNodes();
    var ghostPapers = state.showHalo ? state.ghostNodes : [];
    var ids = new Set(
      papers
        .concat(ghostPapers)
        .map(function (paper) {
          return paper.id;
        })
    );
    var edges = visibleEdges(ids).concat(state.showHalo ? state.ghostEdges : []);
    var hidden = state.nodes.filter(function (paper) {
      return paper.occasional && !paper.seed;
    }).length;

    if (!papers.length && !ghostPapers.length) {
      els.svg.selectAll("*").remove();
      setStatus("No papers to map yet. Search a topic, then come back.");
      return;
    }
    setStatus(
      state.showOccasional
        ? papers.length + " papers · " + edges.length + " links"
        : papers.length +
            " papers · " +
            edges.length +
            " links" +
            (hidden ? " (" + hidden + " other hidden)" : "")
    );

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
    function radius(paper) {
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
    var labelCap = papers.length > 40 ? 8 : papers.length > 20 ? 12 : 18;
    var labeledIds = new Set(
      nodes
        .slice()
        .sort(function (a, b) {
          return (b.cited_by_count || 0) - (a.cited_by_count || 0);
        })
        .slice(0, labelCap)
        .map(function (node) {
          return node.id;
        })
    );
    seeds.forEach(function (node) {
      labeledIds.add(node.id);
    });

    var g = els.svg.append("g").attr("class", "citation-zoom");
    var zoom = d3
      .zoom()
      .scaleExtent([0.35, 4])
      .on("zoom", function (event) {
        g.attr("transform", event.transform);
      });
    els.svg.call(zoom);

    var link = g
      .append("g")
      .attr("class", "links")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", function (d) {
        return d.direction === "cites" ? "#3d5a80" : "#c46a2a";
      })
      .attr("stroke-opacity", function (d) {
        var key = d.source.id + "|" + d.target.id + "|" + d.direction;
        if (pathKeys.size && pathKeys.has(key)) return 0.95;
        return crowded ? 0.35 : 0.55;
      })
      .attr("stroke-width", function (d) {
        var key = d.source.id + "|" + d.target.id + "|" + d.direction;
        return pathKeys.size && pathKeys.has(key) ? 2.4 : 1.4;
      })
      .attr("stroke-dasharray", function (d) {
        return d.source.ghost || d.target.ghost ? "4 3" : null;
      })
      .attr("marker-end", "url(#citation-arrow)")
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
      .on("click", function (event, d) {
        event.stopPropagation();
        if (state.pathMode) {
          pickPathNode(d);
          return;
        }
        state.selectedId = d.id;
        showNode(d);
        if (state.showHalo) loadHalo(d.id);
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
      .attr("fill", function (d) {
        return ROLE_FILL[d.role] || ROLE_FILL.other;
      })
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
        node.style("opacity", function (d) {
          if (d.keep === false) return 0.35;
          if (d.watch_seen) return 0.45;
          return 1;
        });
        link.attr("stroke-opacity", function (d) {
          var key = d.source.id + "|" + d.target.id + "|" + d.direction;
          if (pathKeys.size && pathKeys.has(key)) return 0.95;
          return crowded ? 0.35 : 0.55;
        });
        labels.style("opacity", function (d) {
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

    els.svg.on("click", function () {
      state.selectedId = "";
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
          .distance(70)
          .strength(0.35)
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

    if (state.reduceMotion) {
      state.simulation.stop();
      for (var i = 0; i < 200; i += 1) state.simulation.tick();
      state.simulation.on("tick")();
    }
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
    if (!path) {
      setStatus("No citation path between those papers on this map. Try Expand on each end.");
    } else {
      setStatus("Path: " + path.length + " link(s) on this map.");
      showPathPanel(path, paper);
    }
    state.pathFirst = "";
    renderGraph();
  }

  function bfsPath(start, end) {
    var adj = {};
    state.edges.forEach(function (edge) {
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
    var start = state.nodes.filter(function (n) {
      return n.id === path[0].source || n.id === path[0].target;
    })[0];
    var labels = path
      .map(function (edge) {
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
      doi +
      why +
      keep +
      libActions +
      seedSearchBtn +
      editForm +
      '<div class="citation-actions">' +
      '<button type="button" class="secondary" data-expand="refs"' +
      expandDisabled +
      ">Papers it cites</button>" +
      '<button type="button" class="secondary" data-expand="cites"' +
      expandDisabled +
      ">Papers that cite it</button>" +
      "</div>";
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
    var label =
      edge.direction === "cites"
        ? source + " cites " + target
        : source + " references " + target;
    els.panel.innerHTML =
      "<h3>" + escapeHtml(label) + "</h3>" + '<p class="citation-meta">Arrow points to the cited paper.</p>';
  }

  function clearPanel() {
    if (!els.panel) return;
    els.panel.innerHTML =
      '<p class="citation-panel-empty">Click a paper to see why it is on the map, then expand who it cites or who cites it. A dark ring means it is already in your library. Larger nodes have more citations.</p>';
  }

  function expand(nodeId, direction, btn) {
    if (state.expandBlocked) return;
    if (btn) btn.disabled = true;
    setStatus("Loading neighbours…");
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
        if (msg.toLowerCase().indexOf("budget") >= 0 || msg.toLowerCase().indexOf("429") >= 0) {
          state.expandBlocked = true;
          msg += " Expand is paused until you reload or OpenAlex resets.";
        }
        setStatus(msg);
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
