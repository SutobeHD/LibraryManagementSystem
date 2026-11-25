"""Probes 2 + 3 (W8): note events -> 16-step top-voice sequences on the Rekordbox grid ->
per-window loops -> transposition-invariant fingerprints -> partner retrieval.

Input: samples.json (grids), notes.jsonl (basic-pitch notes per stem variant), pairs.json.
Output: retrieval.json + stdout tables. CPU only (numpy + numba).

Definitions
  step        1/16 bar = 1/4 Rekordbox beat; bars start on the grid downbeat at the window start
  step pitch  note active in a step = overlaps >= 50 % of it, MIDI 45..96;
              voice "top" = highest active note with amp >= 0.5 x strongest active note,
              voice "sal" = strongest active note; no active note = rest
  loop        per window + loop length L (1 / 2 / 4 bars): chunks of L bars, medoid chunk
              (highest mean step agreement), per-step majority over chunks agreeing >= 50 % with it
  fingerprint int = per step the interval to the previous sounding step (circular, clip +-12)
              rel = per step pitch minus the loop's most frequent pitch (clip +-24)
              pc  = per step pitch class, compared under all 12 transpositions (OTI)
  distance    band-limited (+-4 steps) edit distance, min over rotations by whole beats and (pc)
              12 transpositions, divided by max(sounding steps); track distance = min over the
              4 x 4 window loops
"""

import itertools
import json
import random
import sys
import time

import mcommon as M
import numpy as np
from numba import njit, prange

SEED = 20261113
LO, HI = 45, 96
REST = 99
BAND = 4
STEMS = ("other", "vocals", "ov", "mix")
VOICES = ("top", "sal")
LOOPS = (1, 2, 4)
FPS = ("int", "rel", "pc")
MIN_PCS = (1, 3)
N_DISTRACT = 60


def bar_steps(beats_s, bib0, t0, ratio):
    """Step edges (window time, s) for the full bars inside the 30 s window. -> (n_bars, 17)."""
    beats = np.asarray(beats_s)
    i0 = int(np.argmin(np.abs(beats - t0)))
    need = t0 + M.WIN_S * ratio
    if beats[-1] < need + 1.0:  # extend a grid that stops early with its last interval
        step = beats[-1] - beats[-2]
        extra = np.arange(1, int((need + 2.0 - beats[-1]) / step) + 2) * step + beats[-1]
        beats = np.concatenate([beats, extra])
    bars = []
    i = i0
    while i + 4 < len(beats) and (beats[i + 4] - t0) / ratio <= M.WIN_S + 1e-6:
        edges = []
        for b in range(4):
            edges += list(beats[i + b] + (beats[i + b + 1] - beats[i + b]) * np.arange(4) / 4.0)
        edges.append(beats[i + 4])
        bars.append((np.array(edges) - t0) / ratio)
        i += 4
    return np.array(bars)


def step_matrix(notes, bars, voice, lo_midi=LO, hi_midi=HI):
    """notes [[start, end, midi, amp, bend]] -> int16 (n_bars, 16), REST where nothing sounds."""
    out = np.full((len(bars), 16), REST, dtype=np.int16)
    if not notes or not len(bars):
        return out
    nt = np.array([n[:4] for n in notes], dtype=float)
    nt = nt[(nt[:, 2] >= lo_midi) & (nt[:, 2] <= hi_midi)]
    if not len(nt):
        return out
    for bi, edges in enumerate(bars):
        lo, hi = edges[:-1], edges[1:]
        ov = np.minimum(nt[:, 1][None, :], hi[:, None]) - np.maximum(nt[:, 0][None, :], lo[:, None])
        active = ov >= 0.5 * (hi - lo)[:, None]
        for s in range(16):
            idx = np.nonzero(active[s])[0]
            if not len(idx):
                continue
            amp = nt[idx, 3]
            if voice == "sal":
                out[bi, s] = int(nt[idx[int(np.argmax(amp))], 2])
            else:
                keep = idx[amp >= 0.5 * amp.max()]
                out[bi, s] = int(nt[keep, 2].max())
    return out


