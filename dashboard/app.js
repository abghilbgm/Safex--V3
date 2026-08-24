/* ============================================================
   SENTINEL Dashboard — client logic
   ============================================================ */

const API = {
  cameras: "/api/cameras", areaGroups: "/api/area-groups", violations: "/api/violations",
  stats: "/api/stats", rules: "/api/rules",
};
const state = { cameras: [], areaGroups: [], rules: [], wsEventsConnected: false, videoSockets: {} };

document.addEventListener("DOMContentLoaded", async () => {
  startClock();
  await loadAreaGroups();
  await loadCameras();
  connectEventStream();
  await refreshStats();
  await refreshRules();
  setupTabs();
  setupRuleModal();
  setupLightbox();
  setupViolationsGallery();
  setupCameraModal();
  setupGroupsModal();
  setupReconnectAll();
  setInterval(refreshStats, 15000);
  setInterval(refreshCameraStatuses, 8000);
});

function startClock() {
  const el = document.getElementById("liveClock");
  const tick = () => { el.textContent = new Date().toLocaleTimeString(); };
  tick(); setInterval(tick, 1000);
}

// ---------------------------------------------------------------
// Area Groups
// ---------------------------------------------------------------
async function loadAreaGroups() {
  try { const res = await fetch(API.areaGroups); state.areaGroups = await res.json(); }
  catch (e) { state.areaGroups = []; }
  populateAreaGroupSelects();
}

function populateAreaGroupSelects() {
  const targets = [document.getElementById("camAreaGroup"), document.getElementById("violationAreaGroupFilter")];
  targets.forEach((select) => {
    if (!select) return;
    const currentValue = select.value;
    const placeholder = select === document.getElementById("violationAreaGroupFilter")
      ? '<option value="">All Area Groups</option>' : '<option value="">Unassigned</option>';
    select.innerHTML = placeholder;
    state.areaGroups.forEach((g) => {
      const opt = document.createElement("option");
      opt.value = g.id; opt.textContent = g.name; select.appendChild(opt);
    });
    select.value = currentValue || "";
  });
}

function setupGroupsModal() {
  const backdrop = document.getElementById("groupsModalBackdrop");
  document.getElementById("btnManageGroups").addEventListener("click", () => {
    renderGroupsTable(); backdrop.classList.add("open");
  });
  document.getElementById("btnCloseGroups").addEventListener("click", () => backdrop.classList.remove("open"));
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) backdrop.classList.remove("open"); });
  document.getElementById("btnAddGroup").addEventListener("click", async () => {
    const name = document.getElementById("newGroupName").value.trim();
    const description = document.getElementById("newGroupDesc").value.trim();
    if (!name) return;
    await fetch(API.areaGroups, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, description }) });
    document.getElementById("newGroupName").value = ""; document.getElementById("newGroupDesc").value = "";
    await loadAreaGroups(); renderGroupsTable(); await loadCameras();
  });
}

function renderGroupsTable() {
  const tbody = document.getElementById("groupsTableBody"); tbody.innerHTML = "";
  state.areaGroups.forEach((g) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${g.name}</td><td>${g.description || "<span style='color:var(--text-dim)'>—</span>"}</td><td>${g.camera_count ?? 0}</td><td><button class="icon-btn danger" data-delete-group="${g.id}">Delete</button></td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll("[data-delete-group]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this area group? Cameras assigned to it will become unassigned.")) return;
      await fetch(`${API.areaGroups}/${btn.dataset.deleteGroup}`, { method: "DELETE" });
      await loadAreaGroups(); renderGroupsTable(); await loadCameras();
    }));
}

