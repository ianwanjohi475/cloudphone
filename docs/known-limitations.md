# Known limitations

cloudphone gives you a real, scriptable Android farm. Some things are **not**
achievable in a containerized software phone, by design of the security models
involved. Being honest about these saves you days of dead-ends.

## Hardware-backed attestation — NOT defeatable

**Play Integrity `STRONG` / `HARDWARE` verdicts, key attestation, SafetyNet
hardware attestation.**

These rely on a key fused into a real **TEE / StrongBox** that signs a
challenge. A container has no TEE, so it cannot produce a valid hardware-rooted
attestation chain. Magisk/resetprop/fingerprint spoofing only influence
*software* signals.

- **Ceiling:** you can usually reach Play Integrity **`BASIC`** (and sometimes
  `DEVICE` with a clean fingerprint + certified GApps + the GSF id registered).
  `STRONG`/`HARDWARE` are out of reach.
- **Affected:** banking apps, some wallets, DRM L1 video, a few games with
  strict integrity gates. They will detect the environment or refuse to run.

## ML / camera liveness — NOT defeatable with a static feed

**Face/anti-spoof liveness, "blink/turn your head", depth/IR checks.**

The virtual camera (`v4l2loopback`) injects a video stream, which beats *simple*
camera presence checks and basic upload flows. It does **not** beat modern
active liveness: those demand real-time responses to randomized prompts, and
many use depth/IR sensors a virtual camera can't emulate. A pre-recorded clip
fails the challenge-response.

- **Works:** apps that just need *a* camera, photo upload, QR scanning, basic
  "take a selfie" with no active challenge.
- **Fails:** active liveness / presentation-attack-detection, depth-based face
  unlock.

## GPU performance

Software (SwiftShader) rendering is stable but slow for heavy 3D. Host GPU
passthrough helps but is driver-sensitive on laptop GPUs.

## Scale

Each phone is ~2–4 GB RAM + real CPU. A 16 GB laptop runs ~3–4 comfortably;
density is a host-resource problem, not a software one.

## ARM apps

Need a native-bridge image; translation has a performance cost and a few
NDK-heavy apps still misbehave.

## What this *is* good for

Development & testing, UI automation, multi-account/session isolation, privacy
and geo workflows, scraping/automation where `BASIC` integrity suffices, and
education. Use it only where you're authorized to.