def window_loop(P, L):
    """P (n_bars, 16) -> (loop (16 L,), support share). Medoid chunk + majority of its neighbours."""
    n = len(P) // L
    if n == 0:
        return np.full(16 * L, REST, dtype=np.int16), 0.0
    ch = P[: n * L].reshape(n, 16 * L)
    snd = ch != REST
    agree = np.zeros((n, n))
    for i in range(n):
        either = snd[i][None, :] | snd
        same = (ch[i][None, :] == ch) & either
        agree[i] = same.sum(1) / np.maximum(1, either.sum(1))
    med = int(np.argmax(agree.mean(1)))
    near = np.nonzero(agree[med] >= 0.5)[0]
    if not len(near):  # window without notes
        return ch[med].copy(), 0.0
    loop = np.empty(16 * L, dtype=np.int16)
    for s in range(16 * L):
        vals, cnt = np.unique(ch[near, s], return_counts=True)
        loop[s] = vals[int(np.argmax(cnt))]
    return loop, len(near) / n


def fingerprint(loop, kind):
    snd = loop != REST
    out = np.full(len(loop), REST, dtype=np.int16)
    if not snd.any():
        return out
    if kind == "pc":
        out[snd] = loop[snd] % 12
    elif kind == "rel":
        vals, cnt = np.unique(loop[snd], return_counts=True)
        out[snd] = np.clip(loop[snd] - vals[int(np.argmax(cnt))], -24, 24)
    else:
        idx = np.nonzero(snd)[0]
        prev = loop[idx[-1]]
        for s in idx:
            out[s] = int(np.clip(loop[s] - prev, -12, 12))
            prev = loop[s]
    return out


@njit(cache=True)
def _edit_band(a, b, band):
    n = len(a)
    big = 1 << 20
    prev = np.full(n + 1, big, dtype=np.int32)
    cur = np.full(n + 1, big, dtype=np.int32)
    for j in range(min(n, band) + 1):
        prev[j] = j
    for i in range(1, n + 1):
        for j in range(n + 1):
            cur[j] = big
        if i <= band:
            cur[0] = i
        for j in range(max(1, i - band), min(n, i + band) + 1):
            c = prev[j - 1] + (0 if a[i - 1] == b[j - 1] else 1)
            if prev[j] + 1 < c:
                c = prev[j] + 1
            if cur[j - 1] + 1 < c:
                c = cur[j - 1] + 1
            cur[j] = c
        prev, cur = cur, prev
    return prev[n]


@njit(cache=True)
def _loop_dist(a, b, oti, band, rest):
    n = len(a)
    best = 1 << 20
    bt = np.empty(n, dtype=np.int16)
    for r in range(0, n, 4):
        for t in range(12 if oti else 1):
            for s in range(n):
                v = b[(s + r) % n]
                bt[s] = v if (v == rest or not oti) else (v + t) % 12
            d = _edit_band(a, bt, band)
            if d < best:
                best = d
    return best


@njit(cache=True)
def best_transposition(a, b, band, rest):
    """-> (distance, t): pitch classes of b shifted up by t semitones fit a best (any beat rotation)."""
    n = len(a)
    best, bt_ = 1 << 20, 0
    tmp = np.empty(n, dtype=np.int16)
    for t in range(12):
        for r in range(0, n, 4):
            for s in range(n):
                v = b[(s + r) % n]
                tmp[s] = v if v == rest else (v + t) % 12
            d = _edit_band(a, tmp, band)
            if d < best:
                best, bt_ = d, t
    return best, bt_


@njit(parallel=True, cache=True)
def loop_matrix(F, oti, band, rest):
    """F (m, n) fingerprints -> symmetric int32 (m, m) loop distances."""
    m = F.shape[0]
    D = np.zeros((m, m), dtype=np.int32)
    for i in prange(m):
        for j in range(i, m):
            D[i, j] = _loop_dist(F[i], F[j], oti, band, rest)
    for i in range(m):
        for j in range(i):
            D[i, j] = D[j, i]
    return D


