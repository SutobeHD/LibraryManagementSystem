"""Probe 5 (W3 mechanism proxy): K-shot classes on CLAP (`laion/clap-htsat-unfused`) window
embeddings. Bells cannot be tested without the user's examples; targets here are labels that
already exist: tags Melodic / Hard, Genre-field contrasts, and a pseudo-label "sparse vocal"
(vocals stem holds >= 5 % of the energy in exactly one of the four 30 s windows, < 1 % elsewhere).

Embeddings: 12 x 10 s windows per track (the 4 x 30 s analysis windows), mix and `other` stem.
  win_top3   classifier on window vectors (track label copied to its windows), track score =
             mean of the 3 highest window scores -> needs the window vectors at query time
  pooled     one mean vector per track, stored as float16 (512 x 2 B = 1 KB)
Classifiers: logistic regression (C = 1) and nearest prototype (cos to positive mean minus cos
to negative mean). K positives + K negatives, 50 random draws, AUC on all remaining tracks.
"""

import json

import mcommon as M
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

SEED = 20261113
KS = (3, 5, 10)
REPEATS = 50


def norm(x):
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-12)


def score_tracks(method, clf_kind, Wtr, ytr, Wte):
    """Wtr (n, 12, 512) train windows, Wte (m, 12, 512). -> track scores (m,)."""
    if method == "pooled":
        Xtr = norm(Wtr.mean(1).astype(np.float16).astype(np.float32))
        Xte = norm(Wte.mean(1).astype(np.float16).astype(np.float32))
    else:
        Xtr = Wtr.reshape(-1, Wtr.shape[-1])
        Xte = Wte.reshape(-1, Wte.shape[-1])
        ytr = np.repeat(ytr, Wtr.shape[1])
    if clf_kind == "lr":
        clf = LogisticRegression(C=1.0, max_iter=2000).fit(Xtr, ytr)
        s = clf.decision_function(Xte)
    else:
        s = Xte @ norm(Xtr[ytr == 1].mean(0)) - Xte @ norm(Xtr[ytr == 0].mean(0))
    if method == "pooled":
        return s
    s = s.reshape(len(Wte), -1)
    if method == "win_top3":
        return np.sort(s, axis=1)[:, -3:].mean(1)
    return s.mean(1)


def main():
    S = M.load_samples()
    recs = {r["id"]: r for r in M.load_notes() if r["k"] == 0}
    emb = {}
    for f in (M.OUT / "clap").glob("*.npy"):
        emb[f.stem] = norm(np.load(f).astype(np.float32))  # (2, 12, 512): mix, other
    sets = {k: [i for i in v if i in emb] for k, v in S["sets"].items()}
    tags = {i: set(t["tags"]) for i, t in S["tracks"].items()}
    reviewed = [i for i in sets["neg_Melodic"] + sets["tag_Melodic"] + sets["tag_Synth"] + sets["tag_Dark"] if "Hard" not in tags[i]]
    sparse_pos, sparse_neg = [], []
    for i, r in recs.items():
        if i not in emb:
            continue
        v = np.array(r["energy"])[:, 3]
        if (v >= 0.05).sum() == 1 and (np.sort(v)[:-1] < 0.01).all():
            sparse_pos.append(i)
        elif (v < 0.002).all():
            sparse_neg.append(i)
    targets = {
        "tag Melodic": (sets["tag_Melodic"], sets["neg_Melodic"]),
        "tag Hard": (sets["tag_Hard"], sorted(set(reviewed))),
        "genre Trance vs Hard Techno": (sets["genre_Trance"], sets["genre_Hard Techno"]),
        "genre Raw vs Groove": (sets["genre_Raw"], sets["genre_Groove"]),
        "crate folder acid vs Raw / Hard Techno / Groove": (
            sets.get("folder_acid", []), sets["genre_Raw"] + sets["genre_Hard Techno"] + sets["genre_Groove"]),
        "pseudo sparse vocal (1 of 4 windows)": (sparse_pos, sparse_neg),
    }
    out = {}
    rng = np.random.default_rng(SEED)
    for name, (pos, neg) in targets.items():
        pos, neg = sorted(set(pos)), sorted(set(neg) - set(pos))
        print(f"\n== {name}: {len(pos)} pos / {len(neg)} neg ==", flush=True)
        res = {"n_pos": len(pos), "n_neg": len(neg)}
        if len(pos) < 13 or len(neg) < 13:
            print("too few tracks, skipped")
            out[name] = res
            continue
        ids = pos + neg
        y = np.r_[np.ones(len(pos), dtype=int), np.zeros(len(neg), dtype=int)]
        for src, si in (("mix", 0), ("other", 1)):
            W = np.stack([emb[i][si] for i in ids])
            ceiling = {}
            for method in ("pooled", "win_top3"):  # all labels, 5-fold CV x 5: what many examples would reach
                aucs = []
                for r in range(5):
                    oof = np.zeros(len(y))
                    for tr, te in StratifiedKFold(5, shuffle=True, random_state=SEED + r).split(W, y):
                        oof[te] = score_tracks(method, "lr", W[tr], y[tr], W[te])
                    aucs.append(roc_auc_score(y, oof))
                ceiling[method] = round(float(np.mean(aucs)), 3)
            res[f"{src}/all-labels CV"] = ceiling
            print(f"{src} all labels 5-fold CV (LR): {ceiling}", flush=True)
            for K in KS:
                if K > len(pos) - 3:
                    continue
                acc = {}
                for _ in range(REPEATS):
                    tr = np.r_[rng.choice(len(pos), K, replace=False), len(pos) + rng.choice(len(neg), K, replace=False)]
                    te = np.setdiff1d(np.arange(len(ids)), tr)
                    for method in ("win_top3", "win_mean", "pooled"):
                        for kind in ("lr", "proto"):
                            s = score_tracks(method, kind, W[tr], y[tr], W[te])
                            acc.setdefault(f"{method}/{kind}", []).append(roc_auc_score(y[te], s))
                row = {m: [round(float(np.mean(v)), 3), round(float(np.percentile(v, 10)), 3), round(float(np.percentile(v, 90)), 3)]
                       for m, v in acc.items()}
                res[f"{src}/K{K}"] = row
                print(f"{src} K={K}: " + "  ".join(f"{m} {v[0]:.3f} [{v[1]:.2f}-{v[2]:.2f}]" for m, v in row.items()), flush=True)
        out[name] = res
    (M.OUT / "fewshot.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
