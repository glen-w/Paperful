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
    nodes: [],
    edges: [],
    direction: "both",
    showOccasional: false,
    simulation: null,
    reduceMotion: false,
    selectedId: "",
  };
  var els = {};

  function init() {
    var root = document.getElementById("citationMapApp");
    if (!root || typeof d3 === "undefined") {
      var status = document.getElementById("citationStatus");
      if (status && typeof d3 === "undefined") {
        status.textContent = "The map needs a network connection to load its drawing library.";
      }
      return;
    }
    els.root = root;
    els.svg = d3.select("#citationCanvas");
    els.panel = document.getElementById("citationPanel");
    els.status = document.getElementById("citationStatus");
    els.toggle = document.getElementById("citationShowOccasional");
    state.graphUrl = root.getAttribute("data-graph") || "";
    state.runId = root.getAttribute("data-run-id") || "";
    state.reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    root.querySelectorAll(".citation-filter").forEach(function (btn) {
      btn.addEventListener("click", function () {
        root.querySelectorAll(".citation-filter").forEach(function (other) {
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
    window.addEventListener("resize", function () {
      if (state.nodes.length) renderGraph();
    });

    setStatus("Loading citation map…");
    fetch(state.graphUrl, { credentials: "same-origin" })
      .then(readJson)
      .then(function (graph) {
        adopt(graph);
        clearPanel();
      })
      .catch(function (error) {
        setStatus(error.message || "Could not load the citation map.");
      });
  }

  function adopt(graph) {
    state.nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    state.edges = Array.isArray(graph.edges) ? graph.edges : [];
    renderGraph();
    if (state.selectedId) {
      var still = state.nodes.filter(function (node) {
        return node.id === state.selectedId;
      })[0];
      if (still) showNode(still);
    }
  }

  function setStatus(text) {
    if (els.status) els.status.textContent = text || "";
  }

  function visibleNodes() {
    return state.nodes.filter(function (node) {
      if (!state.showOccasional && node.occasional && !node.seed) return false;
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
    var ids = new Set(
      papers.map(function (paper) {
        return paper.id;
      })
    );
    var edges = visibleEdges(ids);
    var hidden = state.nodes.filter(function (paper) {
      return paper.occasional && !paper.seed;
    }).length;

    if (!papers.length) {
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
      d3.max(papers, function (paper) {
        return paper.cited_by_count || 1;
      }) || 1;
    var radiusScale = d3.scaleSqrt().domain([0, maxCited]).range([7, 26]);
    function radius(paper) {
      return radiusScale(paper.cited_by_count || 0);
    }

    var crowded = papers.length > 35;
    var nodes = papers.map(function (paper) {
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
      .attr("stroke-opacity", crowded ? 0.35 : 0.55)
      .attr("stroke-width", 1.4)
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
        state.selectedId = d.id;
        showNode(d);
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
        return d.in_library ? "#101820" : "#f7f1e8";
      })
      .attr("stroke-width", function (d) {
        return d.in_library ? 2.5 : 1;
      });

    node.append("title").text(function (d) {
      return (
        (d.title || "Untitled") +
        " · " +
        (d.year || "n.d.") +
        " · " +
        (d.cited_by_count || 0) +
        " citations"
      );
    });

    var labels = g
      .append("g")
      .attr("class", "node-labels")
      .selectAll("text")
      .data(nodes)
      .join("text")
      .text(function (d) {
        return shortTitle(d.title);
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
        node.style("opacity", 1);
        link.attr("stroke-opacity", crowded ? 0.35 : 0.55);
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

  function showNode(paper) {
    var year = paper.year || "year unknown";
    var library = paper.in_library ? "In your library" : "Not in the library yet";
    var author = paper.first_author ? escapeHtml(paper.first_author) + " · " : "";
    var doi = paper.doi
      ? '<p class="citation-meta"><a href="https://doi.org/' +
        escapeAttr(paper.doi) +
        '" rel="noopener noreferrer">doi:' +
        escapeHtml(paper.doi) +
        "</a></p>"
      : "";
    var why = paper.why ? "<p>" + escapeHtml(paper.why) + "</p>" : "";
    var keep = "";
    if (paper.doi) {
      keep =
        '<form method="post" action="/discover/keep" class="citation-actions">' +
        '<input type="hidden" name="run_id" value="' +
        escapeAttr(state.runId) +
        '">' +
        '<input type="hidden" name="doi" value="' +
        escapeAttr(paper.doi) +
        '">' +
        '<button type="submit" name="keep" value="1" class="secondary">Keep</button>' +
        '<button type="submit" name="keep" value="0" class="secondary">Skip</button>' +
        "</form>";
    }
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
      "<p>" +
      escapeHtml(ROLE_LABEL[paper.role] || paper.role) +
      "</p>" +
      "<p>" +
      library +
      "</p>" +
      doi +
      why +
      keep +
      '<div class="citation-actions">' +
      '<button type="button" class="secondary" data-expand="refs">Papers it cites</button>' +
      '<button type="button" class="secondary" data-expand="cites">Papers that cite it</button>' +
      "</div>";
    els.panel.querySelectorAll("[data-expand]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        expand(paper.id, btn.getAttribute("data-expand") || "both", btn);
      });
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
        setStatus(error.message || "Could not expand that paper.");
        if (btn) btn.disabled = false;
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
        throw new Error((body && body.error) || "Could not update the map.");
      }
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