// ---------------------------------------------------------------
// Cameras: list + Feeds rendering
// ---------------------------------------------------------------
async function loadCameras() {
  const grid = document.getElementById("feedsByGroup");
  try {
    const res = await fetch(API.cameras);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    state.cameras = await res.json();
  } catch (e) {
    console.error("Failed to load cameras:", e);
    state.cameras = [];
    grid.innerHTML = `<div class="error-state">Could not load cameras.<div class="error-detail">${escapeHtml(e.message)}</div></div>`;
    return;
  }

  renderFeedsGroupedByArea();
  renderCamerasTable();
  populateViolationCameraFilter();

  document.getElementById("statCamerasOnline").textContent = `${state.cameras.filter(c => c.connected).length}/${state.cameras.length}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function populateViolationCameraFilter() {
  const select = document.getElementById("violationCameraFilter");
  const currentValue = select.value;
  select.innerHTML = '<option value="">All Cameras</option>';
  state.cameras.forEach((cam) => {
    const opt = document.createElement("option"); opt.value = cam.camera_id; opt.textContent = cam.name; select.appendChild(opt);
  });
  select.value = currentValue || "";
}

// FIX: "not all cameras loaded in frontend" - previously a single malformed
// camera object (or a DOM/template error for one tile) could throw and
// abort the whole forEach loop, silently skipping every camera after the
// broken one. Each camera's tile is now built inside its own try/catch so
// one bad camera can NEVER prevent the rest from rendering.
function renderFeedsGroupedByArea() {
  const container = document.getElementById("feedsByGroup");
  container.innerHTML = "";

  const groups = {};
  state.cameras.forEach((cam) => {
    const key = cam.area_group_name || "Unassigned";
    if (!groups[key]) groups[key] = [];
    groups[key].push(cam);
  });

  const groupNames = Object.keys(groups).sort((a, b) => {
    if (a === "Unassigned") return 1; if (b === "Unassigned") return -1; return a.localeCompare(b);
  });

  if (!groupNames.length) {
    container.innerHTML = `<div class="event-empty">No cameras configured yet. Use the Cameras tab to add one.</div>`;
    return;
  }

  groupNames.forEach((groupName) => {
    const cams = groups[groupName];
    const section = document.createElement("div"); section.className = "feed-group";
    section.innerHTML = `<div class="feed-group-header"><h4>${escapeHtml(groupName)}</h4><span class="feed-group-count">${cams.length} camera${cams.length !== 1 ? "s" : ""}</span></div><div class="camera-grid"></div>`;
    container.appendChild(section);
    const grid = section.querySelector(".camera-grid");

    cams.forEach((cam) => {
      try {
        const tile = buildCameraTile(cam);
        grid.appendChild(tile);
        connectVideoStream(cam.camera_id);
      } catch (err) {
        // A single bad camera must never stop the others from rendering.
        console.error(`Failed to render tile for camera ${cam && cam.camera_id}:`, err);
        const errorTile = document.createElement("div");
        errorTile.className = "camera-tile";
        errorTile.innerHTML = `<div class="error-state" style="padding:20px;">Failed to render this camera tile.<div class="error-detail">${escapeHtml(String(err))}</div></div>`;
        grid.appendChild(errorTile);
      }
    });
  });
}

function buildCameraTile(cam) {
  const tile = document.createElement("div");
  tile.className = "camera-tile";
  tile.id = `tile-${cam.camera_id}`;
  tile.innerHTML = `
    <div class="feed-wrap">
      <canvas id="canvas-${cam.camera_id}"></canvas>
      <div class="feed-placeholder" id="placeholder-${cam.camera_id}">Connecting…</div>
      <div class="violation-flash" id="flash-${cam.camera_id}"></div>
    </div>
    <div class="tile-footer">
      <div>
        <span class="tile-cam-name">${escapeHtml(cam.name)}</span>
        <span class="tile-cam-zone">${escapeHtml(cam.camera_id)}</span>
      </div>
      <div class="tile-actions">
        <div class="tile-status ${cam.connected ? "online" : "offline"}" id="status-${cam.camera_id}">
          <span class="dot"></span><span>${cam.connected ? "ONLINE" : "OFFLINE"}</span>
        </div>
        <button class="tile-reconnect-btn" data-reconnect-tile="${cam.camera_id}" title="Reconnect this camera (useful for PTZ cameras that pan/zoom)">↻</button>
      </div>
    </div>
  `;
  tile.querySelector(`[data-reconnect-tile="${cam.camera_id}"]`).addEventListener("click", (e) => {
    e.stopPropagation();
    reconnectSingleCamera(cam.camera_id);
  });
  return tile;
}

// The per-tile "↻" Reconnect button - forces this ONE camera's stream to
// restart immediately, without touching any other camera. This is what
// you want for a PTZ camera that appears "stuck"/reconnecting after it
// pans - instead of waiting for the automatic backoff retry.
async function reconnectSingleCamera(cameraId) {
  const btn = document.querySelector(`[data-reconnect-tile="${cameraId}"]`);
  if (btn) { btn.disabled = true; btn.classList.add("spinning"); }
  const placeholder = document.getElementById(`placeholder-${cameraId}`);
  if (placeholder) { placeholder.style.display = "block"; placeholder.textContent = "Reconnecting…"; }
  try {
    await fetch(`${API.cameras}/${cameraId}/refresh`, { method: "POST" });
    await new Promise((r) => setTimeout(r, 1000));
    connectVideoStream(cameraId);
    await refreshCameraStatuses();
  } catch (e) {
    console.error(`Reconnect failed for ${cameraId}:`, e);
  } finally {
    if (btn) { btn.disabled = false; btn.classList.remove("spinning"); }
  }
}

function setupReconnectAll() {
  document.getElementById("btnReconnectAll").addEventListener("click", async () => {
    const btn = document.getElementById("btnReconnectAll");
    btn.disabled = true;
    btn.textContent = "Reconnecting all cameras…";
    try {
      // Reconnect cameras with a small stagger so we don't hit the backend
      // with 16 simultaneous stream restarts at once.
      for (const cam of state.cameras) {
        fetch(`${API.cameras}/${cam.camera_id}/refresh`, { method: "POST" }).catch(() => {});
        await new Promise((r) => setTimeout(r, 150));
      }
      await new Promise((r) => setTimeout(r, 1500));
      state.cameras.forEach((cam) => connectVideoStream(cam.camera_id));
      await loadCameras();
    } finally {
      btn.disabled = false;
      btn.textContent = "↻ Reconnect All Cameras";
    }
  });
}

function connectVideoStream(cameraId) {
  if (state.videoSockets[cameraId]) {
    try { state.videoSockets[cameraId].close(); } catch (e) {}
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/video/${cameraId}`);
  ws.binaryType = "arraybuffer";
  state.videoSockets[cameraId] = ws;

  const canvas = document.getElementById(`canvas-${cameraId}`);
  if (!canvas) return;
  const placeholder = document.getElementById(`placeholder-${cameraId}`);
  const ctx = canvas.getContext("2d");

  ws.onmessage = async (event) => {
    try {
      const blob = new Blob([event.data], { type: "image/jpeg" });
      const bitmap = await createImageBitmap(blob);
      if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
        canvas.width = bitmap.width; canvas.height = bitmap.height;
      }
      ctx.drawImage(bitmap, 0, 0);
      bitmap.close();
      if (placeholder) placeholder.style.display = "none";
    } catch (e) { /* stray partial frame - next one recovers */ }
  };

  ws.onclose = () => {
    if (document.getElementById(`placeholder-${cameraId}`)) {
      const p = document.getElementById(`placeholder-${cameraId}`);
      p.style.display = "block"; p.textContent = "Reconnecting…";
    }
    setTimeout(() => { if (document.getElementById(`canvas-${cameraId}`)) connectVideoStream(cameraId); }, 2000);
  };
  ws.onerror = () => ws.close();
}

