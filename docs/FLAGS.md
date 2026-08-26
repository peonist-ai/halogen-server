# halogen environment flags

Everything is configured by environment variable; there is no config file.
All flags are read **once at startup**.

This lists the flags used to deploy and operate halogen. The engine carries
additional kernel-tuning levers that are not documented here: they select
internal implementation variants, they are not needed to run the server, and
the shipped defaults are the measured winners. Changing what is listed below
is supported; anything else is not.

| class | meaning |
|---|---|
| **BITWISE** | output is byte-identical. Safe to change. |
| **NUMERIC** | output *can* change. |

Every flag below is **BITWISE** — they are deployment policy, not arithmetic —
except `HALOGEN_W4A4` and `HALOGEN_W4A4_EXCL`, which are **NUMERIC** and
documented as such.


## Model and tokenizer

| flag | default | meaning |
|---|---|---|
| `HALOGEN_CHECKPOINT` | `/models/qwen3.8-27b-p1w4d-d2.hgn` | Path to the `.hgn` checkpoint the engine loads. |
| `HALOGEN_TOKENIZER` | `/tokenizer` | Flat tokenizer directory. Must contain `tokenizer.json`. HuggingFace cache snapshots are symlinks into a sibling `blobs/` and dangle inside a container, so materialize with `cp -L`. |

## Networking

| flag | default | meaning |
|---|---|---|
| `HALOGEN_API_PORT` | `8731` | Port for the OpenAI-compatible front-end. The only port that should be published. |
| `HALOGEN_PORT` | `8730` | Engine port. **The engine protocol has no authentication** — keep it unpublished. |
| `HALOGEN_BIND` | `127.0.0.1` | Engine bind address. Loopback when engine and front-end share a container; `0.0.0.0` for the two-container topology, where it stays unpublished to the host. |
| `HALOGEN_ENGINE` | `127.0.0.1:$HALOGEN_PORT` | Where the front-end reaches the engine. Compose gives the services separate network namespaces, so it needs `engine:8730` there. |

## Request policy

| flag | default | meaning |
|---|---|---|
| `HALOGEN_MAX_TOKENS_CAP` | `16384` | Largest `max_tokens` a request may ask for. Exceeding it is a **400**, never a silent truncation — a truncated response and a model that stopped on its own both end with `finish_reason: "length"`, so a client cannot tell them apart. **Coupled to `HALOGEN_QUEUE_TIMEOUT`** — see the README. |
| `HALOGEN_QUEUE_TIMEOUT` | `2400` | Seconds a queued request waits before `503 engine_busy`. Must exceed the time a full-length request takes, or a long request 503s everyone behind it. |
| `HALOGEN_DRAFTER` | `2` | Default drafter for requests that do not name one: `0` serial, `1` MTP, `2` DFlash2. Output is identical whichever is used; only speed changes. Overridable per request. |

## Prompt cache

| flag | default | meaning |
|---|---|---|
| `HALOGEN_CACHE_MB` | *(empty = auto)* | Cache budget in MB. Empty means the engine sizes it from available memory at startup. `0` disables. A small explicit value yields a cache that reports itself enabled and never hits — one full-context entry is about 18.4 GB at 262K. |
| `HALOGEN_CACHE_ALIGN` | `2048` | Snapshot alignment. This value is what makes a warm answer byte-identical to a cold one; any other value is not. Do not change it. |
| `HALOGEN_CACHE_RESERVE_MB` | `8192` | Memory left for the system when the cache sizes itself automatically. |

## Concurrency

| flag | default | meaning |
|---|---|---|
| `HALOGEN_KV_SLOTS` | `1` | Sequences resident at once. `1` serves one request at a time **with speculative decoding**, which is the right default for a single user. Above 1 raises aggregate throughput but disables speculation, so each stream runs at serial speed. Capped at 8. |
| `HALOGEN_SLOT_CTX` | `262144` | Context each slot holds. The pool costs `slots x slot_ctx x 64 KiB`, so raising slots without lowering this multiplies the allocation — keep the product at or below the native context. A prompt exceeding it is a hard error naming the limit, never a truncation. |

## Precision

| flag | default | meaning |
|---|---|---|
| `HALOGEN_W4A4` | `64` | Minimum rows for the int4 GEMM path used in prefill. `0` disables it entirely — slower, higher precision. Decode never crosses this threshold, so **decode is unaffected either way**. |
| `HALOGEN_W4A4_EXCL` | `""` | Which weight planes are excluded from the int4 path. The image ships `""` (no exclusions), worth about **+9% prefill** against roughly **-0.45 pt** top-1 aggregate, with decode unharmed. This is the one default whose emitted tokens differ from the engine's built-in default; it does not affect speculation-equals-serial, warm-equals-cold, or batched-equals-solo. See the README to roll it back. |

## Optional model download

| flag | default | meaning |
|---|---|---|
| `HALOGEN_DOWNLOAD` | *(unset = off)* | HuggingFace repo id to fetch weights from at startup, e.g. `peonist-ai/halogen-qwen3.8-27b`. **Off by default**: with it unset the container makes no outbound connections at all. It fires only when the checkpoint is genuinely missing, so restarts never re-download, and interrupted transfers resume. The models volume must be mounted read-**write** for this, not `:ro`. |

## Benchmark tooling

| flag | default | meaning |
|---|---|---|
| `HALOGEN_API` | `http://127.0.0.1:8731` | Endpoint the bundled benchmarks target. |
| `HALOGEN_API_LOG` | *(unset)* | Path to a teed front-end log, so the serving benchmark can read throughput counters from inside a container. |