def rank_of(dist_row, target, exclude):
    """Average rank (1 = best) of `target` among all candidates except `exclude`."""
    d = dist_row.copy()
    cand = np.ones(len(d), dtype=bool)
    cand[list(exclude)] = False
    dt = d[target]
    less = int(np.sum(cand & (d < dt)))
    ties = int(np.sum(cand & (d == dt)))  # includes the target itself
    return less + (ties + 1) / 2.0


def metrics(ranks):
    r = np.asarray(ranks, dtype=float)
    if not len(r):
        return {"n": 0, "top1": float("nan"), "top5": float("nan"), "top10": float("nan"), "mrr": float("nan")}
    return {"n": len(r), "top1": round(float(np.mean(r <= 1)), 3), "top5": round(float(np.mean(r <= 5)), 3),
            "top10": round(float(np.mean(r <= 10)), 3), "mrr": round(float(np.mean(1.0 / r)), 3),
            "med_rank": float(np.median(r))}


def main():
    S = M.load_samples()
    P = json.loads((M.OUT / "pairs.json").read_text(encoding="utf-8"))
    recs = {}
    for r in M.load_notes():
        if all(v in r["notes"] for v in STEMS):
            recs[r["id"]] = r
    pairs = [p for p in P["chosen"] if p["a"] in recs and p["b"] in recs]
    pair_ids = [i for p in pairs for i in (p["a"], p["b"])]
    distract = [i for i in S["sets"]["distract"] if i in recs and i not in pair_ids][:N_DISTRACT]
    real = pair_ids + distract
    syn = [i for i in recs if i.startswith("syn:") and i.split(":")[1] in real]
    ids = real + syn
    ix = {t: k for k, t in enumerate(ids)}
    nreal = len(real)
    print(f"pairs {len(pairs)} distractors {len(distract)} candidates {nreal} synthetic queries {len(syn)}")
    chance = {"top1": round(1 / (nreal - 1), 4), "top5": round(5 / (nreal - 1), 4), "top10": round(10 / (nreal - 1), 4),
              "mrr": round(sum(1 / k for k in range(1, nreal)) / (nreal - 1), 4)}
    print("chance", chance)

    rng = random.Random(SEED)
    tune, test = [], []
    for sub in ("ext", "orig_remix", "remix_remix", "pitched"):
        ps = [k for k, p in enumerate(pairs) if p["sub"] == sub]
        rng.shuffle(ps)
        half = (len(ps) + (len(tune) <= len(test))) // 2
        tune += ps[:half]
        test += ps[half:]
    overlap_win = {t for t in real if min(np.diff(S["tracks"][t]["wins"])) < M.WIN_S}

    # ---- step matrices per (stem, voice): [track][window] -> (n_bars, 16)
    t0 = time.time()
    steps = {}
    for stem in STEMS:
        for voice in VOICES:
            cur = []
            for t in ids:
                r = recs[t]
                tr = S["tracks"][r["tid"]]
                ratio = 2.0 ** (r["k"] / 12.0)
                beats = np.array(tr["beats_ms"]) / 1000.0
                cur.append([step_matrix(r["notes"][stem][w], bar_steps(beats, tr["bib0"], s, ratio), voice)
                            for w, s in enumerate(r["wins"])])
            steps[(stem, voice)] = cur
    print(f"step matrices {time.time() - t0:.0f}s; bars per window median "
          f"{np.median([len(m) for tr in steps[('other', 'top')] for m in tr]):.0f}")

    results, loopinfo, all_loops = {}, {}, {}

    def evaluate(track, half):
        res = {"ranks": {}, "half": {}, "syn": {}}
        for k, p in enumerate(pairs):
            a, b = ix[p["a"]], ix[p["b"]]
            res["ranks"][k] = (rank_of(track[a, :nreal], b, {a}), rank_of(track[b, :nreal], a, {b}))
        for t in real:
            if t not in overlap_win:
                res["half"][t] = rank_of(half[ix[t], :nreal], ix[t], set())
        for s_id in syn:
            res["syn"][s_id] = rank_of(track[ix[s_id], :nreal], ix[s_id.split(":")[1]], set())
        return res

    for stem, voice, L in itertools.product(STEMS, VOICES, LOOPS):
        loops = np.array([[window_loop(m, L)[0] for m in tr] for tr in steps[(stem, voice)]])  # (T, 4, 16L)
        T = len(ids)
        flat = loops.reshape(T * 4, 16 * L)
        snd = (flat != REST).sum(1)
        npc = np.array([len(set((x[x != REST] % 12).tolist())) for x in flat])
        all_loops[(stem, voice, L)] = (flat, snd)
        loopinfo[(stem, voice, L)] = {"sounding_med": float(np.median(snd)), "share_ge3pc": round(float(np.mean(npc >= 3)), 3),
                                      "share_empty": round(float(np.mean(snd < 4)), 3)}
        for fp in FPS:
            F = np.array([fingerprint(x, fp) for x in flat]).astype(np.int16)
            D = loop_matrix(F, fp == "pc", BAND, REST).astype(float)
            D /= np.maximum(4, np.maximum(snd[:, None], snd[None, :]))
            for minpc in MIN_PCS:
                ok = (snd >= 4) & (npc >= minpc)
                Dv = np.where(ok[:, None] & ok[None, :], D, 9.0)
                DT = Dv.reshape(T, 4, T, 4)
                track = DT.min(axis=(1, 3))
                half = DT[:, :2, :, 2:].min(axis=(1, 3))  # windows 1-2 (query) vs 3-4 (candidate)
                key = (stem, voice, L, fp, minpc)
                res = evaluate(track, half)
                res["valid_share"] = round(float(np.mean(ok.reshape(T, 4)[:nreal].any(1))), 3)
                res["track"], res["half_m"] = track.astype(np.float32), half.astype(np.float32)
                results[key] = res
        print(f"{stem}/{voice}/L{L} done {time.time() - t0:.0f}s", flush=True)

    def pair_metrics(key, which, sub=None):
        r = [x for k in which if sub is None or pairs[k]["sub"] == sub for x in results[key]["ranks"][k]]
        return metrics(r)

    table = sorted(results, key=lambda k: (-pair_metrics(k, tune)["mrr"], -pair_metrics(k, tune)["top5"]))
    best = table[0]
    print("\n== tuned on", len(tune), "pairs; top 8 variants by tune MRR (stem, voice, L, fp, min_pcs) ==")
    for k in table[:8]:
        print(k, "tune", pair_metrics(k, tune), "test", pair_metrics(k, test))
    print("\n== chosen variant", best, "==")
    out = {"chance": chance, "n_candidates": nreal, "chosen": list(best), "pairs_used": [[p["a"], p["b"], p["sub"]] for p in pairs],
           "tune_pairs": tune, "test_pairs": test, "loopinfo": {"/".join(map(str, k)): v for k, v in loopinfo.items()}}
    out["chosen_tune"] = pair_metrics(best, tune)
    out["chosen_test"] = pair_metrics(best, test)
    out["chosen_all"] = pair_metrics(best, range(len(pairs)))
    print("tune", out["chosen_tune"], "\ntest", out["chosen_test"], "\nall ", out["chosen_all"])
    out["chosen_by_sub"] = {}
    for sub in ("ext", "orig_remix", "remix_remix"):
        out["chosen_by_sub"][sub] = {"test": pair_metrics(best, test, sub), "all": pair_metrics(best, range(len(pairs)), sub)}
        print(sub, out["chosen_by_sub"][sub])
    for shift in sorted({s.split(":")[2] for s in syn}):
        m = metrics([results[best]["syn"][s] for s in syn if s.endswith(shift)])
        out.setdefault("chosen_syn", {})[shift] = m
        print("synthetic pitched", shift, m)
    out["chosen_half"] = metrics(list(results[best]["half"].values()))
    print("own-half (windows 1-2 -> 3-4), tracks without window overlap:", out["chosen_half"])
    out["valid_share"] = results[best]["valid_share"]

    # ---- compact table: per stem the variant with the best tune MRR, plus a fusion of two stems
    def line(res):
        def m(which, sub=None):
            return metrics([x for k in which if sub is None or pairs[k]["sub"] == sub for x in res["ranks"][k]])

        allp = range(len(pairs))
        te, sy, ha = m(test), metrics(list(res["syn"].values())), metrics(list(res["half"].values()))
        return {"test": [te["top1"], te["top5"], te["top10"], te["mrr"]], "tune_mrr": m(tune)["mrr"],
                "all_top5": {sub: m(allp, sub)["top5"] for sub in ("ext", "orig_remix", "remix_remix")},
                "all_top1": {sub: m(allp, sub)["top1"] for sub in ("ext", "orig_remix", "remix_remix")},
                "test_top5": {sub: m(test, sub)["top5"] for sub in ("ext", "orig_remix", "remix_remix")},
                "syn_top1_top5": [sy["top1"], sy["top5"]], "half_top1_top5": [ha["top1"], ha["top5"]]}

    out["table"] = {}
    per_stem = {}
    print("== per stem: tune-best variant | test top1/top5/top10/MRR | all-pairs top5 per subgroup | synthetic | own-half ==")
    for stem in STEMS:
        k = max((k for k in results if k[0] == stem), key=lambda k: (pair_metrics(k, tune)["mrr"], pair_metrics(k, tune)["top5"]))
        per_stem[stem] = k
        out["table"][stem] = {"variant": list(k), "valid_share": results[k]["valid_share"], **line(results[k])}
        print(stem, out["table"][stem])
    for name, (s1, s2) in (("fusion vocals+ov", ("vocals", "ov")), ("fusion vocals+other", ("vocals", "other"))):
        k1, k2 = per_stem[s1], per_stem[s2]
        res = evaluate(np.minimum(results[k1]["track"], results[k2]["track"]), np.minimum(results[k1]["half_m"], results[k2]["half_m"]))
        out["table"][name] = {"variant": [list(k1), list(k2)], **line(res)}
        print(name, out["table"][name])
        out["table"][name]["pair_ranks"] = [[p["a"], p["b"], p["sub"], *res["ranks"][k]] for k, p in enumerate(pairs)]
    n_te = {sub: sum(pairs[k]["sub"] == sub for k in test) for sub in ("ext", "orig_remix", "remix_remix")}
    print("test pairs per subgroup:", n_te, "| pairs per subgroup:", {sub: sum(p["sub"] == sub for p in pairs) for sub in n_te})

    # ---- marginals over all pairs (exploratory): best variant per stem / fp / L / voice
    def best_of(pred, which=None):
        ks = [k for k in results if pred(k)]
        k = max(ks, key=lambda k: pair_metrics(k, tune)["mrr"])
        return k, pair_metrics(k, test), pair_metrics(k, range(len(pairs))), metrics(list(results[k]["half"].values())), \
            metrics(list(results[k]["syn"].values()))

    out["marginals"] = {}
    print("\n== per dimension: variant with the best tune MRR -> test | all pairs | own-half | synthetic ==")
    for name, pos, vals in (("stem", 0, STEMS), ("voice", 1, VOICES), ("loop", 2, LOOPS), ("fp", 3, FPS), ("min_pcs", 4, MIN_PCS)):
        for v in vals:
            k, mt, ma, mh, ms = best_of(lambda kk, pos=pos, v=v: kk[pos] == v)
            out["marginals"][f"{name}={v}"] = {"variant": list(k), "test": mt, "all": ma, "half": mh, "syn": ms}
            print(f"{name}={v}: {k} test {mt} | all {ma} | half {mh} | syn {ms}")
    # mean over variants per stem: less selection-biased view of what separation buys
    print("\n== mean over all variants per stem (all pairs MRR / top5; own-half top1; synthetic top1) ==")
    out["stem_means"] = {}
    for stem in STEMS:
        ks = [k for k in results if k[0] == stem]
        row = {"pair_mrr": round(float(np.mean([pair_metrics(k, range(len(pairs)))["mrr"] for k in ks])), 3),
               "pair_top5": round(float(np.mean([pair_metrics(k, range(len(pairs)))["top5"] for k in ks])), 3),
               "half_top1": round(float(np.mean([metrics(list(results[k]["half"].values()))["top1"] for k in ks])), 3),
               "syn_top1": round(float(np.mean([metrics(list(results[k]["syn"].values()))["top1"] for k in ks])), 3)}
        out["stem_means"][stem] = row
        print(stem, row)
    print("\nloop info (chosen stem/voice/L):", loopinfo[best[:3]])
    # found pairs under the chosen variant: which ones, which subgroup, key tag shift
    hits = [(pairs[k]["sub"], pairs[k]["key_shift"], pairs[k]["dbpm"], results[best]["ranks"][k]) for k in range(len(pairs))]
    out["pair_ranks"] = [[pairs[k]["a"], pairs[k]["b"], pairs[k]["sub"], pairs[k]["key_shift"], pairs[k]["dbpm"],
                          *results[best]["ranks"][k], k in test] for k in range(len(pairs))]
    print("\npairs with a rank <= 5 in either direction:", sum(min(h[3]) <= 5 for h in hits), "of", len(hits))
    for sub in ("ext", "orig_remix", "remix_remix"):
        hs = [h for h in hits if h[0] == sub]
        print(sub, "n", len(hs), "hit<=5", sum(min(h[3]) <= 5 for h in hs),
              "| key tag shifted:", sum(h[1] not in (0, None) for h in hs), "of which hit<=5:",
              sum(min(h[3]) <= 5 for h in hs if h[1] not in (0, None)))
    # ---- transposition actually found between pair members (pc fingerprint of the chosen stem / voice / L)
    flat, snd = all_loops[best[:3]]
    Fpc = np.array([fingerprint(x, "pc") for x in flat]).astype(np.int16)
    trans = []
    for k, p in enumerate(pairs):
        a, b = ix[p["a"]], ix[p["b"]]
        cand = []
        for i in range(4):
            for j in range(4):
                if snd[a * 4 + i] >= 4 and snd[b * 4 + j] >= 4:
                    d, t = best_transposition(Fpc[a * 4 + i], Fpc[b * 4 + j], BAND, REST)
                    cand.append((d / max(snd[a * 4 + i], snd[b * 4 + j]), int(t)))
        if cand:
            d, t = min(cand)
            tag = None if p["key_shift"] is None else (-p["key_shift"]) % 12
            trans.append({"sub": p["sub"], "rank": min(results[best]["ranks"][k]), "t": t, "t_from_key_tags": tag, "d": round(float(d), 3)})
    found = [x for x in trans if x["rank"] <= 5]
    out["transposition"] = {
        "pairs_found_rank_le5": len(found),
        "found_with_t_nonzero": sum(x["t"] != 0 for x in found),
        "found_t_hist": {str(t): sum(x["t"] == t for x in found) for t in range(12) if any(x["t"] == t for x in found)},
        "found_t_agrees_with_key_tags": sum(x["t"] == x["t_from_key_tags"] for x in found),
        "ext_found": sum(x["sub"] == "ext" for x in found),
        "ext_found_t_nonzero": sum(x["sub"] == "ext" and x["t"] != 0 for x in found),
    }
    print("transposition between found pairs:", out["transposition"])

    # ---- reference without notes: mean-pooled CLAP embedding of the mix (cosine)
    try:
        E = np.stack([np.load(M.OUT / "clap" / f"{t}.npy")[0].astype(np.float32) for t in real])
        E /= np.linalg.norm(E, axis=-1, keepdims=True)
        pooled = E.mean(1)
        pooled /= np.linalg.norm(pooled, axis=-1, keepdims=True)
        dc = 1.0 - pooled @ pooled.T
        cr = {k: (rank_of(dc[ix[p["a"]]], ix[p["b"]], {ix[p["a"]]}), rank_of(dc[ix[p["b"]]], ix[p["a"]], {ix[p["b"]]}))
              for k, p in enumerate(pairs)}
        out["clap_pooled_reference"] = {"all": metrics([x for v in cr.values() for x in v]),
                                        "test": metrics([x for k in test for x in cr[k]])}
        for sub in ("ext", "orig_remix", "remix_remix"):
            out["clap_pooled_reference"][sub] = metrics([x for k, v in cr.items() if pairs[k]["sub"] == sub for x in v])
        print("reference CLAP pooled mix cosine:", out["clap_pooled_reference"])
    except FileNotFoundError as exc:
        print("clap reference skipped:", exc)
    (M.OUT / "retrieval.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