async function refreshCameraStatuses() {
  try {
    const res = await fetch(API.cameras);
    if (!res.ok) return;
    const cams = await res.json();
    state.cameras = cams;
    cams.forEach((cam) => {
      const statusEl = document.getElementById(`status-${cam.camera_id}`);
      if (!statusEl) return;
      statusEl.className = `tile-status ${cam.connected ? "online" : "offline"}`;
      statusEl.querySelector("span:last-child").textContent = cam.connected ? "ONLINE" : "OFFLINE";
    });
    document.getElementById("statCamerasOnline").textContent = `${cams.filter(c => c.connected).length}/${cams.length}`;
    renderCamerasTable();
  } catch (e) { /* transient network blip - next poll will retry */ }
}

function renderCamerasTable() {
  const tbody = document.getElementById("camerasTableBody"); if (!tbody) return; tbody.innerHTML = "";
  state.cameras.forEach((cam) => {
    try {
      const tr = document.createElement("tr");
      const ppeTags = (cam.required_ppe || []).map(p => `<span class="ppe-tag">${escapeHtml(p)}</span>`).join("");
      tr.innerHTML = `<td><code>${escapeHtml(cam.camera_id)}</code></td><td>${escapeHtml(cam.name)}</td><td>${cam.area_group_name ? escapeHtml(cam.area_group_name) : "<span style='color:var(--text-dim)'>Unassigned</span>"}</td><td><div class="ppe-tag-list">${ppeTags}</div></td><td><span class="tile-status ${cam.connected ? "online" : "offline"}"><span class="dot"></span>${cam.connected ? "ONLINE" : "OFFLINE"}</span></td><td><span class="state-pill ${cam.worker_running ? "running" : "stopped"}">${cam.worker_running ? "RUNNING" : "STOPPED"}</span></td><td><button class="icon-btn" data-refresh-cam="${cam.camera_id}">↻ Refresh</button><button class="icon-btn" data-edit-cam="${cam.camera_id}">Edit</button><button class="icon-btn danger" data-delete-cam="${cam.camera_id}">Delete</button></td>`;
      tbody.appendChild(tr);
    } catch (err) {
      console.error(`Failed to render camera table row for ${cam && cam.camera_id}:`, err);
    }
  });
  tbody.querySelectorAll("[data-refresh-cam]").forEach(btn => btn.addEventListener("click", () => refreshCameraConnection(btn.dataset.refreshCam)));
  tbody.querySelectorAll("[data-edit-cam]").forEach(btn => btn.addEventListener("click", () => openCameraModal(btn.dataset.editCam)));
  tbody.querySelectorAll("[data-delete-cam]").forEach(btn => btn.addEventListener("click", () => deleteCamera(btn.dataset.deleteCam)));
}

