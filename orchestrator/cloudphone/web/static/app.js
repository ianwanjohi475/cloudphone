const $ = (s) => document.querySelector(s);
const rows = $("#rows");
let phones = {};

async function api(path, opts) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function badge(status) {
  return `<span class="badge ${status}">${status}</span>`;
}

async function load() {
  rows.innerHTML = `<tr><td colspan="9" class="muted">Loading…</td></tr>`;
  let data;
  try {
    data = await api("/api/phones");
  } catch (e) {
    rows.innerHTML = `<tr><td colspan="9" class="muted">Error: ${e.message}</td></tr>`;
    return;
  }
  if (!data.phones.length) {
    rows.innerHTML = `<tr><td colspan="9" class="muted">No phones yet. Create one ↑</td></tr>`;
    return;
  }
  phones = Object.fromEntries(data.phones.map((p) => [p.name, p]));
  rows.innerHTML = data.phones.map((p) => {
    const h = p.health || {};
    const tag = p.engine === "emulator" ? "real phone" : "redroid";
    return `<tr>
      <td><b>${p.name}</b><span class="tag">${tag}</span></td>
      <td>${badge(p.status)}</td>
      <td>${p.profile}</td>
      <td class="muted">${p.proxy || "-"}</td>
      <td>${h.booted ? "✓" : "—"}</td>
      <td>${h.cpu_pct ?? "—"}</td>
      <td>${h.mem_mb ? Math.round(h.mem_mb) + "M" : "—"}</td>
      <td>${h.crashes_recent ?? "—"}</td>
      <td class="controls">
        <button data-view="${p.name}">View</button>
        <button data-tools="${p.name}">Apps &amp; camera</button>
        <button data-action="restart" data-name="${p.name}">Restart</button>
        <button data-action="${p.status === "running" ? "stop" : "start"}" data-name="${p.name}">
          ${p.status === "running" ? "Stop" : "Start"}</button>
        <button class="danger" data-action="destroy" data-name="${p.name}">Del</button>
      </td>
    </tr>`;
  }).join("");
}

rows.addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  if (btn.dataset.view) return openViewer(btn.dataset.view);
  if (btn.dataset.tools) return openTools(btn.dataset.tools);
  const { action, name } = btn.dataset;
  if (!action) return;
  if (action === "destroy" && !confirm(`Delete ${name}?`)) return;
  btn.disabled = true;
  try {
    await api(`/api/phones/${name}/${action}`, { method: "POST" });
  } catch (err) {
    alert(err.message);
  }
  load();
});

$("#create").addEventListener("click", async () => {
  const body = JSON.stringify({
    count: Number($("#count").value || 1),
    profile: $("#profile").value,
    engine: $("#engine").value,
  });
  $("#create").disabled = true;
  try {
    await api("/api/phones", { method: "POST", body });
  } catch (e) {
    alert(e.message);
  }
  $("#create").disabled = false;
  load();
});

$("#refresh").addEventListener("click", load);

// ws-scrcpy viewer — opens the device in the embedded scrcpy client.
function openViewer(name) {
  const host = location.hostname;
  const udid = encodeURIComponent((phones[name] && phones[name].adb_address) || `${name}:5555`);
  const url = `http://${host}:${window.SCRCPY_PORT}/#!action=stream&udid=${udid}&player=broadway&ws=ws%3A%2F%2F${host}%3A${window.SCRCPY_PORT}%2F`;
  $("#viewer-title").textContent = name;
  $("#scrcpy").src = url;
  $("#viewer").classList.remove("hidden");
}
$("#viewer-close").addEventListener("click", () => {
  $("#viewer").classList.add("hidden");
  $("#scrcpy").src = "about:blank";
});

// ------------------------------------------------------------ apps & camera panel
let current = null;

function esc(t) {
  return String(t).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function setStatus(el, text, kind = "") {
  el.className = `status ${kind}`;
  el.textContent = text;
}

// XHR instead of fetch so big uploads show progress.
function upload(url, form, statusEl, label) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    const bar = document.createElement("progress");
    bar.max = 100;
    statusEl.className = "status";
    statusEl.textContent = `${label}…`;
    statusEl.append(bar);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) bar.value = (e.loaded / e.total) * 100;
      if (e.loaded === e.total) statusEl.firstChild.textContent = `${label}: uploaded, working on the phone…`;
    };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch { body = { detail: xhr.responseText }; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(body.detail || body);
    };
    xhr.onerror = () => reject("Network error");
    xhr.send(form);
  });
}

