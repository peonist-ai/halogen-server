# Changelog

## 0.1.1

A bug-fix release. **The engine is unchanged**: no kernel, no checkpoint, no
format change, so every performance and quality number below still stands and
**your weights do not need re-downloading**. The image carries no weights and
the mount layout is the same, so upgrading is a container pull and nothing else.

### Fixed

- **A default request could come back empty.** `max_tokens` defaulted to 512
  while the chat template defaults `reasoning_effort` to `xhigh`, and reasoning
  tokens count against the budget. A request that ran out before the model
  finished thinking returned `finish_reason: "length"` with an **empty
  `content`** and the whole reply in `reasoning_content`, which most OpenAI
  clients do not display. The default is now **8192**.
- **`max_completion_tokens` and `max_output_tokens` were silently ignored.**
  They were not declared, so a client using the current OpenAI Chat Completions
  field name had it dropped without an error and got the default no matter what
  it asked for. The budget was reachable only under the deprecated `max_tokens`.
  All three names are now accepted and mean the same thing. Send one, or send
  several as long as they agree; two different values is a 400 rather than a
  guess.

### Changed

- `HALOGEN_MAX_TOKENS_CAP` **16384 to 65536**, so a long reasoning problem is
  not cut off by server policy. `HALOGEN_QUEUE_TIMEOUT` **2400 to 7200** with
  it: the two are coupled, and a cap that outlasts the timeout makes one long
  request 503 everyone queued behind it. At the xhigh decode rate a full-length
  request is about 109 minutes, which is where 7200 comes from.
- `/health` now reports `max_tokens_default` and `token_budget_aliases`, so a
  client can read which spellings this server accepts instead of guessing.

### If you saw poor output on 0.1.0

Check `finish_reason` on a reply that looked wrong. `"length"` with an empty or
truncated `content` was this bug, and it was not your configuration. Either pull
0.1.1, or stay on 0.1.0 and pass `"max_tokens": 8192` explicitly, which is the
only spelling 0.1.0 reads.

## 0.1.0


First public release. Container image only; the engine is closed source.

### Fixed
- **The quickstart commands now say `podman run`, not `docker run`.** They
  always carried `--group-add keep-groups`, which is a Podman keyword: Podman
  intercepts it and keeps the caller's supplementary groups, while Docker
  resolves `--group-add` names against the container's `/etc/group` and fails
  with `unable to find group keep-groups`. Every command in this project is
  tested under Podman, so the published `docker run` form had never been run.
  The README and `docker-compose.yml` now show the Podman form and give the
  Docker substitution (`--group-add video --group-add render`, or
  `group_add: ["video", "render"]`).

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