async function refreshCameraConnection(cameraId) {
  const btn = document.querySelector(`[data-refresh-cam="${cameraId}"]`);
  if (btn) { btn.textContent = "Refreshing…"; btn.disabled = true; }
  try {
    await fetch(`${API.cameras}/${cameraId}/refresh`, { method: "POST" });
    await new Promise(r => setTimeout(r, 800));
    connectVideoStream(cameraId);
    await loadCameras();
  } finally { if (btn) { btn.textContent = "↻ Refresh"; btn.disabled = false; } }
}

async function deleteCamera(cameraId) {
  if (!confirm(`Delete camera ${cameraId}? This stops its stream and removes it permanently.`)) return;
  await fetch(`${API.cameras}/${cameraId}`, { method: "DELETE" });
  await loadCameras();
}

// ---------------------------------------------------------------
// Camera Add/Edit Modal
// ---------------------------------------------------------------
function setupCameraModal() {
  const backdrop = document.getElementById("cameraModalBackdrop");
  document.getElementById("btnNewCamera").addEventListener("click", () => openCameraModal(null));
  document.getElementById("btnCancelCamera").addEventListener("click", () => backdrop.classList.remove("open"));
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) backdrop.classList.remove("open"); });
  document.getElementById("cameraForm").addEventListener("submit", async (e) => {
    e.preventDefault(); await saveCamera(); backdrop.classList.remove("open"); await loadCameras();
  });
}

async function openCameraModal(cameraId) {
  const backdrop = document.getElementById("cameraModalBackdrop");
  const isEdit = !!cameraId;
  document.getElementById("cameraModalTitle").textContent = isEdit ? `Edit Camera — ${cameraId}` : "Add Camera";
  const idField = document.getElementById("camCameraId"); idField.disabled = isEdit;
  if (isEdit) {
    const res = await fetch(`${API.cameras}/${cameraId}`); const cam = await res.json();
    idField.value = cam.camera_id;
    document.getElementById("camName").value = cam.name;
    document.getElementById("camRtspUrl").value = cam.rtsp_url;
    document.getElementById("camAreaGroup").value = cam.area_group_id || "";
    document.getElementById("camEnabled").checked = cam.enabled;
    const ppe = cam.required_ppe || [];
    document.getElementById("ppeHelmet").checked = ppe.includes("helmet");
    document.getElementById("ppeVest").checked = ppe.includes("vest");
    document.getElementById("ppeMask").checked = ppe.includes("mask");
    document.getElementById("ppeGloves").checked = ppe.includes("gloves");
    document.getElementById("ppeBoots").checked = ppe.includes("boots");
    document.getElementById("ppeGoggles").checked = ppe.includes("goggles");
  } else {
    document.getElementById("cameraForm").reset(); idField.value = "";
    document.getElementById("ppeHelmet").checked = true; document.getElementById("ppeVest").checked = true;
    document.getElementById("camEnabled").checked = true;
  }
  backdrop.classList.add("open");
}

