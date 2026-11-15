// cloudphone web client: draws the phone screen and sends input back.
"use strict";

const $ = (id) => document.getElementById(id);
const canvas = $("screen");
const ctx = canvas.getContext("2d");
const overlay = $("overlay");

const PKT_CONFIG = 0, PKT_KEY = 1, PKT_DELTA = 2, PKT_IMAGE = 9;
const DOWN = 0, UP = 1, MOVE = 2;

let ws = null;
let mode = "video";       // "video" (H.264) or "shot" (screenshots)
let decoder = null;
let config = null;        // SPS/PPS, sent before every key frame
let waitingForKey = true;
let gotFrame = false;
let watchdog = 0;

// ------------------------------------------------------------------ ui bits
function showOverlay(text) {
  $("overlay-text").textContent = text;
  overlay.classList.remove("hidden");
}

let toastTimer = 0;
function toast(text, isError = false, sticky = false) {
  const el = $("toast");
  el.textContent = text;
  el.className = "on" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  if (!sticky) toastTimer = setTimeout(() => (el.className = ""), isError ? 8000 : 3500);
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

// ------------------------------------------------------------------- video
function resize(w, h) {
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
}

function frameShown() {
  if (!gotFrame) {
    gotFrame = true;
    clearTimeout(watchdog);
    overlay.classList.add("hidden");
  }
}

function drawFrame(frame) {
  resize(frame.displayWidth, frame.displayHeight);
  ctx.drawImage(frame, 0, 0);
  frame.close();
  frameShown();
}

async function drawImage(bytes) {
  const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
  resize(bitmap.width, bitmap.height);
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  frameShown();
}

// The codec string ("avc1.PPCCLL") comes from the first three bytes of the SPS.
function codecFromConfig(data) {
  for (let i = 0; i + 4 < data.length; i++) {
    if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 1 && (data[i + 3] & 0x1f) === 7) {
      const hex = (b) => b.toString(16).padStart(2, "0");
      return "avc1." + hex(data[i + 4]) + hex(data[i + 5]) + hex(data[i + 6]);
    }
  }
  return "avc1.42e01f";
}

function sameBytes(a, b) {
  return a && b && a.length === b.length && a.every((v, i) => v === b[i]);
}

function useScreenshots(why) {
  if (mode === "shot") return;
  console.warn("cloudphone: switching to screenshot mode:", why);
  mode = "shot";
  if (ws) ws.close();
}

function onConfig(data) {
  if (decoder && decoder.state === "configured" && sameBytes(config, data)) return;
  config = data;
  waitingForKey = true;
  if (decoder && decoder.state !== "closed") decoder.close();
  decoder = new VideoDecoder({
    output: drawFrame,
    error: (e) => useScreenshots(e.message),
  });
  decoder.configure({ codec: codecFromConfig(data), optimizeForLatency: true });
}

function onVideo(type, data) {
  if (!decoder || decoder.state !== "configured") return;
  if (type === PKT_KEY) {
    const joined = new Uint8Array(config.length + data.length);
    joined.set(config);
    joined.set(data, config.length);
    data = joined;
    waitingForKey = false;
  } else if (waitingForKey) {
    return;
  }
  try {
    decoder.decode(new EncodedVideoChunk({
      type: type === PKT_KEY ? "key" : "delta",
      timestamp: performance.now() * 1000,
      data,
    }));
  } catch (e) {
    useScreenshots(e.message);
  }
}

function onBinary(bytes) {
  const type = bytes[0];
  const data = bytes.subarray(1);
  if (type === PKT_IMAGE) drawImage(data).catch(() => {});
  else if (type === PKT_CONFIG) onConfig(data);
  else onVideo(type, data);
}

// -------------------------------------------------------------- connection
async function h264Supported() {
  if (!("VideoDecoder" in window)) return false;
  try {
    return (await VideoDecoder.isConfigSupported({ codec: "avc1.42e01f" })).supported;
  } catch {
    return false;
  }
}

