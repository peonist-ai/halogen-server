# Changelog

## 0.1.0 — unreleased

First public release. Container image only; the engine is closed source.

### Added
- OpenAI-compatible endpoint: `/v1/chat/completions`, `/v1/completions`,
  streaming, tool calling, sampling with seeds, reasoning-effort control.
- Native 262,144-token context.
- Three selectable drafters — `dflash2` (default), `mtp`, `serial` — all
  producing byte-identical output.
- Prompt cache: ~20x time-to-first-token on a follow-up turn at 32K, and warm
  answers are byte-identical to cold ones by construction.
- Batched decode: 8 concurrent sequences, 4.87x aggregate, each byte-identical
  to running alone. OFF by default (`HALOGEN_KV_SLOTS=1`), and currently
  mutually exclusive with speculative decoding — a single user is better off
  with the default.
- `bench` and `sweep` modes in the image, so throughput claims can be checked
  without our cooperation and without any fixture download.

### Measured
- Prefill: 620 t/s (pp512), 710 (pp2048), 566 (pp32768), all over HTTP with
  the bundled `sweep`.
- Decode over HTTP, ten prompt shapes, greedy: dflash2 31.71 t/s mean
  (20.8-44.2), serial 10.58.
- Ships full W4A4 promotion (all 400 i4l planes): +8.96% pp32K measured ABBA
  on the shipped checkpoint, decode unharmed, against about -0.45 pt top-1
  aggregate. This is the one default whose emitted tokens differ from the
  engine's built-in default; it does not affect spec-equals-serial,
  warm-equals-cold or batched-equals-solo. One env var rolls it back.
- Batch-1 decode runs at 249 GB/s against a measured 240 GB/s ceiling — the
  hardware wall, not a tuning target.

### Known limits
- gfx1151 only, by construction. The build rejects every other architecture.
- Text only; the model's vision encoder is not used.
- Unassisted (non-speculative) decode is slower than lower-precision engines,
  which is a deliberate precision choice — see `docs/QUANT.md`.
- A genuinely cold 262K prompt is a multi-minute prefill. The prompt cache
  makes the second turn fast, not the first.
- Speculation and batching cannot currently be used together. Enabling slots
  raises aggregate throughput but drops each stream to serial speed.
- Configuration is by environment variable only; there is no config file.