async function saveCamera() {
  const cameraId = document.getElementById("camCameraId").value.trim();
  const isEdit = document.getElementById("camCameraId").disabled;
  const requiredPpe = [];
  if (document.getElementById("ppeHelmet").checked) requiredPpe.push("helmet");
  if (document.getElementById("ppeVest").checked) requiredPpe.push("vest");
  if (document.getElementById("ppeMask").checked) requiredPpe.push("mask");
  if (document.getElementById("ppeGloves").checked) requiredPpe.push("gloves");
  if (document.getElementById("ppeBoots").checked) requiredPpe.push("boots");
  if (document.getElementById("ppeGoggles").checked) requiredPpe.push("goggles");
  const areaGroupVal = document.getElementById("camAreaGroup").value;
  if (isEdit) {
    const payload = { name: document.getElementById("camName").value, rtsp_url: document.getElementById("camRtspUrl").value, area_group_id: areaGroupVal ? parseInt(areaGroupVal, 10) : null, required_ppe: requiredPpe, enabled: document.getElementById("camEnabled").checked };
    await fetch(`${API.cameras}/${cameraId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } else {
    const payload = { camera_id: cameraId, name: document.getElementById("camName").value, rtsp_url: document.getElementById("camRtspUrl").value, area_group_id: areaGroupVal ? parseInt(areaGroupVal, 10) : null, required_ppe: requiredPpe, enabled: document.getElementById("camEnabled").checked };
    const res = await fetch(API.cameras, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!res.ok) { const err = await res.json(); alert(`Failed to add camera: ${err.detail || res.statusText}`); }
  }
}

// ---------------------------------------------------------------
// Live Violation Event Feed (WebSocket)
// ---------------------------------------------------------------
function connectEventStream() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/events`);
  const dot = document.getElementById("wsConnDot");
  ws.onopen = () => { state.wsEventsConnected = true; dot.classList.add("connected"); };
  ws.onclose = () => { state.wsEventsConnected = false; dot.classList.remove("connected"); setTimeout(connectEventStream, 2000); };
  ws.onerror = () => ws.close();
  ws.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    if (event.type === "violation") { renderViolationEvent(event); flashCameraTile(event.camera_id); bumpViolationCounter(); }
  };
}

function renderViolationEvent(event) {
  const feed = document.getElementById("eventFeed");
  const empty = feed.querySelector(".event-empty"); if (empty) empty.remove();
  const item = document.createElement("div"); item.className = "event-item";
  const label = (event.violation_type || "").replace("no_", "Missing ").replace("_", " ");
  const snapshotUrl = event.snapshot_url || (event.violation_id ? `/api/snapshot/${event.violation_id}` : null);
  item.innerHTML = `${snapshotUrl ? `<img class="ev-thumb" src="${snapshotUrl}" alt="violation snapshot" loading="lazy" />` : `<div class="ev-thumb"></div>`}<div class="ev-body"><div class="ev-top"><span class="ev-type">${label.toUpperCase()}</span><span class="ev-time">${event.timestamp || ""}</span></div><div class="ev-meta">${escapeHtml(event.camera_name || event.camera_id)} · ${escapeHtml(event.area_group || event.zone || "")}</div>${event.rules_matched && event.rules_matched.length ? `<div class="ev-rules">⚡ ${escapeHtml(event.rules_matched.join(", "))}</div>` : `<div class="ev-rules" style="color:var(--text-dim)">No matching alert rule</div>`}</div>`;
  if (snapshotUrl) { item.addEventListener("click", () => openLightbox(snapshotUrl, `${event.camera_name || event.camera_id} · ${event.area_group || event.zone || ""} · ${label} · ${event.timestamp || ""}`)); }
  feed.insertBefore(item, feed.firstChild);
  const items = feed.querySelectorAll(".event-item"); if (items.length > 100) items[items.length - 1].remove();
}

function flashCameraTile(cameraId) {
  const flash = document.getElementById(`flash-${cameraId}`); if (!flash) return;
  flash.classList.remove("active"); void flash.offsetWidth; flash.classList.add("active");
}

function bumpViolationCounter() {
  const el = document.getElementById("statViolations24h"); const current = parseInt(el.textContent, 10);
  if (!isNaN(current)) el.textContent = current + 1;
}

// ---------------------------------------------------------------
// Violations Gallery Tab - now with clear error state + Retry
// ---------------------------------------------------------------
function setupViolationsGallery() {
  document.getElementById("btnRefreshViolations").addEventListener("click", loadViolationsGallery);
  document.getElementById("violationCameraFilter").addEventListener("change", loadViolationsGallery);
  document.getElementById("violationAreaGroupFilter").addEventListener("change", loadViolationsGallery);
  document.getElementById("violationTypeFilter").addEventListener("change", loadViolationsGallery);
}

