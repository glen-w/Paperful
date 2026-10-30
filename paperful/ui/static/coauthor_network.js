(function () {
  var FILL = {
    ego: "#c46a2a",
    academia: "#3d5a80",
    government: "#6b4c7a",
    ngo: "#2f6f4e",
    industry: "#8a5a2b",
    research: "#3d5a80",
    other: "#8d99a6",
  };

  var state = {
    runId: "",
    phase: "",
    nodes: [],
    edges: [],
    metrics: {},
    meta: {},
    phases: [],
    runs: [],
    selectedId: "",
    simulation: null,
    reduceMotion: false,
  };
  var els = {};

  function init() {
    var root = document.getElementById("coauthorNetworkApp");
    if (!root || typeof d3 === "undefined") {
      var status = document.getElementById("networkStatus");
      if (status && typeof d3 === "undefined") {
        status.textContent = "The map could not load its drawing library.";
      }
      return;
    }
    els.root = root;
    els.svg = d3.select("#networkCanvas");
    els.panel = document.getElementById("networkPanel");
    els.status = document.getElementById("networkStatus");
    els.runSelect = document.getElementById("networkRunSelect");
    els.phaseSelect = document.getElementById("networkPhaseSelect");
    els.metrics = document.getElementById("networkMetrics");
    state.reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (els.runSelect) els.runSelect.addEventListener("change", onRunChange);
    if (els.phaseSelect) els.phaseSelect.addEventListener("change", onPhaseChange);
    window.addEventListener("resize", function () {
      if (state.nodes.length) renderGraph();
    });
    loadMeta().then(function () {
      if (state.runId) loadRun(state.runId);
    });
  }

  function setStatus(text) {
    if (els.status) els.status.textContent = text || "";
  }

  function loadMeta() {
    return fetch("/discover/network/meta")
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        state.runs = data.runs || [];
        fillRunSelect();
        if (!state.runId && state.runs.length) {
          state.runId = state.runs[0].run_id;
        }
      })
      .catch(function () {
        setStatus("Could not list saved network runs.");
      });
  }

  function fillRunSelect() {
    if (!els.runSelect) return;
    els.runSelect.innerHTML = "";
    if (!state.runs.length) {
      var empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "No runs yet";
      els.runSelect.appendChild(empty);
      return;
    }
    state.runs.forEach(function (row) {
      var opt = document.createElement("option");
      opt.value = row.run_id;
      opt.textContent =
        (row.display_name || row.orcid || row.run_id) +
        (row.built_at ? " · " + String(row.built_at).slice(0, 10) : "");
      if (row.run_id === state.runId) opt.selected = true;
      els.runSelect.appendChild(opt);
    });
  }

  function fillPhaseSelect() {
    if (!els.phaseSelect) return;
    els.phaseSelect.innerHTML = "";
    var all = document.createElement("option");
    all.value = "";
    all.textContent = "All years";
    els.phaseSelect.appendChild(all);
    (state.phases || []).forEach(function (phase) {
      var opt = document.createElement("option");
      opt.value = phase.id;
      opt.textContent = phase.label || phase.id;
      if (phase.id === state.phase) opt.selected = true;
      els.phaseSelect.appendChild(opt);
    });
  }

  function onRunChange() {
    state.runId = els.runSelect ? els.runSelect.value : "";
    state.phase = "";
    if (state.runId) loadRun(state.runId);
  }

  function onPhaseChange() {
    state.phase = els.phaseSelect ? els.phaseSelect.value : "";
    if (state.runId) loadRun(state.runId);
  }

  function loadRun(runId) {
    var url = "/discover/network?run_id=" + encodeURIComponent(runId);
    if (state.phase) url += "&phase=" + encodeURIComponent(state.phase);
    setStatus("Loading…");
    fetch(url)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (!data.ok && data.error) {
          setStatus(data.error);
          return;
        }
        var graph = data.graph || {};
        state.meta = data.meta || {};
        state.metrics = data.metrics || {};
        state.phases = (state.meta.phases || []).map(function (row) {
          return { id: row.id, label: row.label };
        });
        state.nodes = graph.nodes || [];
        state.edges = (graph.edges || []).map(function (edge) {
          return {
            source: edge.a || edge.source,
            target: edge.b || edge.target,
            weight: edge.weight || 1,
          };
        });
        fillPhaseSelect();
        renderMetrics();
        renderGraph();
      })
      .catch(function () {
        setStatus("Could not load this network run.");
      });
  }

  function renderMetrics() {
    if (!els.metrics) return;
    var ego = state.metrics.ego || {};
    var bits = [];
    bits.push((state.nodes || []).length + " people");
    bits.push((state.edges || []).length + " ties");
    if (ego.degree != null) bits.push("degree " + ego.degree);
    if (ego.betweenness != null) bits.push("betweenness " + Number(ego.betweenness).toFixed(3));
    if (ego.constraint != null) bits.push("constraint " + Number(ego.constraint).toFixed(3));
    var roles = (ego.brokerage || {}).roles || {};
    var roleBits = Object.keys(roles)
      .filter(function (key) {
        return roles[key];
      })
      .map(function (key) {
        return key + " " + roles[key];
      });
    if (roleBits.length) bits.push(roleBits.join(" · "));
    els.metrics.textContent = bits.join(" · ");
  }

  function nodeFill(node) {
    if (node.ego) return FILL.ego;
    return FILL[node.sector] || FILL.other;
  }

  function renderGraph() {
    var nodes = state.nodes.map(function (node) {
      return Object.assign({}, node);
    });
    var nodeById = new Map(
      nodes.map(function (node) {
        return [node.id, node];
      })
    );
    var links = state.edges
      .map(function (edge) {
        return Object.assign({}, edge, {
          source: nodeById.get(edge.source),
          target: nodeById.get(edge.target),
        });
      })
      .filter(function (edge) {
        return edge.source && edge.target;
      });

    if (!nodes.length) {
      els.svg.selectAll("*").remove();
      setStatus("No co-authors in this slice. Run an ORCID network, or pick another phase.");
      return;
    }
    setStatus(nodes.length + " people · " + links.length + " ties");

    var wrap = els.root.querySelector(".citation-canvas-wrap");
    var width = Math.max(wrap ? wrap.clientWidth : 640, 320);
    var height = Math.max(wrap ? wrap.clientHeight : 480, 360);
    els.svg.attr("viewBox", "0 0 " + width + " " + height).attr("width", width).attr("height", height);
    els.svg.selectAll("*").remove();

    var maxDeg =
      d3.max(nodes, function (node) {
        return node.degree || 1;
      }) || 1;
    var radiusScale = d3.scaleSqrt().domain([0, maxDeg]).range([8, 22]);
    function radius(node) {
      return node.ego ? 18 : radiusScale(node.degree || 0);
    }

    var g = els.svg.append("g");
    els.svg.call(
      d3.zoom().on("zoom", function (event) {
        g.attr("transform", event.transform);
      })
    );

    var link = g
      .append("g")
      .selectAll("line")
      .data(links)
      .enter()
      .append("line")
      .attr("stroke", "#5c6b73")
      .attr("stroke-opacity", 0.45)
      .attr("stroke-width", function (d) {
        return Math.min(4, 0.6 + (d.weight || 1) * 0.4);
      });

    var node = g
      .append("g")
      .selectAll("circle")
      .data(nodes)
      .enter()
      .append("circle")
      .attr("r", radius)
      .attr("fill", nodeFill)
      .attr("stroke", function (d) {
        return d.ego ? "#1f2a32" : "#f7f1e8";
      })
      .attr("stroke-width", function (d) {
        return d.ego ? 2.5 : 1;
      })
      .attr("role", "button")
      .attr("tabindex", 0)
      .on("click", function (event, d) {
        event.stopPropagation();
        showPanel(d);
      });

    var label = g
      .append("g")
      .selectAll("text")
      .data(nodes)
      .enter()
      .append("text")
      .text(function (d) {
        var name = d.display_name || d.id;
        return String(name).split(",")[0].slice(0, 22);
      })
      .attr("font-size", 9)
      .attr("fill", "#1f2a32")
      .attr("dx", 10)
      .attr("dy", 3);

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
      .force("charge", d3.forceManyBody().strength(nodes.length > 40 ? -220 : -140))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force(
        "collision",
        d3.forceCollide().radius(function (d) {
          return radius(d) + 8;
        })
      );

    var ego = nodes.find(function (n) {
      return n.ego;
    });
    if (ego) {
      ego.fx = width / 2;
      ego.fy = height / 2;
    }

    if (state.reduceMotion) {
      state.simulation.stop();
      for (var i = 0; i < 80; i++) state.simulation.tick();
      tick();
    } else {
      state.simulation.on("tick", tick);
    }

    function tick() {
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
      node
        .attr("cx", function (d) {
          return d.x;
        })
        .attr("cy", function (d) {
          return d.y;
        });
      label
        .attr("x", function (d) {
          return d.x;
        })
        .attr("y", function (d) {
          return d.y;
        });
    }
  }

  function showPanel(node) {
    if (!els.panel) return;
    state.selectedId = node.id;
    var rows = [
      ["Name", node.display_name || ""],
      ["ORCID", node.orcid || ""],
      ["OpenAlex", node.openalex || ""],
      ["Degree", node.degree != null ? String(node.degree) : ""],
      ["Papers with ego", node.frequency != null ? String(node.frequency) : ""],
      ["Region", node.region || ""],
      ["Sector", node.sector || ""],
      ["Discipline", node.discipline || ""],
      ["Career stage", node.career_stage || ""],
    ];
    var html = "<h3>" + escapeHtml(node.display_name || node.id) + "</h3>";
    if (node.ego) html += "<p class=\"citation-meta\">Ego</p>";
    html += "<dl>";
    rows.forEach(function (row) {
      if (!row[1]) return;
      html += "<dt>" + escapeHtml(row[0]) + "</dt><dd>" + escapeHtml(row[1]) + "</dd>";
    });
    html += "</dl>";
    els.panel.innerHTML = html;
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
