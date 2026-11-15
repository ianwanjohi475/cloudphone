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
  if (document.querySelector("dialog[open]")) return;     // typing in a dialog
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
  if (document.querySelector("dialog[open]")) return;
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

// ------------------------------------------------------------------ files
const fd = { dialog: $("files-dialog"), status: $("files-status"), list: $("files-list") };
const APP_FILE = /\.(apk|xapk|apks|apkm)$/i;

function fdStatus(text, kind = "") {
  fd.status.textContent = text;
  fd.status.className = kind || "muted";
}

function humanSize(n) {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

async function refreshFiles() {
  const res = await fetch("/api/files").then((r) => r.json()).catch(() => null);
  fd.list.replaceChildren();
  if (!res || res.error) return fdStatus((res && res.error) || "Could not read the phone's files.", "bad");
  for (const file of res.files) {
    const li = document.createElement("li");
    const name = Object.assign(document.createElement("span"), { className: "name", textContent: file.name });
    const size = Object.assign(document.createElement("span"), { className: "size", textContent: humanSize(file.size) });
    const del = Object.assign(document.createElement("button"), { type: "button", textContent: "Delete" });
    del.setAttribute("aria-label", `Delete ${file.name}`);
    del.addEventListener("click", async () => {
      if (!confirm(`Delete ${file.name} from the phone?`)) return;
      await fetch("/api/files?name=" + encodeURIComponent(file.name), { method: "DELETE" }).catch(() => null);
      refreshFiles();
    });
    li.append(name, size, del);
    fd.list.append(li);
  }
}

// Copy files into the phone's Downloads folder, with progress.
function uploadFiles(files) {
  files = [...files];
  if (!files.length) return;
  const label = files.length === 1 ? files[0].name : `${files.length} files`;
  const say = (text, kind, sticky) => {
    if (fd.dialog.open) fdStatus(text, kind);
    else toast(text, kind === "bad", sticky);
  };
  const body = new FormData();
  for (const f of files) body.append("file", f);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/files");
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    say(pct < 100 ? `Uploading ${label}… ${pct}%` : `Copying ${label} onto the phone…`, "", true);
  };
  xhr.onload = () => {
    let reply = {};
    try { reply = JSON.parse(xhr.responseText); } catch { /* not json */ }
    if (reply.ok) say(`${label} copied to the phone's Downloads folder.`, "ok");
    else say(`Could not copy ${label}: ${reply.error || xhr.statusText}`, "bad");
    if (fd.dialog.open) refreshFiles();
  };
  xhr.onerror = () => say(`Upload of ${label} failed.`, "bad");
  say(`Uploading ${label}…`, "", true);
  xhr.send(body);
}

$("files").addEventListener("click", () => {
  fdStatus("");
  fd.dialog.showModal();
  refreshFiles();
});
$("files-close").addEventListener("click", () => fd.dialog.close());
$("files-choose").addEventListener("click", () => $("files-input").click());
$("files-input").addEventListener("change", (e) => {
  uploadFiles(e.target.files);
  e.target.value = "";
});

// -------------------------------------------------------- camera / gallery
// Capture with this device's camera, or pick from its gallery, preview, then
// upload into the phone's Downloads. The camera and microphone are opened only
// when the user presses a button, and are released as soon as the live view
// is left; nothing is uploaded before "Upload to phone" is pressed.
const md = {
  dialog: $("media-dialog"), video: $("md-video"), status: $("md-status"),
  stream: null, mic: null, recorder: null, chunks: [], discard: false, timer: 0,
  facing: "environment", pending: [], urls: [], fromCamera: false,
};

function mdStatus(text, kind = "") {
  md.status.textContent = text;
  md.status.className = kind || "muted";
}

