"""Probe 4 (W6 "how melodic" = lead, not pad): scalar candidates from basic-pitch notes on the
`other` stem (and on the mix as the no-separation baseline) vs the user's own tags.

Scalars (4 x 30 s windows, Rekordbox grid; lead register = MIDI 60..96)
  lead_density  lead-register note onsets per beat
  all_density   all note onsets per beat
  lead_cover    share of 16th steps with a sounding lead note (top voice)
  pcs_bar       distinct pitch classes per bar (mean)
  range_bar     highest minus lowest lead pitch per bar (mean, 0 for empty bars)
  move_rate     pitch changes between successive sounding steps, per beat
  repeat_share  share of bars with >= 3 sounding steps that agree >= 75 % with another bar of the window
  note_len      mean lead note length in beats (pads long, leads short)
  short_share   share of lead notes <= 0.5 beat
  other_share / vocals_share   stem energy share (needs separation)
Labels: tag Melodic vs user-tagged tracks without it, same Genre field mix (noisy negatives: a
missing tag is not a "not melodic" verdict).
"""

import json

import mcommon as M
import numpy as np
from analyze_melody import REST, bar_steps, step_matrix
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 20261113
LEAD = (60, 96)
NOTE_SCALARS = ["lead_density", "all_density", "lead_cover", "pcs_bar", "range_bar", "move_rate", "repeat_share",
                "note_len", "short_share"]
STEM_SCALARS = ["other_share", "vocals_share"]
# extra candidates for the melody type "acid line" (W7); low register = MIDI 36..59
ACID_NOTE = ["low_density", "low_short_share", "bend_mean"]
ACID_STEM = ["bass_share", "drums_share"]


def scalars(rec, tr, variant, windows=None):
    beats = np.array(tr["beats_ms"]) / 1000.0
    n_beats = n_lead = n_all = n_low = 0
    low_lens, bends = [], []
    lens, bars_all, moves, repeat_hits, n_bars = [], [], 0, 0, 0
    for w, start in enumerate(rec["wins"]):
        if windows is not None and w not in windows:
            continue
        bars = bar_steps(beats, tr["bib0"], start, 1.0)
        if not len(bars):
            continue
        end = bars[-1][-1]
        beat_len = float(np.mean(np.diff(bars[:, ::4], axis=1)))
        notes = [n for n in rec["notes"][variant][w] if n[0] < end]
        lead = [n for n in notes if LEAD[0] <= n[2] <= LEAD[1]]
        n_beats += 4 * len(bars)
        n_all += len(notes)
        n_lead += len(lead)
        lens += [(n[1] - n[0]) / beat_len for n in lead]
        low = [n for n in notes if 36 <= n[2] <= 59]
        n_low += len(low)
        low_lens += [(n[1] - n[0]) / beat_len for n in low]
        bends += [n[4] for n in notes if 36 <= n[2] <= 72]
        P = step_matrix(notes, bars, "top", *LEAD)
        bars_all.append(P)
        seq = P.reshape(-1)
        snd = seq[seq != REST]
        moves += int(np.sum(np.diff(snd) != 0))
        ok = (P != REST).sum(1) >= 3
        for i in range(len(P)):
            if not ok[i]:
                continue
            either = (P[i][None, :] != REST) | (P != REST)
            agree = ((P[i][None, :] == P) & either).sum(1) / np.maximum(1, either.sum(1))
            agree[i] = 0
            repeat_hits += bool(np.any(agree >= 0.75))
        n_bars += len(P)
    if not n_beats:
        return None
    P = np.concatenate(bars_all)
    snd = P != REST
    pcs = [len(set((row[row != REST] % 12).tolist())) for row in P]
    rng_ = [int(row[row != REST].max() - row[row != REST].min()) if (row != REST).any() else 0 for row in P]
    out = {
        "lead_density": n_lead / n_beats,
        "all_density": n_all / n_beats,
        "lead_cover": float(snd.mean()),
        "pcs_bar": float(np.mean(pcs)),
        "range_bar": float(np.mean(rng_)),
        "move_rate": moves / n_beats,
        "repeat_share": repeat_hits / max(1, n_bars),
        "note_len": float(np.mean(lens)) if lens else np.nan,
        "short_share": float(np.mean(np.array(lens) <= 0.5)) if lens else 0.0,
    }
    out["low_density"] = n_low / n_beats
    out["low_short_share"] = float(np.mean(np.array(low_lens) <= 0.25)) if low_lens else 0.0
    out["bend_mean"] = float(np.mean(bends)) if bends else 0.0
    if variant == "other":
        en = np.array(rec["energy"])  # columns: drums, bass, other, vocals
        if windows is not None:
            en = en[list(windows)]
        out["other_share"] = float(en[:, 2].mean())
        out["vocals_share"] = float(en[:, 3].mean())
        out["bass_share"] = float(en[:, 1].mean())
        out["drums_share"] = float(en[:, 0].mean())
    return out