async function loadViolationsGallery() {
  const gallery = document.getElementById("violationsGallery");
  gallery.innerHTML = `<div class="event-empty">Loading violations…</div>`;

  const cameraId = document.getElementById("violationCameraFilter").value;
  const areaGroupId = document.getElementById("violationAreaGroupFilter").value;
  const violationType = document.getElementById("violationTypeFilter").value;

  const params = new URLSearchParams({ limit: "60" });
  if (cameraId) params.set("camera_id", cameraId);
  if (areaGroupId) params.set("area_group_id", areaGroupId);
  if (violationType) params.set("violation_type", violationType);

  let rows = [];
  try {
    const res = await fetch(`${API.violations}?${params.toString()}`);
    if (!res.ok) {
      // Backend now returns a clear JSON {detail: "..."} on DB errors
      // (see main.py) instead of an opaque 500 - surface that message
      // directly instead of a generic "failed to load".
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    rows = await res.json();
  } catch (e) {
    gallery.innerHTML = `
      <div class="error-state">
        Could not load violations.
        <div class="error-detail">${escapeHtml(e.message)}</div>
        <button class="btn-secondary" onclick="loadViolationsGallery()">↻ Retry</button>
      </div>`;
    return;
  }

  if (!rows.length) {
    gallery.innerHTML = `<div class="event-empty">No violations found for this filter.</div>`;
    return;
  }

  gallery.innerHTML = "";
  rows.forEach((row) => {
    try {
      const card = document.createElement("div"); card.className = "violation-card";
      const label = (row.violation_type || "").replace("no_", "Missing ").replace("_", " ");
      const snapshotUrl = row.snapshot_url;
      const detectedAt = row.detected_at ? new Date(row.detected_at).toLocaleString() : "";
      card.innerHTML = `<div class="thumb-wrap">${snapshotUrl ? `<img src="${snapshotUrl}" alt="${escapeHtml(label)}" loading="lazy" />` : `<div class="thumb-placeholder">No image</div>`}<span class="thumb-badge">${label.toUpperCase()}</span></div><div class="card-meta"><div class="card-cam">${escapeHtml(row.camera_name || row.camera_id)}</div><div class="card-time">${escapeHtml(row.area_group || row.zone || "")} · ${detectedAt}</div></div>`;
      if (snapshotUrl) { card.addEventListener("click", () => openLightbox(snapshotUrl, `${row.camera_name || row.camera_id} · ${row.area_group || row.zone || ""} · ${label} · ${detectedAt}`)); }
      gallery.appendChild(card);
    } catch (err) {
      console.error("Failed to render a violation card:", err);
    }
  });
}

// ---------------------------------------------------------------
// Lightbox
// ---------------------------------------------------------------
function setupLightbox() {
  document.getElementById("lightboxClose").addEventListener("click", closeLightbox);
  document.getElementById("lightboxBackdrop").addEventListener("click", (e) => { if (e.target.id === "lightboxBackdrop") closeLightbox(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLightbox(); });
}
function openLightbox(imageUrl, caption) {
  document.getElementById("lightboxImage").src = imageUrl;
  document.getElementById("lightboxCaption").textContent = caption || "";
  document.getElementById("lightboxBackdrop").classList.add("open");
}
function closeLightbox() {
  document.getElementById("lightboxBackdrop").classList.remove("open");
  document.getElementById("lightboxImage").src = "";
}

// ---------------------------------------------------------------
// Stats + Custom Canvas Charts
// ---------------------------------------------------------------
async function refreshStats() {
  try {
    const res = await fetch(`${API.stats}?window_hours=24`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const stats = await res.json();
    document.getElementById("statViolations24h").textContent = stats.total_violations ?? "0";
    drawHourlyChart(stats.hourly || []); drawTypeChart(stats.by_type || []); drawAreaGroupChart(stats.by_area_group || []);
  } catch (e) { console.error("stats refresh failed", e); }
}

function drawHourlyChart(hourly) {
  const canvas = document.getElementById("hourlyChart"); const ctx = prepCanvas(canvas);
  const w = canvas.width, h = canvas.height;
  if (!hourly.length) { drawEmptyState(ctx, w, h); return; }
  const counts = hourly.map(d => d.count); const max = Math.max(...counts, 1); const barW = w / hourly.length;
  ctx.strokeStyle = "#1f2733"; ctx.beginPath(); ctx.moveTo(0, h - 20); ctx.lineTo(w, h - 20); ctx.stroke();
  hourly.forEach((d, i) => {
    const barH = (d.count / max) * (h - 40); const x = i * barW + barW * 0.15;
    const grad = ctx.createLinearGradient(0, h - 20 - barH, 0, h - 20);
    grad.addColorStop(0, "#29d3d9"); grad.addColorStop(1, "#155a5d");
    ctx.fillStyle = grad; ctx.fillRect(x, h - 20 - barH, barW * 0.7, barH);
  });
  ctx.fillStyle = "#5a6578"; ctx.font = "10px monospace";
  ctx.fillText(hourly[0]?.hour?.slice(11, 16) || "", 2, h - 6);
  ctx.fillText(hourly[hourly.length - 1]?.hour?.slice(11, 16) || "", w - 40, h - 6);
}

function drawTypeChart(byType) {
  const canvas = document.getElementById("typeChart"); const ctx = prepCanvas(canvas);
  const w = canvas.width, h = canvas.height;
  if (!byType.length) { drawEmptyState(ctx, w, h); return; }
  const colors = ["#ef4b4b", "#f2a900", "#29d3d9", "#33d17a", "#a78bfa", "#f472b6"];
  const total = byType.reduce((s, d) => s + Number(d.c), 0) || 1;
  const cx = w / 2, cy = h / 2, radius = Math.min(w, h) / 2 - 10; let angleStart = -Math.PI / 2;
  byType.forEach((d, i) => {
    const slice = (Number(d.c) / total) * Math.PI * 2;
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, radius, angleStart, angleStart + slice); ctx.closePath();
    ctx.fillStyle = colors[i % colors.length]; ctx.fill(); angleStart += slice;
  });
  ctx.font = "11px sans-serif";
  byType.forEach((d, i) => {
    const ly = 14 + i * 16;
    ctx.fillStyle = colors[i % colors.length]; ctx.fillRect(w - 118, ly - 9, 9, 9);
    ctx.fillStyle = "#8b96a8"; ctx.fillText(`${d.violation_type} (${d.c})`, w - 104, ly);
  });
}

function drawAreaGroupChart(byAreaGroup) {
  const canvas = document.getElementById("areaGroupChart"); const ctx = prepCanvas(canvas);
  const w = canvas.width, h = canvas.height;
  if (!byAreaGroup.length) { drawEmptyState(ctx, w, h); return; }
  const max = Math.max(...byAreaGroup.map(d => Number(d.c)), 1);
  const barH = Math.min(28, (h - 20) / byAreaGroup.length);
  byAreaGroup.forEach((d, i) => {
    const y = i * (barH + 8) + 6; const barW = (Number(d.c) / max) * (w - 140);
    const grad = ctx.createLinearGradient(0, 0, barW, 0);
    grad.addColorStop(0, "#f2a900"); grad.addColorStop(1, "#8a5f00");
    ctx.fillStyle = grad; ctx.fillRect(120, y, Math.max(barW, 2), barH * 0.7);
    ctx.fillStyle = "#8b96a8"; ctx.font = "11px sans-serif"; ctx.textAlign = "right";
    ctx.fillText((d.area_group || "").slice(0, 16), 112, y + barH * 0.55);
    ctx.textAlign = "left"; ctx.fillStyle = "#e8ecf1"; ctx.font = "11px monospace";
    ctx.fillText(String(d.c), 126 + barW, y + barH * 0.55);
  });
}

function prepCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const cssW = rect.width || canvas.parentElement.clientWidth || 300;
  const cssH = canvas.height || 160;
  canvas.width = cssW * dpr; canvas.height = cssH * dpr;
  canvas.style.width = cssW + "px"; canvas.style.height = cssH + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, cssW, cssH);
  canvas.width = cssW; canvas.height = cssH; ctx.setTransform(1, 0, 0, 1, 0, 0);
  return ctx;
}