function mdStamp(prefix, ext) {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${prefix}-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.${ext}`;
}

function mdControls() {
  const recording = Boolean(md.recorder);
  $("md-photo").disabled = !md.stream || recording;
  $("md-record").disabled = !md.stream;
  $("md-flip").disabled = !md.stream || recording;
  $("md-record").classList.toggle("recording", recording);
  if (!recording) $("md-record").textContent = "Record video";
}

function stopCamera() {
  clearInterval(md.timer);
  if (md.recorder) {
    md.discard = true;  // leaving mid-recording throws the recording away
    md.recorder.stop();
  }
  for (const s of [md.stream, md.mic]) if (s) s.getTracks().forEach((t) => t.stop());
  md.stream = md.mic = null;
  md.video.srcObject = null;
  mdControls();
}

async function startCamera() {
  $("md-title").textContent = "Camera";
  $("md-live").hidden = false;
  $("md-preview").hidden = true;
  const supported = Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  md.video.hidden = $("md-controls").hidden = !supported;
  $("md-native").hidden = supported;
  mdControls();
  if (!supported) {
    // Plain http from another machine: browsers only allow the in-page camera
    // on https or localhost. The device's own camera app still works.
    return mdStatus("The in-page camera needs https or localhost. These buttons use your device's camera app instead.");
  }
  mdStatus("Opening the camera…");
  try {
    md.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: md.facing }, audio: false });
  } catch (e) {
    return mdStatus(e.name === "NotAllowedError"
      ? "Camera permission was not given. Allow the camera for this page in your browser, then try again."
      : `No camera could be opened (${e.name}).`, "bad");
  }
  if (!md.dialog.open) return stopCamera();  // closed while the permission prompt was up
  md.video.srcObject = md.stream;
  mdStatus("");
  mdControls();
}

function takePhoto() {
  const w = md.video.videoWidth, h = md.video.videoHeight;
  if (!w || !h) return;
  const shot = Object.assign(document.createElement("canvas"), { width: w, height: h });
  shot.getContext("2d").drawImage(md.video, 0, 0);
  shot.toBlob((blob) => {
    if (blob) showPreview([new File([blob], mdStamp("photo", "jpg"), { type: "image/jpeg" })], true);
  }, "image/jpeg", 0.92);
}

async function toggleRecording() {
  if (md.recorder) return md.recorder.stop();
  if (!md.stream) return;
  if (!("MediaRecorder" in window)) return mdStatus("This browser cannot record video.", "bad");
  // The microphone is asked for only now, when a recording is started.
  try {
    md.mic = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    md.mic = null;
    mdStatus("No microphone permission: recording without sound.");
  }
  if (!md.stream) return;
  const tracks = [...md.stream.getVideoTracks(), ...(md.mic ? md.mic.getAudioTracks() : [])];
  const type = ["video/mp4", "video/webm"].find((t) => MediaRecorder.isTypeSupported(t));
  const rec = new MediaRecorder(new MediaStream(tracks), type ? { mimeType: type } : {});
  md.chunks = [];
  md.discard = false;
  rec.ondataavailable = (e) => { if (e.data.size) md.chunks.push(e.data); };
  rec.onstop = () => {
    clearInterval(md.timer);
    md.recorder = null;
    if (md.mic) md.mic.getTracks().forEach((t) => t.stop());
    md.mic = null;
    mdControls();
    if (md.discard || !md.chunks.length) return;
    const mime = (rec.mimeType || "video/webm").split(";")[0];
    showPreview([new File(md.chunks, mdStamp("video", mime.includes("mp4") ? "mp4" : "webm"), { type: mime })], true);
  };
  rec.start(1000);
  md.recorder = rec;
  mdControls();
  const began = Date.now();
  const tick = () => {
    const s = Math.floor((Date.now() - began) / 1000);
    $("md-record").textContent = `Stop (${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")})`;
  };
  tick();
  md.timer = setInterval(tick, 500);
}

function clearPreview() {
  md.urls.forEach((u) => URL.revokeObjectURL(u));
  md.urls = [];
  md.pending = [];
  $("md-items").replaceChildren();
}

function showPreview(files, fromCamera) {
  files = [...files];
  if (!files.length) return;
  stopCamera();
  clearPreview();
  md.pending = files;
  md.fromCamera = fromCamera;
  for (const file of files) {
    const url = URL.createObjectURL(file);
    md.urls.push(url);
    const figure = document.createElement("figure");
    if (file.type.startsWith("image/")) {
      figure.append(Object.assign(document.createElement("img"), { src: url, alt: `Preview of ${file.name}` }));
    } else if (file.type.startsWith("video/")) {
      figure.append(Object.assign(document.createElement("video"), { src: url, controls: true, playsInline: true }));
    }
    figure.append(Object.assign(document.createElement("figcaption"), { textContent: `${file.name} · ${humanSize(file.size)}` }));
    $("md-items").append(figure);
  }
  $("md-title").textContent = "Preview";
  $("md-live").hidden = true;
  $("md-preview").hidden = false;
  $("md-retake").textContent = fromCamera ? "Retake" : "Cancel";
  mdStatus(files.length === 1 ? "Nothing is uploaded until you press Upload." : `${files.length} items. Nothing is uploaded until you press Upload.`);
  if (!md.dialog.open) md.dialog.showModal();
}

$("files-camera").addEventListener("click", () => {
  md.dialog.showModal();
  startCamera();
});
$("files-gallery").addEventListener("click", () => $("md-gallery").click());
$("md-photo").addEventListener("click", takePhoto);
$("md-record").addEventListener("click", toggleRecording);
$("md-flip").addEventListener("click", () => {
  md.facing = md.facing === "environment" ? "user" : "environment";
  stopCamera();
  startCamera();
});
$("md-native-photo-btn").addEventListener("click", () => $("md-native-photo").click());
$("md-native-video-btn").addEventListener("click", () => $("md-native-video").click());
for (const [id, fromCamera] of [["md-gallery", false], ["md-native-photo", true], ["md-native-video", true]]) {
  $(id).addEventListener("change", (e) => {
    showPreview(e.target.files, fromCamera);
    e.target.value = "";
  });
}
$("md-retake").addEventListener("click", () => {
  clearPreview();
  if (md.fromCamera) startCamera();
  else md.dialog.close();
});
$("md-upload").addEventListener("click", () => {
  const files = md.pending;
  md.dialog.close();
  uploadFiles(files);
});
$("md-close").addEventListener("click", () => md.dialog.close());
// Any way of closing (button, Esc) releases the camera and drops the preview.
md.dialog.addEventListener("close", () => {
  stopCamera();
  clearPreview();
  mdStatus("");
});

// ------------------------------------------------------------------ proxy
const px = { dialog: $("proxy-dialog"), status: $("px-status"), hasPassword: false };

function pxStatus(text, kind = "") {
  px.status.textContent = text;
  px.status.className = kind || "muted";
}

function pxShowFields() {
  $("px-fields").hidden = $("px-type").value === "none";
}

$("px-type").addEventListener("change", pxShowFields);
$("px-cancel").addEventListener("click", () => px.dialog.close());

$("proxy").addEventListener("click", async () => {
  pxStatus("");
  px.dialog.showModal();
  const cfg = await fetch("/api/proxy").then((r) => r.json()).catch(() => null);
  if (!cfg) return pxStatus("Could not load the current setting.", "bad");
  $("px-type").value = cfg.type;
  $("px-host").value = cfg.host;
  $("px-port").value = cfg.port || "";
  $("px-user").value = cfg.username;
  $("px-pass").value = "";
  $("px-pass").placeholder = cfg.has_password ? "saved (leave empty to keep)" : "optional";
  px.hasPassword = cfg.has_password;
  pxShowFields();
  if (cfg.type !== "none") {
    pxStatus(cfg.needs_restart
      ? "Saved, but the phone must restart to use it: run ./cloudphone reboot"
      : `Active: ${cfg.type.toUpperCase()} ${cfg.host}:${cfg.port}`, cfg.needs_restart ? "bad" : "ok");
  }
});

$("proxy-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    type: $("px-type").value,
    host: $("px-host").value.trim(),
    port: Number($("px-port").value),
    username: $("px-user").value,
  };
  // An empty password field keeps the saved password; typing replaces it.
  if ($("px-pass").value || !px.hasPassword) body.password = $("px-pass").value;
  $("px-save").disabled = true;
  pxStatus(body.type === "none" ? "Removing the proxy…" : "Testing the proxy…");
  const res = await fetch("/api/proxy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json()).catch(() => null);
  $("px-save").disabled = false;
  if (!res || !res.ok) return pxStatus((res && res.error) || "Could not save.", "bad");
  px.hasPassword = res.has_password;
  $("px-pass").value = "";
  $("px-pass").placeholder = res.has_password ? "saved (leave empty to keep)" : "optional";
  const what = res.type === "none" ? "Proxy removed." : `Working. Websites will see the address ${res.ip}.`;
  pxStatus(res.restarting ? `${what} The phone is restarting to apply it (about a minute).` : what, "ok");
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
  // App files are installed; everything else is copied to Downloads.
  const dropped = [...e.dataTransfer.files];
  dropped.filter((f) => APP_FILE.test(f.name)).forEach(install);
  uploadFiles(dropped.filter((f) => !APP_FILE.test(f.name)));
});

// ------------------------------------------------------------------- start
h264Supported().then((ok) => {
  if (!ok) mode = "shot";
  start();
});
