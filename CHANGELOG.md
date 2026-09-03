# Changelog

## 0.1.2

A sampler bug-fix release. **The kernels, the checkpoint format and the weights
are unchanged**, so every performance and quality number still stands and your
weights do not need re-downloading. Upgrading is a container pull.

**Greedy output is byte-identical to 0.1.1.** If you run with `temperature: 0`
— the default — nothing about this release changes what you get. Every fix
below is on the sampled path, and each one changes sampled output for the
better, so a sampled request will not reproduce a 0.1.1 result even with the
same seed.

### Fixed

- **`top_p` very close to 1.0 silently kept every token.** At about `0.9998` or
  higher the nucleus cut never triggered, so the request was served as though
  no `top_p` had been set at all — a 200, with the setting quietly doing
  nothing. Values further from 1.0 were unaffected, which is why this went
  unnoticed: our own test cases stopped at `0.99`.
- **`presence_penalty`, `frequency_penalty` and `logit_bias` were ignored when
  speculative decoding was active.** That is the default configuration, so in
  practice these three settings did nothing on most sampled requests. The
  request returned 200 with no indication the setting had been dropped. They
  now apply on every path, including mid-round: a token penalized by something
  the model just emitted is penalized before the next tokens are scored.
- **A rounding gap in the sampler could repeat the previous token.** In rare
  cases a draw landed in a gap that belonged to no candidate, and the token
  that came out was the one before it. This was most visible as an occasional
  stutter in sampled output.

### Changed

- `/health` reports the sampler's behavior under `sampling`, including which
  fields are implemented and which are rejected rather than ignored.

### If you used sampling on 0.1.1

Requests that set `top_p` above ~0.9998, or that set `presence_penalty`,
`frequency_penalty` or `logit_bias`, were served with those settings partly or
wholly inactive. They were not errors and nothing in the response said so, so
output that looked insufficiently constrained or unusually repetitive was
likely this rather than your configuration. There is no workaround on 0.1.1
for the penalty fields under the default drafter; pull 0.1.2.

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