function drawEmptyState(ctx, w, h) {
  ctx.fillStyle = "#5a6578"; ctx.font = "12px sans-serif"; ctx.textAlign = "center";
  ctx.fillText("No data yet", w / 2, h / 2); ctx.textAlign = "left";
}

// ---------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------
function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
      if (btn.dataset.tab === "analytics") refreshStats();
      if (btn.dataset.tab === "rules") refreshRules();
      if (btn.dataset.tab === "violations") loadViolationsGallery();
      if (btn.dataset.tab === "cameras") renderCamerasTable();
    });
  });
}

// ---------------------------------------------------------------
// Alert Rules CRUD
// ---------------------------------------------------------------
async function refreshRules() {
  try {
    const res = await fetch(API.rules);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.rules = await res.json();
  } catch (e) { state.rules = []; }

  document.getElementById("statActiveRules").textContent = state.rules.filter(r => r.enabled).length;
  const tbody = document.getElementById("rulesTableBody"); tbody.innerHTML = "";
  state.rules.forEach((rule) => {
    const tr = document.createElement("tr");
    const channels = (rule.channels || []).map(c => `<span class="chan-pill">${escapeHtml(c)}</span>`).join("");
    tr.innerHTML = `<td>${escapeHtml(rule.name)}</td><td>${rule.camera_id || "<span style='color:var(--text-dim)'>any</span>"}</td><td>${rule.zone || "<span style='color:var(--text-dim)'>any</span>"}</td><td>${rule.violation_type || "<span style='color:var(--text-dim)'>any</span>"}</td><td>${channels}</td><td>${rule.cooldown_seconds}s</td><td><span class="badge ${rule.enabled ? "on" : "off"}">${rule.enabled ? "ENABLED" : "DISABLED"}</span></td><td><button class="icon-btn" data-edit="${rule.id}">Edit</button><button class="icon-btn danger" data-delete="${rule.id}">Delete</button></td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll("[data-edit]").forEach(btn => btn.addEventListener("click", () => openRuleModal(Number(btn.dataset.edit))));
  tbody.querySelectorAll("[data-delete]").forEach(btn => btn.addEventListener("click", () => deleteRule(Number(btn.dataset.delete))));
}

function setupRuleModal() {
  const backdrop = document.getElementById("ruleModalBackdrop");
  document.getElementById("btnNewRule").addEventListener("click", () => openRuleModal(null));
  document.getElementById("btnCancelRule").addEventListener("click", () => backdrop.classList.remove("open"));
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) backdrop.classList.remove("open"); });
  document.getElementById("ruleForm").addEventListener("submit", async (e) => {
    e.preventDefault(); await saveRule(); backdrop.classList.remove("open"); refreshRules();
  });
}

function openRuleModal(ruleId) {
  const backdrop = document.getElementById("ruleModalBackdrop");
  const rule = ruleId ? state.rules.find(r => r.id === ruleId) : null;
  document.getElementById("ruleModalTitle").textContent = rule ? "Edit Alert Rule" : "New Alert Rule";
  document.getElementById("ruleId").value = rule ? rule.id : "";
  document.getElementById("ruleName").value = rule ? rule.name : "";
  document.getElementById("ruleCameraId").value = rule ? (rule.camera_id || "") : "";
  document.getElementById("ruleZone").value = rule ? (rule.zone || "") : "";
  document.getElementById("ruleViolationType").value = rule ? (rule.violation_type || "") : "";
  document.getElementById("ruleCooldown").value = rule ? rule.cooldown_seconds : 300;
  document.getElementById("chanTeams").checked = rule ? rule.channels.includes("teams") : true;
  document.getElementById("chanEmail").checked = rule ? rule.channels.includes("email") : false;
  document.getElementById("ruleEnabled").checked = rule ? rule.enabled : true;
  document.getElementById("ruleEmailRecipients").value = rule ? (rule.email_recipients || []).join(", ") : "";
  backdrop.classList.add("open");
}

async function saveRule() {
  const id = document.getElementById("ruleId").value;
  const channels = [];
  if (document.getElementById("chanTeams").checked) channels.push("teams");
  if (document.getElementById("chanEmail").checked) channels.push("email");
  const payload = {
    name: document.getElementById("ruleName").value,
    camera_id: document.getElementById("ruleCameraId").value || null,
    zone: document.getElementById("ruleZone").value || null,
    violation_type: document.getElementById("ruleViolationType").value || null,
    cooldown_seconds: parseInt(document.getElementById("ruleCooldown").value, 10),
    channels, enabled: document.getElementById("ruleEnabled").checked,
    email_recipients: document.getElementById("ruleEmailRecipients").value.split(",").map(s => s.trim()).filter(Boolean),
  };
  const url = id ? `${API.rules}/${id}` : API.rules;
  const method = id ? "PUT" : "POST";
  await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

async function deleteRule(id) {
  if (!confirm("Delete this alert rule?")) return;
  await fetch(`${API.rules}/${id}`, { method: "DELETE" });
  refreshRules();
}