function errText(err) {
  if (typeof err === "string") return err;
  if (err && err.hint) return `${err.hint}\n(${err.code})`;
  return JSON.stringify(err);
}

async function openTools(name) {
  current = name;
  const p = phones[name] || {};
  $("#panel-title").textContent = name;
  $("#panel").classList.remove("hidden");
  setStatus($("#install-status"), "");
  $("#camera-section").hidden = p.engine !== "emulator";
  $("#cam-preview").innerHTML = "";
  loadApps();
  if (p.engine === "emulator") loadCamera();
}
$("#panel-close").addEventListener("click", () => $("#panel").classList.add("hidden"));

async function loadApps() {
  const list = $("#apps");
  list.innerHTML = `<li class="muted">Loading…</li>`;
  try {
    const data = await api(`/api/phones/${current}/apps`);
    list.innerHTML = data.apps.length
      ? data.apps.map((a) => `<li><span>${esc(a.package)} <i class="muted">${esc(a.version)}</i></span>
          <button data-pkg="${esc(a.package)}" data-verb="launch">Open</button>
          <button class="danger" data-pkg="${esc(a.package)}" data-verb="uninstall">Remove</button></li>`).join("")
      : `<li class="muted">No apps installed yet.</li>`;
  } catch (e) {
    list.innerHTML = `<li class="muted">Phone not reachable yet (still booting?). ${esc(e.message)}</li>`;
  }
}
$("#apps-refresh").addEventListener("click", loadApps);
$("#apps").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-pkg]");
  if (!b) return;
  b.disabled = true;
  try {
    await api(`/api/phones/${current}/apps/${b.dataset.pkg}/${b.dataset.verb}`, { method: "POST" });
  } catch (err) {
    alert(err.message);
  }
  if (b.dataset.verb === "uninstall") loadApps();
  b.disabled = false;
});

async function installFile(file) {
  const st = $("#install-status");
  const form = new FormData();
  form.append("file", file);
  form.append("replace", $("#replace").checked ? "true" : "false");
  try {
    const res = await upload(`/api/phones/${current}/install`, form, st, `Installing ${file.name}`);
    const extra = res.obb && res.obb.length ? `, plus ${res.obb.length} game data file(s)` : "";
    setStatus(st, `Installed ${res.package || file.name}${extra}.`, "ok");
    loadApps();
  } catch (err) {
    setStatus(st, `Could not install ${file.name}: ${errText(err)}`, "err");
  }
}

async function loadCamera() {
  try {
    showCamera(await api(`/api/phones/${current}/camera`));
  } catch (e) {
    setStatus($("#cam-now"), e.message, "err");
  }
}
function showCamera(st) {
  const what = st.kind === "pattern" ? "the test pattern" : `${st.kind} “${st.source}”`;
  setStatus($("#cam-now"), `Camera is showing ${what}.`, st.kind === "pattern" ? "" : "ok");
}
async function cameraFile(file) {
  const prev = $("#cam-preview");
  const url = URL.createObjectURL(file);
  prev.innerHTML = file.type.startsWith("video/")
    ? `<video src="${url}" muted autoplay loop playsinline></video>`
    : `<img src="${url}" alt="">`;
  const form = new FormData();
  form.append("file", file);
  try {
    showCamera(await upload(`/api/phones/${current}/camera`, form, $("#cam-now"), `Sending ${file.name}`));
  } catch (err) {
    setStatus($("#cam-now"), errText(err), "err");
  }
}
$("#cam-pattern").addEventListener("click", async () => {
  $("#cam-preview").innerHTML = "";
  try {
    showCamera(await upload(`/api/phones/${current}/camera`, new FormData(), $("#cam-now"), "Switching"));
  } catch (err) {
    setStatus($("#cam-now"), errText(err), "err");
  }
});

function dropZone(zone, input, onFile) {
  input.addEventListener("change", () => { if (input.files[0]) onFile(input.files[0]); input.value = ""; });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]);
  });
}
dropZone($("#drop"), $("#apk"), installFile);
dropZone($("#cam-drop"), $("#cam-file"), cameraFile);

load();
setInterval(load, 8000);
