#!/bin/bash
# deploy/entrypoint.sh — Peonist halogen release image entrypoint.
#
#   all      (default) engine on loopback + OpenAI front-end. One container,
#            one published port. This is the shape a user who just wants to
#            run the thing should get.
#   engine   engine only  — for the two-container topology (compose), where
#            front-end iteration must not cost a 35.9 GB model reload.
#   api      front-end only, same reason.
#   bench    run the throughput benchmark against this image's OWN endpoint
#            and exit. Args: [drafters] [max_tokens] [effort] [reps], e.g.
#            `bench dflash2,mtp 256 low 3`. Needs the model and tokenizer
#            mounted exactly like `all` does.
#
#            This exists because the first thing anyone does with a claim
#            about speed is try to reproduce it, and until now that required
#            our private golden fixtures. The ten prompt shapes are baked in
#            (a few KB of JSON); the goldens are NOT and are not needed.
#            It drives the real HTTP endpoint — chat template, tokenizer,
#            SSE, engine — not an engine-side harness, because an engine-side
#            number is not a serving number.
#   sweep    llama-bench-shaped pp/tg size sweep, for putting a number next to
#            another engine's table on the same box. Args are passed through
#            to tools/halogen-bench.py, e.g.
#            `sweep -p 512,2048,8192 -n 128 -d dflash2,mtp -r 3`.
#            `bench` answers "how fast in practice", `sweep` answers "how does
#            this compare at a fixed size". They are not interchangeable.
#
# The engine's token protocol has NO AUTH. In `all` it binds loopback INSIDE
# the container and is unreachable from outside; only the API port is
# published. If you split the roles you must keep the engine port unpublished
# yourself — the compose file does, deliberately.
set -euo pipefail

ENG_PORT="${HALOGEN_PORT:-8730}"
API_PORT="${HALOGEN_API_PORT:-8731}"
BIND="${HALOGEN_BIND:-127.0.0.1}"

# OPTIONAL model download. OFF unless HALOGEN_DOWNLOAD names a repo.
#
# Default-off is deliberate and is not timidity: with it off, this image opens
# NO outbound connections at all, which is a property worth keeping and which
# the EULA states. A 35.9 GB transfer should also never start because someone
# ran `podman run` to see what happens.
#
# Only fires when the checkpoint is genuinely absent, so a restart never
# re-downloads. huggingface_hub resumes partial files natively, so an
# interrupted pull continues rather than starting over.
maybe_download() {
  [ -n "${HALOGEN_DOWNLOAD:-}" ] || return 0
  [ -f "$HALOGEN_CHECKPOINT" ] && return 0

  local dir; dir="$(dirname "$HALOGEN_CHECKPOINT")"
  if [ ! -w "$dir" ]; then
    echo "halogen: HALOGEN_DOWNLOAD is set but $dir is not writable." >&2
    echo "  The models volume must be read-WRITE to download into it." >&2
    echo "  Mount it as -v <path>:/models  (drop the :ro)." >&2
    exit 1
  fi

  echo "halogen: $HALOGEN_CHECKPOINT not found."
  echo "halogen: downloading from $HALOGEN_DOWNLOAD into $dir"
  echo "         this is tens of GB and will take a while; it resumes if interrupted."
  # HF_HUB_OFFLINE=1 is baked into the image and MUST stay set for serving --
  # it is what stops the front-end reaching for a tokenizer at request time.
  # Override it for this command only. Without this the download fails even
  # against a valid repo, which is exactly how the first build of this feature
  # behaved until the failure-path test caught it.
  if ! HF_HUB_OFFLINE=0 hf download "$HALOGEN_DOWNLOAD" --local-dir "$dir"; then
    echo "halogen: download FAILED. Nothing was started." >&2
    echo "  Re-run to resume, or fetch it yourself and mount it." >&2
    exit 1
  fi

  # Verify rather than trust: a failed transfer can leave a plausible-looking
  # tree, and an engine that starts on a truncated checkpoint fails much later
  # and much more confusingly than one that refuses here.
  if [ ! -f "$HALOGEN_CHECKPOINT" ]; then
    echo "halogen: download finished but $HALOGEN_CHECKPOINT is still missing." >&2
    echo "  The repo layout may not match HALOGEN_CHECKPOINT. Contents:" >&2
    ls -la "$dir" >&2
    exit 1
  fi
  echo "halogen: download complete ($(du -h "$HALOGEN_CHECKPOINT" | cut -f1))"
}

need_ckpt() {
  maybe_download
  [ -f "$HALOGEN_CHECKPOINT" ] || {
    echo "halogen: no checkpoint at $HALOGEN_CHECKPOINT" >&2
    echo "  mount it:  -v /path/to/models:/models:ro" >&2
    echo "  or point:  -e HALOGEN_CHECKPOINT=/models/<file>.hgn" >&2
    exit 1; }
}

need_tokenizer() {
  # Must be a FLAT dir. HF cache snapshots are symlinks into a sibling blobs/,
  # which dangle inside a container that mounts only the snapshot.
  [ -f "$HALOGEN_TOKENIZER/tokenizer.json" ] || {
    echo "halogen: no tokenizer.json in $HALOGEN_TOKENIZER" >&2
    echo "  the tokenizer dir must be FLAT (cp -L out of an HF snapshot)" >&2
    exit 1; }
}

start_engine() {
  need_ckpt
  exec /usr/local/bin/halogen \
    --checkpoint "$HALOGEN_CHECKPOINT" \
    --serve --port "$ENG_PORT" --bind "$BIND"
}

