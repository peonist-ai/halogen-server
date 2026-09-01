<p align="center">
  <img src="docs/halogen.jpg" alt="halogen — the peon's inference engine" width="760">
</p>

# halogen

**The fastest way to run Qwen3.8-27B on AMD Strix Halo — at higher precision
than anything that comes close.**

Every kernel is written for this one GPU and this one model family. No
general-purpose runtime, no portability layer, no fallback path — which is why
it can do things a general engine cannot, and why it runs on exactly one piece
of silicon.

On a 32K prompt with a 256-token answer, against the fastest numbers anyone
else has published for this model on this hardware:

| | prefill | decode | **total** |
|---|---|---|---|
| **halogen** (6.32 bpw) | **57.9 s** | 8.1 s | **66.0 s** |
| [KyaniteLabs](https://github.com/KyaniteLabs/qwen38-27b-strix-halo) (Q4_K_XL) | 84.0 s | 8.5 s | 92.5 s |
| [q38rocm](https://github.com/julianmb/q38rocm) (4.26 bpw) | 133.7 s | 7.8 s | 141.5 s |

**2.1× faster than q38rocm and 1.4× faster than KyaniteLabs end-to-end, while
carrying ~1.5× their weight precision.** Prefill is where that is won, and on
any prompt with real context prefill is most of the wall clock.

Output is also *byte-identical* to serial greedy decode — speculation here is
a pure speed optimization, verified on every release, not a quality trade.

```bash
podman run --rm -p 8731:8731 \
  --device /dev/kfd --device /dev/dri --group-add keep-groups \
  --security-opt seccomp=unconfined --ipc=host \
  -v /path/to/models:/models:ro -v /path/to/tokenizer:/tokenizer:ro \
  ghcr.io/peonist-ai/halogen:0.1.1
```

An OpenAI-compatible endpoint comes up on `:8731`.

On Docker rather than Podman, replace `--group-add keep-groups` with
`--group-add video --group-add render`. `keep-groups` is a Podman keyword that
Docker does not understand: Docker resolves `--group-add` names against the
container's `/etc/group` and fails with `unable to find group keep-groups`.

---

## Get the weights

The image contains **no model weights** — it is 3.5 GB of engine, and the
checkpoint is 35.9 GB. Download it once and mount it:

```bash
pip install -U "huggingface_hub[cli]"
hf download peonist-ai/halogen-qwen3.8-27b \
  --local-dir ~/halogen-models
```

That repository carries both the `.hgn` checkpoint **and a flat tokenizer
directory**, so there is nothing to assemble by hand:

```
~/halogen-models/
  qwen3.8-27b-p1w4d-d2.hgn      35.9 GB   the checkpoint
  tokenizer/                              tokenizer.json, chat template, ...
```

Then point the container at both:

```bash
podman run --rm -p 8731:8731 \
  --device /dev/kfd --device /dev/dri --group-add keep-groups \
  --security-opt seccomp=unconfined --ipc=host \
  -v ~/halogen-models:/models:ro \
  -v ~/halogen-models/tokenizer:/tokenizer:ro \
  ghcr.io/peonist-ai/halogen:0.1.1
```

### Or let it fetch them for you

If you would rather not download separately, set `HALOGEN_DOWNLOAD` and the
container fetches the weights on first start:

```bash
podman run --rm -p 8731:8731 \
  --device /dev/kfd --device /dev/dri --group-add keep-groups \
  --security-opt seccomp=unconfined --ipc=host \
  -e HALOGEN_DOWNLOAD=peonist-ai/halogen-qwen3.8-27b \
  -e HALOGEN_TOKENIZER=/models/tokenizer \
  -v ~/halogen-models:/models \
  ghcr.io/peonist-ai/halogen:0.1.1
```

Two differences from the manual route. The models volume is mounted
**read-write** — it has to be, to download into. And there is only *one*
mount: the download brings the tokenizer with it, so `HALOGEN_TOKENIZER`
points inside `/models` rather than at a second volume. Mounting
`~/halogen-models/tokenizer` here would fail on a first run, because the
container runtime would create it as an empty directory before the download
had a chance to populate it. It fires only when the checkpoint is actually missing, so
restarts do not re-download, and an interrupted transfer resumes rather than
starting over.

**With `HALOGEN_DOWNLOAD` unset, the container makes no outbound network
connections at all** — no telemetry, no license check, no model fetch. If the
checkpoint is not on disk where `HALOGEN_CHECKPOINT` points, it says so and
exits rather than reaching for the network. That default is deliberate: a
35.9 GB transfer should not begin because someone ran `podman run` to see what
would happen.

Model weights are licensed separately from the engine by their original
authors; see the model repository for those terms.

---

## Performance

Measured on a Ryzen AI Max+ 395 (Radeon 8060S, 128 GB LPDDR5X), ROCm 7.14.0,
checkpoint `p1w4d-d2` (~6.3 bits/weight effective at decode), 262,144 context.

### Prefill

All three measured over the HTTP endpoint with the bundled `sweep`, so they
are one instrument rather than a mix.

| test | t/s |
|---|---|
| pp512 | 620 |
| pp2048 | 710 |
| pp32768 | **566** |

### Decode

Over the HTTP endpoint, ten prompt shapes, greedy, DFlash2 drafter:

| | mean t/s | range |
|---|---|---|
| **DFlash2** (default) | **31.71** | 20.8 – 44.2 |
| MTP | 26.88 | 19.8 – 34.2 |
| serial (no speculation) | 10.58 | — |

Aggregate throughput at 8 concurrent requests: **48.6 t/s** (4.87×).

### Read the range, not just the mean

**halogen's decode rate is a distribution, not a number.** Speculative
decoding accepts more drafted tokens when the text is predictable, so the same
build on the same hardware does:

- **prose / chat: 20.8 – 23.5 t/s**
- **procedures: 25.6 – 38.7 t/s**
- **code / proofs: 32.7 – 44.2 t/s**

A single headline figure hides a 2× spread. Any decode number quoted from this
project — by us or anyone else — should name the prompt set that produced it,
or it is not reproducible. `bench` prints the mean; `sweep` prints mean, standard
deviation, and min–max, deliberately.

An engine without speculative decoding has a content-independent decode rate
and can honestly quote one number. We can't.

---

## How it compares

Published numbers from other projects running **the same model on the same
silicon**. These are *their* figures on *their* configurations, not a
head-to-head we ran — quantization, KV-cache settings and context differ, so
read this as orientation, not as a controlled benchmark.

| | halogen | [q38rocm](https://github.com/julianmb/q38rocm) | [KyaniteLabs](https://github.com/KyaniteLabs/qwen38-27b-strix-halo) |
|---|---|---|---|
| backend | custom HIP | ROCm/RADV | llama.cpp |
| weights | ~6.3 bpw | 4.26 bpw | UD-Q4_K_XL |
| **prefill @32K** | **566 t/s** | 245 t/s | ~390 t/s |
| decode, speculated | 30.98 mean (20.8–44.2) | 30.56 – 36.04 | prose 11–24, code 29–40 |
| decode, unassisted *(diagnostic)* | 10.58 t/s | **14.02 t/s** | — |

**Where we win:** prefill, by 1.4–2.3×, and end-to-end on any prompt with real
context. That is what the engine was built for.

**Where we lose:** unassisted decode — and that row is a diagnostic, not a
product configuration. Nobody ships serial decode; every project in this table
runs speculation by default. The gap is also not kernel quality: decode is
bandwidth-bound, q38rocm streams ~17 GB/token against our 23.5, and fewer bits
is simply faster. We spend those bits deliberately (see `QUANT.md`) — the only
4-bit tensors in our trunk are ones somebody else calibrated, and the
aggressive technique is fenced to prefill where it never touches token
generation.

**Our batch-1 decode is at the hardware wall.** 10.58 t/s × 23.51 GB/token =
249 GB/s against a measured ceiling of 240 GB/s. There is no kernel win left
there for anyone; the levers are fewer bits, better draft acceptance, and
batching.

**On the 148–163 t/s figure** circulating for llama.cpp on this hardware: that
is an ngram-repetition artifact on back-to-back identical runs, and
KyaniteLabs — whose benchmark it is — says so plainly and warns against
quoting it for chat. Their honest conversational numbers are in the table.
We think that is the right way to publish, and we have tried to match it.

---

## Benchmark it yourself

The image ships both benchmarks. No fixtures, no extra downloads, no
cooperation from us required.

```bash
# ten real prompt shapes over the HTTP endpoint — the number of record
podman run --rm --device /dev/kfd --device /dev/dri --group-add keep-groups \
  --security-opt seccomp=unconfined --ipc=host \
  -v /path/to/models:/models:ro -v /path/to/tokenizer:/tokenizer:ro \
  ghcr.io/peonist-ai/halogen:0.1.1 bench dflash2 256 low 3

# llama-bench-shaped pp/tg sweep, for putting a number beside another engine
podman run --rm ... ghcr.io/peonist-ai/halogen:0.1.1 \
  sweep -p 512,2048,8192 -n 128,256 -d dflash2,mtp -r 3
```

`sweep --json` emits machine-readable output.

**Publishing the results is expressly permitted** — no approval, no notice, no
prior review. We only ask that figures name the version and the prompt set,
for the reason above. That request is not a licensing condition.

---

## What it does

**Byte-identical speculative decoding.** Draft-then-verify commits only tokens
the full model would have produced, so output is bit-for-bit identical to
serial greedy decode. This is gated on every release across all three
drafters — not asserted, measured. Speculation here is a pure speed
optimization with no quality cost, and you can turn it off per request to
check.

**Native 262,144-token context**, with decode that barely degrades at depth —
Gated DeltaNet carries O(1) state, so 48 of 64 layers have no KV cache at all.

**Prompt cache** — a follow-up turn on a long conversation resumes instead of
re-prefilling, worth roughly 20× on time-to-first-token at 32K. Warm answers
are byte-identical to cold ones by construction.

**Batched decode** — 8 concurrent sequences, 4.87× aggregate, each
byte-identical to running alone. **Off by default**, and it trades away
speculation when enabled; see [Configuration](#concurrency-and-the-one-trap)
before turning it on.

**OpenAI-compatible API** — `/v1/chat/completions`, `/v1/completions`,
streaming, tool calling, sampling with seeds, reasoning-effort control.

**Three selectable drafters** — `dflash2` (default), `mtp`, `serial`. Choose
per request; output is identical, only speed changes.

---

## Configuration

Everything is set by environment variable — there is no config file. The
complete list of levers, with defaults and whether each one can change output,
is in [`docs/FLAGS.md`](docs/FLAGS.md). These are the ones most people touch:

| variable | default | what it does |
|---|---|---|
| `HALOGEN_CHECKPOINT` | `/models/qwen3.8-27b-p1w4d-d2.hgn` | which checkpoint to load |
| `HALOGEN_TOKENIZER` | `/tokenizer` | flat tokenizer directory |
| `HALOGEN_API_PORT` | `8731` | the published port |
| `HALOGEN_DRAFTER` | `2` (DFlash2) | default drafter: `0` serial, `1` MTP, `2` DFlash2 |
| `HALOGEN_CACHE_MB` | *auto* | prompt cache budget; `0` disables |
| `HALOGEN_MAX_TOKENS_CAP` | `16384` | largest `max_tokens` a request may ask for — over it is a **400**, never a silent truncation |
| `HALOGEN_QUEUE_TIMEOUT` | `2400` | seconds a queued request will wait — **coupled to the cap**, see below |
| `HALOGEN_KV_SLOTS` | `1` | concurrent resident sequences — see below |
| `HALOGEN_SLOT_CTX` | `262144` | context each slot holds — see below |

Per-request settings — drafter, temperature, top_p, seed, reasoning effort,
tools — go in the JSON body and override the server defaults.

### The token budget covers thinking, not just the answer

This model reasons before it replies and those tokens count against the budget,
so a budget that runs out mid-thought does not shorten the answer, it removes
it: the reply comes back with `finish_reason: "length"`, an empty `content`, and
the partial reasoning in `reasoning_content`, which most OpenAI clients do not
display. The per-request default is **8192**, which finished every ordinary
prompt we measured with room to spare; the ceiling is `HALOGEN_MAX_TOKENS_CAP`.

Any of three field names works, and they mean the same thing here:
`max_completion_tokens` (current OpenAI Chat Completions), `max_output_tokens`
(OpenAI Responses), or `max_tokens` (deprecated upstream, still widely sent).
Send one, or send several as long as they agree; two different values is a 400
rather than a guess about which you meant. `/health` lists all three under
`token_budget_aliases` and reports the default as `max_tokens_default`.

If a reply looks empty or cut off, read `finish_reason` first: `"stop"` means
you have the whole answer, `"length"` means you ran out of budget. Pass a larger
budget, or `"reasoning_effort": "low"` to make the model think less.

### Concurrency, and the one trap

**By default halogen serves one request at a time with speculative decoding
on.** That is the right setting for a single user: you get ~31 t/s.

Raising `HALOGEN_KV_SLOTS` lets several sequences be resident at once and
raises *aggregate* throughput to about 49 t/s at 8 concurrent requests — but
**speculation and batching are currently mutually exclusive.** With more than
one slot the drafter is off, so each individual stream runs at serial speed
(~6 t/s at 8 slots). One user is much better off with the default; a shared
server with steady concurrent load is better off with slots.

**The trap:** the KV pool costs `slots x slot_ctx x 64 KiB`, so raising slots
without lowering the per-slot context multiplies the allocation. Eight slots
at the native 262,144 context asks for **137 GB** and will not fit. Keep the
product at or below the native context:

| `KV_SLOTS` | `SLOT_CTX` | pool |
|---|---|---|
| 1 | 262144 | 17.2 GB *(default)* |
| 2 | 131072 | 17.2 GB |
| 4 | 65536 | 17.2 GB |
| 8 | 32768 | 17.2 GB |
| 8 | 262144 | 137 GB — **will not fit** |

A prompt longer than `SLOT_CTX` is a hard error naming the limit. It is never
silently truncated.

### Raising the output cap

`HALOGEN_MAX_TOKENS_CAP` and `HALOGEN_QUEUE_TIMEOUT` are coupled and should
not be moved independently. The cap bounds how long one request can hold the
GPU; the timeout bounds how long the next client waits for it. **If a
full-length request can outlast the timeout, everyone queued behind it gets a
503.**

At high reasoning effort decode runs around 10 t/s, so:

| cap | worst-case request | needs a timeout above |
|---|---|---|
| 4,096 | 6.8 min | 410 s |
| 16,384 | 27.3 min | 1,640 s |
| 32,768 | 54.6 min | 3,280 s |
| **65,536** *(default)* | **109.2 min** | **6,550 s**, and the default timeout is 7,200 s |

The cap is a ceiling on what a client may ask for, not a promise about
throughput. Almost nothing reaches it: the model stops on its own when the
answer is done. It is set high so that a long reasoning problem is not cut off
by server policy, and the timeout is set above it so that a client who does ask
for a full-length reply does not 503 the next one in the queue. Lower both
together if you would rather bound how long one request can hold the GPU.

Asking for more than the cap returns a **400** naming the limit. It is never
silently truncated — a truncated response and a model that stopped on its own
both end with `finish_reason: "length"`, so a client cannot tell them apart.

### Prompt cache

`HALOGEN_CACHE_MB` is empty by default, meaning **auto**: the engine sizes the
cache from available memory at startup. That suits a machine dedicated to
serving. Set an explicit value in MB to pin it, or `0` to disable.

One caveat if you pin it: a single full-context entry is about 18.4 GB at
262K, so a small explicit budget produces a cache that reports itself enabled
and never actually hits. The engine warns at startup when this happens.

Warm answers are byte-identical to cold ones by construction.

## Requirements

- **AMD Strix Halo (gfx1151)** — Ryzen AI Max+ 395 or equivalent. The build
  hard-rejects every other architecture; this will not run on your discrete
  GPU, and that is deliberate.
- **128 GB unified memory** recommended. The checkpoint is 35.9 GB and is
  mapped, not copied.
- **ROCm-capable kernel** with `/dev/kfd` and `/dev/dri` accessible.
- **A checkpoint and a tokenizer**, mounted at `/models` and `/tokenizer` —
  see [Get the weights](#get-the-weights). The tokenizer directory must be
  flat; the published model repository is already flat, so this only bites if
  you point at a HuggingFace *cache* snapshot, whose entries are symlinks into
  a sibling `blobs/` and dangle inside a container.

### Modes

| command | what it does |
|---|---|
| *(default)* | engine + API in one container, one published port |
| `engine` / `api` | split roles for a two-container deployment |
| `bench` | ten real prompt shapes over HTTP |
| `sweep` | pp/tg size sweep |

**The engine's token protocol has no authentication.** In the default mode it
binds loopback *inside* the container and only the API port is published. If
you split the roles, keeping the engine port unpublished is your
responsibility.

---

## Honest limits

- **One GPU target.** gfx1151 only, by construction.
- **Text only.** The model has a vision encoder; halogen does not use it.
- **Unassisted decode is not our strong suit** — see the comparison above.
- **Cold time-to-first-token at very long context is slow.** A genuinely cold
  262K prompt is a multi-minute prefill. The prompt cache makes the *second*
  turn fast; it cannot make the first one fast.
- **One default is not byte-identical to the engine's built-in one.** The
  image ships full W4A4 promotion, worth +9% prefill, against about −0.45 pt
  top-1 aggregate (better at deep context, worse in the first ~12%). It does
  not affect the guarantees above — speculation is still exact against serial
  greedy, warm cache still matches cold, batched still matches solo. Roll it
  back with one environment variable; see [`docs/FLAGS.md`](docs/FLAGS.md).
- **The comparison table is cross-published, not head-to-head.** We have not
  run the other engines ourselves on our box under matched settings. When we
  do, we will publish whatever it says.

---

## License

Free for any use, including commercial. Unmodified redistribution permitted.
Benchmark publication expressly permitted. See [`LICENSE`](LICENSE.md) and
[`THIRD-PARTY-NOTICES`](THIRD-PARTY-NOTICES.md), both also at `/licenses`
inside the image.

**Model weights are not included and are not covered** by that license. They
are obtained separately and licensed by their original authors.
