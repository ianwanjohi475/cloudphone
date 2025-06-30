const $ = (s) => document.querySelector(s);
const rows = $("#rows");

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
  rows.innerHTML = data.phones.map((p) => {
    const h = p.health || {};
    return `<tr>
      <td><b>${p.name}</b></td>
      <td>${badge(p.status)}</td>
      <td>${p.profile}</td>
      <td class="muted">${p.proxy || "-"}</td>
      <td>${h.booted ? "✓" : "—"}</td>
      <td>${h.cpu_pct ?? "—"}</td>
      <td>${h.mem_mb ? Math.round(h.mem_mb) + "M" : "—"}</td>
      <td>${h.crashes_recent ?? "—"}</td>
      <td class="controls">
        <button data-view="${p.name}">View</button>
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
  const url = `http://${host}:${window.SCRCPY_PORT}/#!action=stream&udid=${name}%3A5555&player=broadway&ws=ws%3A%2F%2F${host}%3A${window.SCRCPY_PORT}%2F`;
  $("#viewer-title").textContent = name;
  $("#scrcpy").src = url;
  $("#viewer").classList.remove("hidden");
}
$("#viewer-close").addEventListener("click", () => {
  $("#viewer").classList.add("hidden");
  $("#scrcpy").src = "about:blank";
});

load();
setInterval(load, 8000);