function connect() {
  gotFrame = false;
  config = null;
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws?mode=${mode}`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    showOverlay("Starting the screen…");
    // No picture after a while in video mode: this browser cannot decode it.
    if (mode === "video") watchdog = setTimeout(() => useScreenshots("no frame decoded"), 12000);
  };
  ws.onmessage = (e) => {
    if (typeof e.data !== "string") return onBinary(new Uint8Array(e.data));
    const msg = JSON.parse(e.data);
    if (msg.t === "fallback") {
      console.warn("cloudphone: server fell back to screenshots:", msg.reason);
      clearTimeout(watchdog);
    }
  };
  ws.onclose = () => {
    clearTimeout(watchdog);
    ws = null;
    setTimeout(start, 1000);
  };
}

async function start() {
  let state = "offline";
  try {
    const res = await fetch("/api/status");
    if (res.status === 401) return location.reload();
    state = (await res.json()).state;
  } catch { /* server restarting */ }
  if (state === "ready") return connect();
  showOverlay(state === "booting"
    ? "Android is booting. The first boot takes a few minutes…"
    : "Waiting for the phone to power on…");
  setTimeout(start, 2000);
}

// ------------------------------------------------------------------- touch
const pointers = new Map();  // browser pointer id -> slot 0..9

function point(e) {
  const r = canvas.getBoundingClientRect();
  const clamp = (v, max) => Math.max(0, Math.min(max, Math.round(v)));
  return {
    x: clamp(((e.clientX - r.left) / r.width) * canvas.width, canvas.width),
    y: clamp(((e.clientY - r.top) / r.height) * canvas.height, canvas.height),
    w: canvas.width,
    h: canvas.height,
  };
}

function touch(action, e) {
  send({ t: "touch", a: action, id: pointers.get(e.pointerId), ...point(e) });
}

canvas.addEventListener("pointerdown", (e) => {
  if (e.button > 0) return;
  let slot = 0;
  const used = new Set(pointers.values());
  while (used.has(slot)) slot++;
  if (slot > 9) return;
  pointers.set(e.pointerId, slot);
  canvas.setPointerCapture(e.pointerId);
  canvas.focus();
  touch(DOWN, e);
  e.preventDefault();
});
canvas.addEventListener("pointermove", (e) => {
  if (pointers.has(e.pointerId)) touch(MOVE, e);
});
for (const name of ["pointerup", "pointercancel"]) {
  canvas.addEventListener(name, (e) => {
    if (!pointers.has(e.pointerId)) return;
    touch(UP, e);
    pointers.delete(e.pointerId);
  });
}
canvas.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  send({ t: "key", k: 4 });  // right click = Back
});

let lastWheel = 0;
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const now = performance.now();
  if (now - lastWheel < 40) return;
  lastWheel = now;
  send({ t: "scroll", ...point(e), dx: -Math.sign(e.deltaX), dy: -Math.sign(e.deltaY) });
}, { passive: false });

// ---------------------------------------------------------------- keyboard
const KEYS = {
  Enter: 66, Backspace: 67, Delete: 112, Tab: 61, Escape: 4,
  ArrowUp: 19, ArrowDown: 20, ArrowLeft: 21, ArrowRight: 22,
  Home: 122, End: 123, PageUp: 92, PageDown: 93,
};
const softkeys = $("softkeys");

window.addEventListener("keydown", (e) => {
  if (e.target === softkeys && !(e.key in KEYS)) return;  // handled by "input" below
  if (e.ctrlKey || e.metaKey || e.altKey) return;         // leave browser shortcuts alone
  if (e.key in KEYS) {
    send({ t: "key", k: KEYS[e.key] });
  } else if (e.key.length === 1 || [...e.key].length === 1) {
    send({ t: "text", s: e.key });
  } else {
    return;
  }
  e.preventDefault();
});

window.addEventListener("paste", (e) => {
  const text = e.clipboardData && e.clipboardData.getData("text");
  if (text) send({ t: "text", s: text });
  e.preventDefault();
});

// On-screen keyboards (phones, tablets) type into a hidden field.
softkeys.addEventListener("input", (e) => {
  if (e.inputType === "deleteContentBackward") send({ t: "key", k: 67 });
  else if (e.inputType === "insertLineBreak") send({ t: "key", k: 66 });
  else if (e.data) send({ t: "text", s: e.data });
  if (!e.isComposing) softkeys.value = "";
});
$("keyboard").addEventListener("click", () => softkeys.focus());

// ----------------------------------------------------------------- buttons
for (const button of document.querySelectorAll("#bar button[data-key]")) {
  button.addEventListener("click", () => send({ t: "key", k: Number(button.dataset.key) }));
}
$("rotate").addEventListener("click", () => send({ t: "rotate" }));
$("fullscreen").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
});
$("store").addEventListener("click", async () => {
  const res = await fetch("/api/launch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ package: "com.android.vending" }),
  }).catch(() => null);
  if (!res || !res.ok) toast("Could not open the Play Store on this phone.", true);
});

// ------------------------------------------------------------ app install
function install(file) {
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/install");
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    toast(pct < 100 ? `Uploading ${file.name}… ${pct}%` : `Installing ${file.name}…`, false, true);
  };
  xhr.onload = () => {
    let reply = {};
    try { reply = JSON.parse(xhr.responseText); } catch { /* not json */ }
    if (reply.ok) toast(`${file.name} installed. Find it in the app drawer.`);
    else toast(`Could not install ${file.name}: ${reply.error || xhr.statusText}`, true);
  };
  xhr.onerror = () => toast(`Upload of ${file.name} failed.`, true);
  toast(`Uploading ${file.name}…`, false, true);
  xhr.send(body);
}

$("install").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", (e) => {
  install(e.target.files[0]);
  e.target.value = "";
});

let dragDepth = 0;
window.addEventListener("dragenter", (e) => {
  e.preventDefault();
  dragDepth++;
  $("drop").classList.add("on");
});
window.addEventListener("dragleave", () => {
  if (--dragDepth <= 0) $("drop").classList.remove("on");
});
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  $("drop").classList.remove("on");
  install(e.dataTransfer.files[0]);
});

// ------------------------------------------------------------------- start
h264Supported().then((ok) => {
  if (!ok) mode = "shot";
  start();
});
