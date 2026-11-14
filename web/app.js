/* Live 2D Metric Map & Guidance Client (pure DOM/Canvas, textContent only). */
(function () {
  "use strict";

  // Mirrors voice/led_states.py STATES so the wrist preview matches hardware cues.
  var LED_STATES = {
    idle: { color: null, pattern: "off", period: 1000, label: "LED off" },
    route_started: {
      color: "#00ff00",
      pattern: "blink",
      period: 400,
      holdMs: 1500,
      then: "recording",
      label: "Green blink — route started"
    },
    recording: {
      color: "#ffb000",
      pattern: "breathe",
      period: 2000,
      label: "Amber breathe — recording walk"
    },
    landmark_saved: {
      color: "#a020f0",
      pattern: "solid",
      period: 1000,
      holdMs: 1500,
      then: "recording",
      label: "Purple solid — landmark saved"
    },
    navigating: {
      color: "#ffffff",
      pattern: "breathe",
      period: 2000,
      label: "White breathe — navigating back"
    },
    turn_now: {
      color: "#ffffff",
      pattern: "blink",
      period: 500,
      label: "White blink — approaching turn"
    },
    arrived: {
      color: "#00ff00",
      pattern: "solid",
      period: 1000,
      holdMs: 1500,
      then: "arrived_party",
      label: "Green solid — destination reached"
    },
    arrived_party: {
      color: null,
      pattern: "rainbow",
      period: 2000,
      label: "Rainbow — arrived!"
    },
    uncertain: {
      color: "#ff0000",
      pattern: "blink",
      period: 500,
      label: "Red blink — position uncertain"
    }
  };

  var state = {
    mode: "SIMULATION",
    linkStatus: "simulated",
    wsConnected: false,
    ledState: "idle",
    ledPeriod: null,
    ledTimer: null,
    routePoints: [],
    returnTrail: [],
    currentPose: { t: 0, x_m: 0, y_m: 0, heading_deg: 0, steps: 0 },
    hasPose: false,
    landmarks: [],
    guidance: {
      instructions: [],
      current_index: 0,
      active: false,
      waypoints: []
    },
    lastSay: ""
  };

  var els = {
    fileWarning: document.getElementById("file-warning"),
    modeBanner: document.getElementById("mode-banner"),
    linkDot: document.getElementById("link-dot"),
    linkText: document.getElementById("link-text"),
    wsDot: document.getElementById("ws-dot"),
    wsText: document.getElementById("ws-text"),
    fitBtn: document.getElementById("fit-btn"),
    themeBtn: document.getElementById("theme-btn"),
    canvas: document.getElementById("map-canvas"),
    poseX: document.getElementById("pose-x"),
    poseY: document.getElementById("pose-y"),
    poseHeading: document.getElementById("pose-heading"),
    poseSteps: document.getElementById("pose-steps"),
    ledOrb: document.getElementById("led-orb"),
    ledStateName: document.getElementById("led-state-name"),
    ledDetail: document.getElementById("led-detail"),
    sayBox: document.getElementById("say-box"),
    ttsCheckbox: document.getElementById("tts-checkbox"),
    guidanceBadge: document.getElementById("guidance-badge"),
    guidanceEmpty: document.getElementById("guidance-empty"),
    guidanceList: document.getElementById("guidance-list"),
    landmarkCount: document.getElementById("landmark-count"),
    landmarkEmpty: document.getElementById("landmark-empty"),
    landmarkList: document.getElementById("landmark-list"),
    cmdForm: document.getElementById("cmd-form"),
    cmdInput: document.getElementById("cmd-input")
  };

  // Warn immediately when opened via double-click (file: protocol).
  if (window.location.protocol === "file:") {
    els.fileWarning.classList.remove("hidden");
    els.fileWarning.textContent =
      "Opened via file:// — run `python3 -m http.server 8000 --bind 127.0.0.1` in the project root, then open http://localhost:8000/web/";
  }

  function clearChildren(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  // --- Mode, Link & LED rendering -------------------------------------------
  function renderMode() {
    var mode = (state.mode || "SIMULATION").toUpperCase();
    if (mode === "LIVE") {
      els.modeBanner.classList.add("hidden");
      return;
    }
    els.modeBanner.classList.remove("hidden");
    if (mode === "REPLAY") {
      els.modeBanner.classList.add("mode-replay");
      els.modeBanner.textContent = "REPLAY — Recorded Walk (Not Live Sensing)";
    } else {
      els.modeBanner.classList.remove("mode-replay");
      els.modeBanner.textContent = "SIMULATION — Synthetic Walk (Not Live Sensing)";
    }
  }

  function renderLink() {
    var status = state.linkStatus || "disconnected";
    els.linkText.textContent = status;
    els.linkDot.className = "dot";
    if (status === "connected" || status === "reconnected") {
      els.linkDot.classList.add("ok");
    } else if (status === "reconnecting" || status === "simulated" || status === "replay") {
      els.linkDot.classList.add("warn");
    } else {
      els.linkDot.classList.add("err");
    }
  }

  function renderWsStatus(label, level) {
    els.wsText.textContent = label;
    els.wsDot.className = "dot " + level;
  }

  function applyLedState(name, periodOverride) {
    if (state.ledTimer) {
      clearTimeout(state.ledTimer);
      state.ledTimer = null;
    }
    var key = LED_STATES[name] ? name : "idle";
    var cue = LED_STATES[key];
    var period = periodOverride || cue.period || 1000;
    state.ledState = key;
    state.ledPeriod = period;

    els.ledStateName.textContent = key;
    var detail = cue.label;
    if (key === "turn_now" && periodOverride) {
      detail += " (" + String(periodOverride) + " ms)";
    }
    els.ledDetail.textContent = detail;

    els.ledOrb.className = "led-orb";
    els.ledOrb.style.setProperty("--led-period", String(period) + "ms");
    if (cue.pattern === "off") {
      els.ledOrb.style.backgroundColor = "#334155";
      els.ledOrb.style.boxShadow = "none";
    } else if (cue.pattern === "rainbow") {
      els.ledOrb.style.backgroundColor = "transparent";
      els.ledOrb.style.boxShadow = "0 0 14px rgba(168, 85, 247, 0.7)";
      els.ledOrb.classList.add("led-pattern-rainbow");
    } else {
      var color = cue.color || "#ffffff";
      els.ledOrb.style.backgroundColor = color;
      els.ledOrb.style.boxShadow = "0 0 14px " + color;
      if (cue.pattern === "blink") {
        els.ledOrb.classList.add("led-pattern-blink");
      } else if (cue.pattern === "breathe") {
        els.ledOrb.classList.add("led-pattern-breathe");
      }
    }

    if (cue.holdMs && cue.then) {
      state.ledTimer = setTimeout(function () {
        applyLedState(cue.then, null);
      }, cue.holdMs);
    }
  }

  function renderPoseOverlay() {
    var p = state.currentPose;
    els.poseX.textContent = "x: " + p.x_m.toFixed(1) + " m";
    els.poseY.textContent = "y: " + p.y_m.toFixed(1) + " m";
    els.poseHeading.textContent = "hdg: " + Math.round(p.heading_deg) + "°";
    els.poseSteps.textContent = "steps: " + String(p.steps);
  }

  function handleSay(text) {
    if (!text) {
      return;
    }
    state.lastSay = text;
    els.sayBox.textContent = text;
    if (els.ttsCheckbox.checked && "speechSynthesis" in window) {
      try {
        window.speechSynthesis.cancel();
        var utter = new SpeechSynthesisUtterance(text);
        utter.rate = 1.02;
        window.speechSynthesis.speak(utter);
      } catch (_err) {
        // Ignore browser TTS blocks when tab lacks user gesture.
      }
    }
  }

  // --- Guidance & Landmarks DOM lists (strictly textContent) ----------------
  function renderGuidance() {
    clearChildren(els.guidanceList);
    var insts = state.guidance.instructions || [];
    var cur = state.guidance.current_index || 0;
    var active = Boolean(state.guidance.active);

    if (!insts.length) {
      els.guidanceBadge.textContent = "inactive";
      els.guidanceEmpty.classList.remove("hidden");
      return;
    }

    els.guidanceEmpty.classList.add("hidden");
    if (active) {
      els.guidanceBadge.textContent = "step " + String(cur + 1) + " of " + String(insts.length);
    } else if (cur >= insts.length - 1 && insts[insts.length - 1].turn === "arrive") {
      els.guidanceBadge.textContent = "arrived";
    } else {
      els.guidanceBadge.textContent = "ready";
    }

    for (var i = 0; i < insts.length; i++) {
      var item = insts[i];
      var li = document.createElement("li");
      li.className = "guidance-step";
      if (active && i === cur) {
        li.classList.add("active");
      } else if (i < cur || (!active && cur >= insts.length - 1)) {
        li.classList.add("done");
      }

      var badge = document.createElement("span");
      badge.className = "step-badge";
      badge.textContent = String(i + 1);

      var body = document.createElement("span");
      body.textContent = item.text || "";

      li.appendChild(badge);
      li.appendChild(body);
      els.guidanceList.appendChild(li);
    }
  }

  function upsertLandmark(lm) {
    if (typeof lm.x_m !== "number" || typeof lm.y_m !== "number") {
      var pt = state.routePoints[lm.point_index];
      if (pt) {
        lm.x_m = pt.x_m;
        lm.y_m = pt.y_m;
      } else {
        lm.x_m = state.currentPose.x_m;
        lm.y_m = state.currentPose.y_m;
      }
    }
    for (var i = 0; i < state.landmarks.length; i++) {
      if (state.landmarks[i].id === lm.id) {
        state.landmarks[i] = lm;
        renderLandmarks();
        return;
      }
    }
    state.landmarks.push(lm);
    renderLandmarks();
  }

  function renderLandmarks() {
    clearChildren(els.landmarkList);
    els.landmarkCount.textContent = String(state.landmarks.length);
    if (!state.landmarks.length) {
      els.landmarkEmpty.classList.remove("hidden");
      return;
    }
    els.landmarkEmpty.classList.add("hidden");

    state.landmarks.forEach(function (lm) {
      var li = document.createElement("li");
      li.className = "landmark-item";

      var top = document.createElement("div");
      top.className = "landmark-top";

      var title = document.createElement("span");
      title.className = "landmark-label";
      title.textContent = lm.label || lm.id;

      var tags = document.createElement("div");
      tags.className = "landmark-tags";

      var idTag = document.createElement("span");
      idTag.className = "mini-tag";
      idTag.textContent = lm.id;
      tags.appendChild(idTag);

      if (lm.floor) {
        var floorTag = document.createElement("span");
        floorTag.className = "mini-tag";
        floorTag.textContent = "Floor " + lm.floor;
        tags.appendChild(floorTag);
      }

      if (typeof lm.x_m === "number" && typeof lm.y_m === "number") {
        var posTag = document.createElement("span");
        posTag.className = "mini-tag";
        posTag.textContent = "(" + lm.x_m.toFixed(1) + ", " + lm.y_m.toFixed(1) + ") m";
        tags.appendChild(posTag);
      }

      top.appendChild(title);
      top.appendChild(tags);
      li.appendChild(top);

      if (lm.note) {
        var noteEl = document.createElement("div");
        noteEl.className = "landmark-note";
        noteEl.textContent = lm.note;
        li.appendChild(noteEl);
      }

      var actions = document.createElement("div");
      actions.className = "landmark-actions";

      var navBtn = document.createElement("button");
      navBtn.type = "button";
      navBtn.className = "btn-mini";
      navBtn.textContent = "Guide here";
      navBtn.addEventListener("click", function () {
        sendCommand("take me back to " + (lm.label || lm.id));
      });

      var anchorBtn = document.createElement("button");
      anchorBtn.type = "button";
      anchorBtn.className = "btn-mini";
      anchorBtn.textContent = "I'm here";
      anchorBtn.addEventListener("click", function () {
        sendCommand("I'm at " + (lm.label || lm.id));
      });

      actions.appendChild(navBtn);
      actions.appendChild(anchorBtn);
      li.appendChild(actions);

      els.landmarkList.appendChild(li);
    });
  }

  // --- 2D Metric Canvas Renderer (+x right, +y up) --------------------------
  function chooseGridStep(spanMetres) {
    var candidates = [1, 2, 5, 10, 20, 50, 100];
    for (var i = 0; i < candidates.length; i++) {
      if (spanMetres / candidates[i] <= 10) {
        return candidates[i];
      }
    }
    return 100;
  }

  function computeBounds() {
    var xs = [0];
    var ys = [0];
    state.routePoints.forEach(function (p) {
      xs.push(p.x_m);
      ys.push(p.y_m);
    });
    state.returnTrail.forEach(function (p) {
      xs.push(p.x_m);
      ys.push(p.y_m);
    });
    state.landmarks.forEach(function (lm) {
      if (typeof lm.x_m === "number" && typeof lm.y_m === "number") {
        xs.push(lm.x_m);
        ys.push(lm.y_m);
      }
    });
    (state.guidance.waypoints || []).forEach(function (wp) {
      if (Array.isArray(wp) && wp.length >= 2) {
        xs.push(wp[0]);
        ys.push(wp[1]);
      }
    });
    if (state.hasPose) {
      xs.push(state.currentPose.x_m);
      ys.push(state.currentPose.y_m);
    }

    var minX = Math.min.apply(null, xs);
    var maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys);
    var maxY = Math.max.apply(null, ys);

    var spanX = Math.max(8, maxX - minX);
    var spanY = Math.max(8, maxY - minY);
    var cx = (minX + maxX) / 2;
    var cy = (minY + maxY) / 2;

    return {
      cx: cx,
      cy: cy,
      spanX: spanX * 1.28,
      spanY: spanY * 1.28
    };
  }

  function drawMap() {
    var canvas = els.canvas;
    var rect = canvas.getBoundingClientRect();
    var width = Math.max(200, Math.floor(rect.width));
    var height = Math.max(200, Math.floor(rect.height));
    var dpr = window.devicePixelRatio || 1;

    if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
    }

    var ctx = canvas.getContext("2d");
    ctx.save();
    ctx.scale(dpr, dpr);

    var cs = getComputedStyle(document.documentElement);
    var bgColor = cs.getPropertyValue("--canvas-bg").trim() || "#090e18";
    var gridMinor = cs.getPropertyValue("--grid-minor").trim() || "rgba(148,163,184,0.1)";
    var gridAxis = cs.getPropertyValue("--grid-axis").trim() || "rgba(148,163,184,0.28)";
    var routeColor = cs.getPropertyValue("--route-line").trim() || "#f59e0b";
    var guidanceColor = cs.getPropertyValue("--guidance-line").trim() || "#38bdf8";
    var textColor = cs.getPropertyValue("--text").trim() || "#f1f5f9";
    var mutedColor = cs.getPropertyValue("--text-muted").trim() || "#94a3b8";

    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, width, height);

    var bounds = computeBounds();
    var scale = Math.min(width / bounds.spanX, height / bounds.spanY);

    function toScreenX(xm) {
      return width / 2 + (xm - bounds.cx) * scale;
    }
    function toScreenY(ym) {
      return height / 2 - (ym - bounds.cy) * scale;
    }

    // Metric grid (+x right, +y up)
    var worldSpan = Math.max(width, height) / scale;
    var gridStep = chooseGridStep(worldSpan);
    var leftM = bounds.cx - width / (2 * scale);
    var rightM = bounds.cx + width / (2 * scale);
    var bottomM = bounds.cy - height / (2 * scale);
    var topM = bounds.cy + height / (2 * scale);

    ctx.lineWidth = 1;
    ctx.strokeStyle = gridMinor;
    ctx.beginPath();
    for (var gx = Math.floor(leftM / gridStep) * gridStep; gx <= rightM; gx += gridStep) {
      var sx = toScreenX(gx);
      ctx.moveTo(sx, 0);
      ctx.lineTo(sx, height);
    }
    for (var gy = Math.floor(bottomM / gridStep) * gridStep; gy <= topM; gy += gridStep) {
      var sy = toScreenY(gy);
      ctx.moveTo(0, sy);
      ctx.lineTo(width, sy);
    }
    ctx.stroke();

    // Coordinate axes through (0, 0)
    ctx.strokeStyle = gridAxis;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(toScreenX(0), 0);
    ctx.lineTo(toScreenX(0), height);
    ctx.moveTo(0, toScreenY(0));
    ctx.lineTo(width, toScreenY(0));
    ctx.stroke();

    // Recorded outbound walk polyline
    if (state.routePoints.length > 1) {
      ctx.strokeStyle = routeColor;
      ctx.lineWidth = 3.2;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      state.routePoints.forEach(function (pt, idx) {
        var px = toScreenX(pt.x_m);
        var py = toScreenY(pt.y_m);
        if (idx === 0 || pt.jump) {          // a re-anchor reset was never walked: no line to it
          ctx.moveTo(px, py);
        } else {
          ctx.lineTo(px, py);
        }
      });
      ctx.stroke();
    }

    // Highlighted return-guidance path
    var wps = state.guidance.waypoints || [];
    if (wps.length > 1 && (state.guidance.active || state.guidance.instructions.length > 0)) {
      ctx.save();
      ctx.strokeStyle = guidanceColor;
      ctx.lineWidth = state.guidance.active ? 3.5 : 2.0;
      ctx.setLineDash([8, 6]);
      ctx.beginPath();
      wps.forEach(function (wp, idx) {
        var wx = toScreenX(wp[0]);
        var wy = toScreenY(wp[1]);
        if (idx === 0) {
          ctx.moveTo(wx, wy);
        } else {
          ctx.lineTo(wx, wy);
        }
      });
      ctx.stroke();
      ctx.restore();

      // Highlight current active guidance leg
      var curIdx = state.guidance.current_index || 0;
      if (state.guidance.active && curIdx < wps.length - 1) {
        ctx.strokeStyle = guidanceColor;
        ctx.lineWidth = 5;
        ctx.beginPath();
        ctx.moveTo(toScreenX(wps[curIdx][0]), toScreenY(wps[curIdx][1]));
        ctx.lineTo(toScreenX(wps[curIdx + 1][0]), toScreenY(wps[curIdx + 1][1]));
        ctx.stroke();
      }
    }

    // Start marker at (0, 0)
    var ox = toScreenX(0);
    var oy = toScreenY(0);
    ctx.fillStyle = "#22c55e";
    ctx.beginPath();
    ctx.arc(ox, oy, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = "600 11px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.fillStyle = mutedColor;
    ctx.fillText("(0, 0)", ox + 9, oy + 4);

    // Landmarks with labels
    state.landmarks.forEach(function (lm) {
      var lx = toScreenX(lm.x_m || 0);
      var ly = toScreenY(lm.y_m || 0);

      ctx.fillStyle = "#a855f7";
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(lx, ly, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      var tag = lm.label || lm.id;
      if (lm.floor) {
        tag += " [" + lm.floor + "]";
      }
      ctx.font = "700 12px -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillStyle = textColor;
      ctx.fillText(tag, lx + 11, ly - 5);
    });

    // Current walker position + heading arrow (0 deg = +y up, 90 deg = +x right)
    if (state.hasPose || state.routePoints.length > 0) {
      var pose = state.currentPose;
      var wx = toScreenX(pose.x_m);
      var wy = toScreenY(pose.y_m);
      var hdgRad = (pose.heading_deg * Math.PI) / 180;
      var screenAngle = hdgRad - Math.PI / 2;

      // Halo
      ctx.fillStyle = "rgba(56, 189, 248, 0.22)";
      ctx.beginPath();
      ctx.arc(wx, wy, 16, 0, Math.PI * 2);
      ctx.fill();

      // Heading arrow
      ctx.save();
      ctx.translate(wx, wy);
      ctx.rotate(screenAngle);
      ctx.fillStyle = "#38bdf8";
      ctx.strokeStyle = "#082f49";
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.moveTo(14, 0);
      ctx.lineTo(-9, -8);
      ctx.lineTo(-5, 0);
      ctx.lineTo(-9, 8);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }

    // Metric scale bar (bottom-right) + orientation cue (+y ahead, +x right)
    var barPx = gridStep * scale;
    var bx = width - 20 - barPx;
    var by = height - 22;
    ctx.strokeStyle = textColor;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(bx, by - 4);
    ctx.lineTo(bx, by);
    ctx.lineTo(bx + barPx, by);
    ctx.lineTo(bx + barPx, by - 4);
    ctx.stroke();
    ctx.font = "600 11px -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.fillStyle = textColor;
    ctx.fillText(String(gridStep) + " m", bx + 4, by - 7);

    ctx.fillStyle = mutedColor;
    ctx.fillText("+y ahead ↑   +x right →", width - 152, 24);

    ctx.restore();
  }

  // --- WebSocket Client & Message Dispatch ----------------------------------
  var socket = null;
  var reconnectTimer = null;

  function resolveWsUrl() {
    var params = new URLSearchParams(window.location.search);
    var custom = params.get("ws");
    if (custom && (custom.indexOf("ws://") === 0 || custom.indexOf("wss://") === 0)) {
      return custom;
    }
    var port = params.get("ws_port") || "8765";
    return "ws://127.0.0.1:" + port;
  }

  function resetRouteView() {
    state.routePoints = [];
    state.returnTrail = [];
    state.landmarks = [];
    state.hasPose = false;
    state.currentPose = { t: 0, x_m: 0, y_m: 0, heading_deg: 0, steps: 0 };
    state.guidance = { instructions: [], current_index: 0, active: false, waypoints: [] };
    renderPoseOverlay();
    renderLandmarks();
    renderGuidance();
    drawMap();
  }

  function handleServerMessage(msg) {
    if (!msg || typeof msg !== "object") {
      return;
    }
    switch (msg.type) {
      case "mode":
        state.mode = msg.mode || "SIMULATION";
        renderMode();
        break;
      case "link":
        state.linkStatus = msg.status || "disconnected";
        renderLink();
        break;
      case "led":
        applyLedState(msg.state || "idle", msg.period || null);
        break;
      case "say":
        handleSay(msg.text || "");
        break;
      case "reset":
        resetRouteView();
        break;
      case "point":
        var pt = {
          t: Number(msg.t || 0),
          x_m: Number(msg.x_m || 0),
          y_m: Number(msg.y_m || 0),
          heading_deg: Number(msg.heading_deg || 0),
          steps: Number(msg.steps || 0),
          jump: msg.jump === true
        };
        state.currentPose = pt;
        state.hasPose = true;
        if (state.guidance.active) {
          state.returnTrail.push(pt);
        } else {
          state.routePoints.push(pt);
        }
        renderPoseOverlay();
        drawMap();
        break;
      case "landmark":
        upsertLandmark({
          id: String(msg.id || ""),
          label: String(msg.label || ""),
          point_index: Number(msg.point_index || 0),
          floor: msg.floor ? String(msg.floor) : null,
          note: msg.note ? String(msg.note) : null,
          transcript: msg.transcript ? String(msg.transcript) : null,
          x_m: typeof msg.x_m === "number" ? msg.x_m : undefined,
          y_m: typeof msg.y_m === "number" ? msg.y_m : undefined
        });
        drawMap();
        break;
      case "guidance":
        state.guidance = {
          instructions: Array.isArray(msg.instructions) ? msg.instructions : [],
          current_index: Number(msg.current_index || 0),
          active: Boolean(msg.active),
          waypoints: Array.isArray(msg.waypoints) ? msg.waypoints : []
        };
        if (!state.guidance.active) {
          state.returnTrail = [];
        }
        renderGuidance();
        drawMap();
        break;
      default:
        break;
    }
  }

  function connectWebSocket() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    var url = resolveWsUrl();
    renderWsStatus("connecting", "warn");
    try {
      socket = new WebSocket(url);
    } catch (_err) {
      renderWsStatus("offline", "err");
      reconnectTimer = setTimeout(connectWebSocket, 1500);
      return;
    }

    socket.addEventListener("open", function () {
      state.wsConnected = true;
      resetRouteView();
      renderWsStatus("connected", "ok");
    });

    socket.addEventListener("message", function (ev) {
      try {
        var payload = JSON.parse(ev.data);
        handleServerMessage(payload);
      } catch (_err) {
        // Ignore malformed payloads.
      }
    });

    socket.addEventListener("close", function () {
      state.wsConnected = false;
      renderWsStatus("reconnecting", "warn");
      reconnectTimer = setTimeout(connectWebSocket, 1500);
    });

    socket.addEventListener("error", function () {
      renderWsStatus("offline", "err");
    });
  }

  function sendCommand(text) {
    var trimmed = (text || "").trim();
    if (!trimmed) {
      return;
    }
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "command", text: trimmed }));
    } else {
      els.sayBox.textContent = "WebSocket not connected — start `python3 -m web.ws_server --sim`.";
    }
  }

  // --- UI Interactions ------------------------------------------------------
  els.cmdForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    sendCommand(els.cmdInput.value);
    els.cmdInput.value = "";
  });

  var chips = document.querySelectorAll(".chip[data-cmd]");
  for (var i = 0; i < chips.length; i++) {
    (function (btn) {
      btn.addEventListener("click", function () {
        sendCommand(btn.getAttribute("data-cmd") || "");
      });
    })(chips[i]);
  }

  els.fitBtn.addEventListener("click", function () {
    drawMap();
  });

  els.themeBtn.addEventListener("click", function () {
    var root = document.documentElement;
    var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    els.themeBtn.textContent = next === "light" ? "Dark Theme" : "Light Theme";
    drawMap();
  });

  window.addEventListener("resize", drawMap);

  renderMode();
  renderLink();
  applyLedState("idle", null);
  renderPoseOverlay();
  renderGuidance();
  renderLandmarks();
  drawMap();
  connectWebSocket();
})();
