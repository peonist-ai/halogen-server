#!/usr/bin/env python3
"""tools/bench-serving.py — the serving benchmark of record.

Run ON the box (it talks to the pod on loopback):

    python3 tools/bench-serving.py [drafters] [max_tokens] [effort] [reps]
    python3 tools/bench-serving.py mtp,dflash2 256 low 3

WHY THIS EXISTS, and it is not "a nicer curl loop". This project kept
quoting FIXTURE numbers as serving numbers and kept being wrong about it:

  - live traffic was recorded far faster than the fixture suggested, while the fox fixture
    said 30.9, and the m9 notes had to carry an explicit "never quote a
    fixture number as the serving speed".
  - m5"-s6 then did it again one level up: `--spec` on test/golden/chat
    showed DFlash2 at -23% and that got written up as "DFlash2 loses on
    chat". The live bench measured +5-7%. The fixture is 64 tokens of raw
    prompt text with NO chat template and NO thinking block, so it is a
    different token distribution from anything the endpoint serves.

So: fixtures gate CORRECTNESS, this gates SPEED, and the two must not be
read across. If you want to know what a change did to serving, run this.

WHAT IT MEASURES, and why not wall clock. t/s and commit/round come from
the ENGINE's own `D` line (surfaced in the api's per-request log), which
times the DECODE WINDOW only. Wall clock includes HTTP, tokenization,
incremental detokenization and prefill, and at 256 tokens that overhead is
several percent — enough to swamp the differences being looked for. Wall is
still reported alongside, because a large wall/decode gap is itself a
finding (it means the front-end, not the engine, is the cost).

commit/round is printed next to every t/s on purpose: it is the mechanism.
Every speed difference between two drafters on this workload is a commit
difference, and a t/s change with a flat commit is a timing artifact, not
an acceptance change.

IDENTITY IS CHECKED, NOT ASSUMED. Spec commit is trunk-argmax equality, so
every drafter must emit byte-identical text; the run hashes each case's
full output (reasoning + content) and fails loudly if two drafters differ.
That makes this a correctness check that happens to also produce timings.

REPS. Single runs on a live pod are indicative, not quotable — small deltas
(a few percent) sit inside run-to-run noise. Pass reps >= 3 for a number
worth putting in a document; the per-case spread is reported so the noise
floor is visible rather than assumed.

The prompt set is tools/eval-prompts.json, which is STABLE by policy: add
cases, never edit them, or cross-release comparisons stop meaning anything.
"""
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

