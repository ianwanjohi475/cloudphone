# Device profiles

Built-in profiles live in `orchestrator/cloudphone/fingerprint.py`
(`DEVICE_PROFILES`): `pixel_7`, `pixel_6`, `samsung_s21`,
`xiaomi_redmi_note11`, `generic_x86_64`.

To add a custom profile, drop a JSON file here named `<profile>.local.json`
(gitignored) with the same keys as the built-ins, e.g.:

```json
{
  "brand": "OnePlus",
  "manufacturer": "OnePlus",
  "model": "CPH2449",
  "device": "OP5959L1",
  "product": "CPH2449",
  "board": "kalama",
  "release": "14",
  "sdk": "34",
  "security_patch": "2024-02-05",
  "build_id": "UKQ1.230924.001",
  "incremental": "CPH2449_14.0.0.300",
  "abilist": "arm64-v8a,armeabi-v7a,armeabi"
}
```

Each phone's generated identity (serial, android_id, MACs, IMEI, full
fingerprint) is written to `data/<phone>.fingerprint.json` at creation time and
re-applied on every provision, so identities are stable across recreation.