start_api() {
  need_tokenizer
  # HALOGEN_ENGINE must be settable. In `all` the engine is in this same
  # container and loopback is right, but in the two-container topology
  # (docker-compose) the services get SEPARATE network namespaces and the
  # api has to reach `engine:8730` by name. Hardcoding 127.0.0.1 here made
  # `api` mode silently unusable for exactly the deployment the split exists
  # to serve — found by writing the compose file, not by testing.
  exec python3 /halogen/tools/serve_api.py \
    --tokenizer "$HALOGEN_TOKENIZER" \
    --engine "${HALOGEN_ENGINE:-127.0.0.1:$ENG_PORT}" \
    --host 0.0.0.0 --port "$API_PORT" \
    --max-tokens-cap "${HALOGEN_MAX_TOKENS_CAP:-16384}" \
    --queue-timeout "${HALOGEN_QUEUE_TIMEOUT:-2400}"
}

case "${1:-all}" in
engine) start_engine ;;
api)    start_api ;;
all)
  need_ckpt; need_tokenizer
  /usr/local/bin/halogen --checkpoint "$HALOGEN_CHECKPOINT" \
      --serve --port "$ENG_PORT" --bind 127.0.0.1 &
  ENGINE_PID=$!
  trap 'kill -TERM "$ENGINE_PID" 2>/dev/null || true' TERM INT

  # The front-end connects to the engine at STARTUP and exits on refusal, so
  # it must not launch first. A cold 35.9 GB checkpoint faults in slowly when
  # it is not already in page cache — measured longer than any fixed sleep is
  # willing to wait, which is why this polls instead of sleeping.
  echo "halogen: waiting for engine on $ENG_PORT (cold load can take minutes)"
  for _ in $(seq 1 900); do
    if exec 3<>"/dev/tcp/127.0.0.1/$ENG_PORT" 2>/dev/null; then
      exec 3>&-; echo "halogen: engine listening"; break
    fi
    kill -0 "$ENGINE_PID" 2>/dev/null || { echo "halogen: engine died during load" >&2; wait "$ENGINE_PID"; exit 1; }
    sleep 2
  done

  python3 /halogen/tools/serve_api.py \
    --tokenizer "$HALOGEN_TOKENIZER" \
    --engine "127.0.0.1:$ENG_PORT" \
    --host 0.0.0.0 --port "$API_PORT" \
    --max-tokens-cap "${HALOGEN_MAX_TOKENS_CAP:-16384}" \
    --queue-timeout "${HALOGEN_QUEUE_TIMEOUT:-2400}" &
  API_PID=$!

  # Either process exiting must take the container down — a live API in front
  # of a dead engine answers 200 + zero bytes, which is indistinguishable
  # from a hang on the client side.
  wait -n "$ENGINE_PID" "$API_PID"
  echo "halogen: a component exited; shutting down" >&2
  kill -TERM "$ENGINE_PID" "$API_PID" 2>/dev/null || true
  wait || true
  exit 1
  ;;
bench|sweep)
  MODE="$1"
  shift || true
  need_ckpt; need_tokenizer
  BENCH_LOG=/tmp/halogen-api.log
  : > "$BENCH_LOG"

  /usr/local/bin/halogen --checkpoint "$HALOGEN_CHECKPOINT" \
      --serve --port "$ENG_PORT" --bind 127.0.0.1 > /tmp/halogen-engine.log 2>&1 &
  ENGINE_PID=$!
  trap 'kill -TERM "$ENGINE_PID" 2>/dev/null || true' TERM INT EXIT

  echo "halogen bench: loading model (cold load can take minutes)"
  for _ in $(seq 1 900); do
    if exec 3<>"/dev/tcp/127.0.0.1/$ENG_PORT" 2>/dev/null; then
      exec 3>&-; break
    fi
    kill -0 "$ENGINE_PID" 2>/dev/null || { echo "engine died during load:" >&2; tail -20 /tmp/halogen-engine.log >&2; exit 1; }
    sleep 2
  done

  # The api's stdout is TEED, not just redirected: the ledger lines the bench
  # scrapes for commit/round and prefill only exist in this stream, and a
  # bench that silently lost them would still print a t/s table.
  python3 /halogen/tools/serve_api.py \
    --tokenizer "$HALOGEN_TOKENIZER" \
    --engine "127.0.0.1:$ENG_PORT" \
    --host 127.0.0.1 --port "$API_PORT" \
    --max-tokens-cap "${HALOGEN_MAX_TOKENS_CAP:-16384}" \
    --queue-timeout "${HALOGEN_QUEUE_TIMEOUT:-2400}" 2>&1 | tee "$BENCH_LOG" &
  API_PID=$!

  # python, not curl: the slim base has no curl and a bench that silently
  # skipped its readiness wait would just fail the first request instead.
  for _ in $(seq 1 150); do
    python3 -c "import urllib.request,sys
try: urllib.request.urlopen('http://127.0.0.1:$API_PORT/health', timeout=3); sys.exit(0)
except Exception: sys.exit(1)" 2>/dev/null && break
    sleep 2
  done

  if [ "$MODE" = sweep ]; then
    python3 /halogen/tools/halogen-bench.py \
      --api "http://127.0.0.1:$API_PORT" "$@"
  else
    HALOGEN_API="http://127.0.0.1:$API_PORT" HALOGEN_API_LOG="$BENCH_LOG" \
      python3 /halogen/tools/bench-serving.py \
        "${1:-dflash2}" "${2:-256}" "${3:-low}" "${4:-1}"
  fi
  RC=$?
  kill -TERM "$API_PID" "$ENGINE_PID" 2>/dev/null || true
  exit $RC
  ;;
*) echo "usage: entrypoint.sh [all|engine|api|bench|sweep]" >&2; exit 2 ;;
esac