API = os.environ.get("HALOGEN_API", "http://127.0.0.1:8731")
HALO = os.environ.get("HALOGEN_HALO", os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
PROMPTS_PATH = os.environ.get("HALOGEN_PROMPTS",
                              os.path.join(HALO, "tools", "eval-prompts.json"))
API_CTR = os.environ.get("HALOGEN_API_CTR", "halogen-api")
# HALOGEN_API_LOG makes this script runnable FROM INSIDE the serving
# container, where `podman logs` does not exist. The release image sets it and
# tees the api's output to that path (deploy/entrypoint.sh `bench` mode).
#
# Deliberately the SAME script rather than a second release-only bench: two
# benchmarks that can disagree is how a --spec fixture number ended up quoted
# as a serving number. One instrument, two ways of reaching the ledger.
API_LOG = os.environ.get("HALOGEN_API_LOG", "")

DRAFTERS = (sys.argv[1] if len(sys.argv) > 1 else "mtp,dflash2").split(",")
MAXTOK = int(sys.argv[2]) if len(sys.argv) > 2 else 256
EFFORT = sys.argv[3] if len(sys.argv) > 3 else "low"
REPS = int(sys.argv[4]) if len(sys.argv) > 4 else 1
# Optional temperature. 0 (the default) is greedy and keeps every
# property this bench relies on. Above 0 the run is SAMPLED, and one of those
# properties goes away — see the identity note below.
TEMP = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
TOPP = float(sys.argv[6]) if len(sys.argv) > 6 else 0.95
SEED0 = 0x5EED0000

CASES = [(k, v["prompt"] if isinstance(v, dict) else v)
         for k, v in json.load(open(PROMPTS_PATH)).items()
         if not k.startswith("_")]

# The `(N cached)` group is OPTIONAL and must stay so. The api only
# prints it when the prompt cache actually served part of the prompt, and a
# regex that required it — or that forgot it — would silently match ZERO lines
# on exactly the requests the cache helped, leaving the run to blame "other
# traffic" for a table it could not fill. This benchmark's prompt set is
# 11-30 tokens, well under the 2,048 snapshot alignment, so nothing here hits
# the cache today; the group exists so that stops being load-bearing.
LEDGER = re.compile(
    r"serve_api: (\w+) (\d+) tok in ([\d.]+)s = ([\d.]+) t/s \| "
    r"(\d+) rounds, commit ([\d.]+)/round \| prompt (\d+)"
    r"(?: \((\d+) cached\))?, prefill ([\d.]+)s")


def _api_output():
    """The api's recent output, however we can reach it.

    In-container (HALOGEN_API_LOG set) we read the teed log file; on the box
    we shell to `podman logs`. Both return the same text, so every caller
    below is unchanged.
    """
    if API_LOG:
        try:
            with open(API_LOG, "r", errors="replace") as f:
                return "".join(collections.deque(f, maxlen=2000))
        except FileNotFoundError:
            return ""
    out = subprocess.run(["podman", "logs", "--tail", "2000", API_CTR],
                         capture_output=True, text=True)
    return out.stdout + out.stderr


def ledger_count():
    """How many ledger lines the api has emitted so far.

    The api log is the only place the engine's decode-window stats surface,
    so the run brackets itself: count before, count after, take the tail.
    Reading `--tail N` blind would silently mix in a neighbouring request
    from other LAN traffic, which is exactly the kind of quiet
    contamination this file exists to avoid.
    """
    return len(LEDGER.findall(_api_output()))


def ledger_tail(n):
    return LEDGER.findall(_api_output())[-n:] if n else []


def ask(prompt, drafter, seed=None):
    b = {"messages": [{"role": "user", "content": prompt}],
         "max_tokens": MAXTOK, "reasoning_effort": EFFORT,
         "drafter": drafter}
    if TEMP > 0.0:
        # A FIXED seed per (case, rep), not a random one. Sampled output is
        # not identical across drafters, so the identity check below cannot
        # hold — but it must still be REPRODUCIBLE, or a t/s difference and a
        # different-text difference become impossible to tell apart.
        b.update(temperature=TEMP, top_p=TOPP, seed=seed)
    body = json.dumps(b).encode()
    req = urllib.request.Request(API + "/v1/chat/completions", body,
                                 {"content-type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    wall = time.time() - t0
    m = d["choices"][0]["message"]
    return (d["usage"]["completion_tokens"], wall,
            m.get("reasoning_content", "") + m["content"])


base = ledger_count()
order, hashes = [], collections.defaultdict(dict)
print(f"bench: {len(CASES)} cases x {len(DRAFTERS)} drafters x {REPS} rep(s), "
      f"max_tokens={MAXTOK}, effort={EFFORT}"
      + (f", SAMPLED temp={TEMP} top_p={TOPP}" if TEMP > 0 else ", greedy"))
for rep in range(REPS):
    for name, prompt in CASES:
        for dr in DRAFTERS:
            n, wall, text = ask(prompt, dr,
                                seed=SEED0 + rep * 1000 + hash(name) % 997)
            order.append((name, dr, wall, n))
            h = hashlib.sha256(text.encode()).hexdigest()[:12]
            prev = hashes[name].setdefault(dr, h)
            flag = "" if prev == h else "  !! UNSTABLE ACROSS REPS"
            print(f"  r{rep} {name:9s} {dr:8s} {n:4d} tok  {wall:6.2f}s wall"
                  f"{flag}", flush=True)

stats = ledger_tail(ledger_count() - base)

# Align ledger lines to requests by DRAFTER NAME, walking both in order.
#
# The previous version did `zip(order, stats)` and warned about "other
# traffic" whenever the counts differed. Both halves were wrong, and the
# combination produced a silently shuffled table: a NON-SPECULATIVE drafter
# (serial) emits no ledger line at all, because there are no draft rounds to
# report, so a serial+dflash2 run yields exactly half as many lines as
# requests with nobody else on the box. zip() then paired the first half of
# the REQUESTS against all of the dflash2 LINES, and every case after the
# first rep got another case's numbers — measured 2026-08-20: five distinct
# t/s values pasted across ten case slots, with the run blaming phantom
# traffic. That is precisely the mis-attribution this file's header exists
# to prevent, one level down.
#
# Consuming a line only when its drafter matches the request's keeps the two
# streams in step regardless of which drafters are speculative. Leftover
# lines afterwards DO mean something else hit the pod.
per = collections.defaultdict(lambda: collections.defaultdict(list))
wall_only = collections.defaultdict(lambda: collections.defaultdict(list))
si = 0
for (name, dr, wall, ntok) in order:
    if si < len(stats) and stats[si][0] == dr:
        st = stats[si]; si += 1
        per[name][dr].append((float(st[3]), float(st[5]), float(st[8]), wall,
                              int(st[7] or 0)))
    else:
        # no ledger line for this request: non-speculative drafter. Keep it,
        # scored on WALL (tokens/wall), which is the only timing available —
        # marked `*` in the table since it carries HTTP + tokenization.
        # ntok, NOT MAXTOK: a case that stops early (chat_a emits 176)
        # would otherwise be credited with tokens it never produced.
        wall_only[name][dr].append((wall, ntok))

quiet = si == len(stats)
if not quiet:
    print(f"\nWARNING: {len(stats) - si} ledger line(s) matched no request — "
          f"other traffic hit the pod during the run. Re-run when it is quiet.",
          file=sys.stderr)
nospec = sorted({dr for c in wall_only.values() for dr in c})
if nospec:
    print(f"note: {', '.join(nospec)} emit no ledger line (non-speculative); "
          f"scored on wall and marked * — not comparable to engine t/s.")

print(f"\n{'case':10s} {'drafter':9s} {'t/s':>7s} {'commit/rd':>10s} "
      f"{'prefill':>8s} {'wall':>7s}")
agg = collections.defaultdict(list)
for name, _ in CASES:
    for dr in DRAFTERS:
        v = per.get(name, {}).get(dr)
        if not v:
            w = wall_only.get(name, {}).get(dr)
            if w:  # wall-derived, no engine ledger for this drafter
                mw = sum(x[0] for x in w) / len(w)
                mt = sum(x[1] for x in w) / len(w)
                print(f"{name:10s} {dr:9s} {mt / mw:7.2f}*{'':9s} "
                      f"{'':7s} {mw:6.2f}s")
            continue
        ts = sum(x[0] for x in v) / len(v)
        cm = sum(x[1] for x in v) / len(v)
        pf = sum(x[2] for x in v) / len(v)
        wl = sum(x[3] for x in v) / len(v)
        spread = f"  (±{(max(x[0] for x in v) - min(x[0] for x in v)) / 2:.2f})" \
            if len(v) > 1 else ""
        # Any cache hit at all is worth surfacing: these prompts are far too
        # short to reach a snapshot boundary, so a non-zero column here means
        # the cache is engaging on something this table did not expect.
        cached = sum(x[4] for x in v) / len(v)
        ch = f"  [{cached:.0f} cached]" if cached else ""
        print(f"{name:10s} {dr:9s} {ts:7.2f} {cm:10.2f} {pf:7.2f}s "
              f"{wl:6.2f}s{spread}{ch}")
        agg[dr].append((ts, cm))

print("\n=== identity (sha256 of reasoning+content, per case) ===")
if TEMP > 0.0:
    # THE IDENTITY CHECK DOES NOT APPLY TO A SAMPLED RUN, and saying so beats
    # letting it "fail". Greedy's commit rule is trunk-argmax equality, so
    # every drafter emits byte-identical text and a mismatch is a real bug.
    # Speculative sampling emits exactly p while CONSUMING randomness
    # differently per drafter, so two correct drafters legitimately diverge.
    # Distributional gates are what cover this path instead.
    print("SKIPPED — sampled runs are not expected to be identical across")
    print("drafters. Correctness here is gated distributionally by")
    print("--spec-sample-check and gate-s3-falsify.sh, not by a hash.")
    # Skip the check itself, not just print a note beside it. The first
    # version printed this AND let the check run, which emitted "PASS — every
    # drafter byte-identical" underneath — vacuously true with one drafter and
    # flatly contradictory with two. A caveat that does not change what runs
    # is a caveat the output will eventually contradict.
    sys.exit(0)
bad = [n for n, h in hashes.items() if len(set(h.values())) != 1]
print("PASS — every drafter byte-identical on every case" if not bad
      else f"FAIL — drafters disagree on: {bad}\n"
           f"  A drafter CANNOT change output (commit is trunk-argmax\n"
           f"  equality). This is a verify or drafter-state bug, not a\n"
           f"  tuning issue. Stop and fix it.")

print("\n=== means over all cases ===")
ref = None
for dr in DRAFTERS:
    v = agg.get(dr)
    if not v:
        continue
    ts = [a for a, _ in v]
    mean = sum(ts) / len(ts)
    cm = sum(b for _, b in v) / len(v)
    if ref is None:
        ref = mean
    delta = f"   {(mean / ref - 1) * 100:+.1f}% vs {DRAFTERS[0]}" \
        if dr != DRAFTERS[0] else ""
    print(f"{dr:9s} mean {mean:6.2f} t/s   min {min(ts):5.2f}  "
          f"max {max(ts):5.2f}   commit {cm:.2f}/round{delta}")
sys.exit(1 if bad else 0)