def auc(pos, neg):
    y = np.r_[np.ones(len(pos)), np.zeros(len(neg))]
    return float(roc_auc_score(y, np.r_[pos, neg]))


def auc_ci(pos, neg, n=1000):
    rng = np.random.default_rng(SEED)
    pos, neg = np.asarray(pos), np.asarray(neg)
    vals = [auc(rng.choice(pos, len(pos)), rng.choice(neg, len(neg))) for _ in range(n)]
    return [round(float(np.percentile(vals, 2.5)), 3), round(float(np.percentile(vals, 97.5)), 3)]


def cv_lr(X, y, repeats=20):
    aucs = []
    for r in range(repeats):
        oof = np.zeros(len(y))
        for tr_i, te_i in StratifiedKFold(5, shuffle=True, random_state=SEED + r).split(X, y):
            clf = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000))
            clf.fit(X[tr_i], y[tr_i])
            oof[te_i] = clf.decision_function(X[te_i])
        aucs.append(roc_auc_score(y, oof))
    return round(float(np.mean(aucs)), 3), round(float(np.std(aucs)), 3)


def main():
    S = M.load_samples()
    recs = {r["id"]: r for r in M.load_notes() if r["k"] == 0}
    feats = {"other": {}, "mix": {}}
    halves = {}
    for tid, r in recs.items():
        tr = S["tracks"][tid]
        for v in ("other", "mix"):
            if v in r["notes"]:
                f = scalars(r, tr, v)
                if f:
                    feats[v][tid] = f
        if min(np.diff(tr["wins"])) >= M.WIN_S:
            halves[tid] = (scalars(r, tr, "other", (0, 1)), scalars(r, tr, "other", (2, 3)))
    med_len = {v: float(np.nanmedian([f["note_len"] for f in feats[v].values()])) for v in feats}
    n_nolead = sum(np.isnan(f["note_len"]) for f in feats["other"].values())
    for v in feats:
        for f in feats[v].values():
            if np.isnan(f["note_len"]):
                f["note_len"] = med_len[v]
    print(f"tracks with scalars: other {len(feats['other'])}, mix {len(feats['mix'])}; no lead note at all: {n_nolead}")

    sets = {k: [i for i in v if i in feats["other"]] for k, v in S["sets"].items()}
    out = {"n": {k: len(v) for k, v in sets.items()}}
    pairs_used = [(p["a"], p["b"], p["sub"]) for p in json.loads((M.OUT / "pairs.json").read_text(encoding="utf-8"))["chosen"]]
    targets = {
        "Melodic": (sets["tag_Melodic"], sets["neg_Melodic"]),
        "Synth": (sets["tag_Synth"], [i for i in sets["neg_Melodic"] if "Synth" not in S["tracks"][i]["tags"]]),
        "Trance_vs_HardTechno(genre field)": (sets["genre_Trance"], sets["genre_Hard Techno"]),
        "Trance_vs_Raw(genre field)": (sets["genre_Trance"], sets["genre_Raw"]),
    }
    techno = sets["genre_Raw"] + sets["genre_Hard Techno"] + sets["genre_Groove"]
    targets["Acid crate folder vs Raw / Hard Techno / Groove (genre field)"] = (sets.get("folder_acid", []), techno)
    pop_edit = [i for a_, b_, sub in pairs_used if sub == "remix_remix" for i in (a_, b_) if i in feats["other"]]
    targets["Vocal proxy: both-remix pair members (edits of pop songs) vs distractors"] = (
        pop_edit, [i for i in sets["distract"] if i not in pop_edit])
    for name, (pos, neg) in targets.items():
        print(f"\n== {name}: {len(pos)} pos vs {len(neg)} neg ==")
        res = {"n_pos": len(pos), "n_neg": len(neg), "auc": {}}
        if len(pos) < 10 or len(neg) < 10:
            out[name] = res
            continue
        acid = name.startswith("Acid")
        note_cols = NOTE_SCALARS + (ACID_NOTE if acid else [])
        stem_cols = STEM_SCALARS + (ACID_STEM if acid else [])
        for v in ("other", "mix"):
            cols = note_cols + (stem_cols if v == "other" else [])
            for c in cols:
                a_ = auc([feats[v][i][c] for i in pos], [feats[v][i][c] for i in neg])
                res["auc"][f"{v}:{c}"] = round(a_, 3)
            print(v, {c: res["auc"][f"{v}:{c}"] for c in cols})
        best = max((k for k in res["auc"] if k.startswith("other:")), key=lambda k: abs(res["auc"][k] - 0.5))
        c = best.split(":")[1]
        res["best_other"] = [best, res["auc"][best], auc_ci([feats["other"][i][c] for i in pos], [feats["other"][i][c] for i in neg])]
        print("best single scalar on other:", res["best_other"])
        y = np.r_[np.ones(len(pos)), np.zeros(len(neg))]
        for label, v, cols in (("LR notes(other)", "other", note_cols), ("LR notes+stem shares(other)", "other", note_cols + stem_cols),
                               ("LR stem shares only", "other", stem_cols), ("LR notes(mix, no separation)", "mix", note_cols)):
            X = np.array([[feats[v][i][c] for c in cols] for i in pos + neg])
            res[label] = cv_lr(X, y)
            print(f"{label}: CV AUC {res[label][0]} +- {res[label][1]}")
        out[name] = res

    # transfer: model fitted on Melodic vs negatives, scored on the genre sets
    pos, neg = targets["Melodic"]
    cols = NOTE_SCALARS + STEM_SCALARS
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000))
    clf.fit(np.array([[feats["other"][i][c] for c in cols] for i in pos + neg]), np.r_[np.ones(len(pos)), np.zeros(len(neg))])
    score = {i: float(clf.decision_function(np.array([[f[c] for c in cols]]))[0]) for i, f in feats["other"].items()}
    out["transfer"] = {}
    for a_, b_ in (("genre_Trance", "genre_Hard Techno"), ("genre_Trance", "genre_Raw"), ("genre_Trance", "genre_Groove")):
        out["transfer"][f"{a_}>{b_}"] = round(auc([score[i] for i in sets[a_]], [score[i] for i in sets[b_]]), 3)
    print("\nMelodic-model score, AUC between genre sets:", out["transfer"])
    coefs = dict(zip(cols, np.round(clf[-1].coef_[0], 2).tolist()))
    print("standardised coefficients:", coefs)
    out["coef"] = coefs

    # retest: windows 1-2 vs 3-4 (non-overlapping), Spearman per scalar
    out["retest"] = {}
    for c in NOTE_SCALARS + STEM_SCALARS:
        a_ = [h[0][c] for h in halves.values() if h[0] and h[1]]
        b_ = [h[1][c] for h in halves.values() if h[0] and h[1]]
        ok = ~(np.isnan(a_) | np.isnan(b_))
        out["retest"][c] = round(float(spearmanr(np.array(a_)[ok], np.array(b_)[ok]).statistic), 2)
    print("\nretest Spearman (windows 1-2 vs 3-4, n =", len(halves), "):", out["retest"])

    # too few for statistics: percentile of each tagged track inside all processed tracks
    allv = {c: np.array([f[c] for f in feats["other"].values()]) for c in cols}
    bends = {}
    for tid, r in recs.items():
        nts = [n for w in r["notes"].get("other", []) for n in w if 36 <= n[2] <= 72]
        bends[tid] = float(np.mean([n[4] for n in nts])) if nts else 0.0
    ball = np.array(list(bends.values()))
    out["small_tags"] = {}
    for tag in ("tag_Vocal", "tag_Acid"):
        rows = []
        for i in sets[tag]:
            row = {c: round(float(np.mean(allv[c] <= feats["other"][i][c])), 2) for c in ("vocals_share", "other_share", "lead_density", "note_len")}
            row["vocals_share_abs"] = round(feats["other"][i]["vocals_share"], 3)
            row["bend_pct"] = round(float(np.mean(ball <= bends[i])), 2)
            row["melodic_score_pct"] = round(float(np.mean(np.array(list(score.values())) <= score[i])), 2)
            rows.append(row)
        out["small_tags"][tag] = rows
        print(f"\n{tag} (n={len(rows)}), percentiles within all {len(allv['other_share'])} processed tracks:")
        for row in rows:
            print("  ", row)
    vs = np.array([feats["other"][i]["vocals_share"] for i in feats["other"]])
    out["vocals_share_dist"] = {"median": round(float(np.median(vs)), 4), "p90": round(float(np.percentile(vs, 90)), 4),
                                "share_ge_0.05": round(float(np.mean(vs >= 0.05)), 3)}
    print("vocals energy share over all tracks:", out["vocals_share_dist"])

    # post hoc: is a W8 pair found (rank <= 5, fused vocals + other+vocals fingerprint) more often
    # when both members carry a lead at all? split at the median lead_cover of all processed tracks
    ret = M.OUT / "retrieval.json"
    if ret.exists():
        med_cover = float(np.median(allv_cover := np.array([f["lead_cover"] for f in feats["other"].values()])))
        rows = json.loads(ret.read_text(encoding="utf-8"))["table"]["fusion vocals+ov"]["pair_ranks"]
        split = {}
        for a_, b_, sub, ra, rb in rows:
            lead = min(feats["other"][a_]["lead_cover"], feats["other"][b_]["lead_cover"]) >= med_cover
            cell = split.setdefault(f"{sub}/{'lead in both' if lead else 'no lead in one'}", [0, 0])
            cell[0] += min(ra, rb) <= 5
            cell[1] += 1
        out["pair_found_by_lead"] = {"median_lead_cover": round(med_cover, 3), "found_of_n": split, "n_tracks": len(allv_cover)}
        print("\npairs found (rank <= 5) / n, split by lead presence:", out["pair_found_by_lead"])
    (M.OUT / "w6.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (M.OUT / "w6_features.json").write_text(json.dumps({"other": feats["other"], "score": score}), encoding="utf-8")


if __name__ == "__main__":
    main()
