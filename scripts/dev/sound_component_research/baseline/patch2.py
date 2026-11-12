"""One-off patch of features.py after the label-free picker tuning (tune_hats.py)."""
from pathlib import Path

p = Path(__file__).parent / "features.py"
s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (s.count(old), old[:80])
    s = s.replace(old, new)


# 1) envelope smoother length as a parameter (ms)
rep('''def env_power(x, dec=DEC_ENV):
    """Power envelope: boxcar 2*dec samples, decimate by dec, 5-tap Hann. Rate fs/dec."""
    e = ndi.uniform_filter1d(x * x, size=2 * dec, mode="nearest")[::dec]
    w = np.hanning(7)[1:-1]
    return np.maximum(np.convolve(e, w / w.sum(), mode="same"), 1e-14)
''', '''def env_power(x, dec=DEC_ENV, smooth_ms=5.0, fs_in=SR):
    """Power envelope: boxcar 2*dec samples, decimate by dec, Hann of smooth_ms. Rate fs_in/dec."""
    e = ndi.uniform_filter1d(x * x, size=2 * dec, mode="nearest")[::dec]
    n = max(3, int(round(smooth_ms * (fs_in / dec) / 1000.0)) | 1)
    w = np.hanning(n + 2)[1:-1]
    return np.maximum(np.convolve(e, w / w.sum(), mode="same"), 1e-14)
''')

# 2) hats: pick on a 10 ms envelope (tuned), decay on the 5 ms envelope, flux profile
rep('''def hat_onsets(y, sos, delta=0.25):
    x = sg.sosfiltfilt(sos, y)
    e = env_power(x)
    on, pk, strength = pick_onsets(e, FS_ENV, delta=delta)
    return e, on, pk, strength
''', '''PICK_SMOOTH_MS = 10.0     # label-free tuning (tune_hats.py): 10 ms / delta 0.25 -> median
PICK_DELTA = 0.25         # spurious share 11 % (5 ms: 44 %) at the best on-lattice yield


def hat_onsets(y, sos, delta=PICK_DELTA):
    """Returns (fine 5 ms envelope for decays, 10 ms pick envelope, onset idx, peak idx)."""
    x = sg.sosfiltfilt(sos, y)
    e_fine = env_power(x, smooth_ms=5.0)
    e_pick = env_power(x, smooth_ms=PICK_SMOOTH_MS)
    on, pk, _strength = pick_onsets(e_pick, FS_ENV, delta=delta)
    return e_fine, e_pick, on, pk


def flux_profile(e_pick, bt, bn, dur):
    """Threshold-free variant: positive rise of the log-compressed envelope, by grid position."""
    _nov, lg = novelty(e_pick, FS_ENV)
    dl = np.maximum(np.diff(lg, prepend=lg[0]), 0.0)
    t = np.arange(len(dl)) / FS_ENV
    ii, ph, ok = beat_phase(t, bt)
    ok &= (t >= 0.05) & (t <= dur - 0.05)
    nb = int(((bt >= 0.05) & (bt <= dur - 0.05)).sum())
    tot = float(dl[ok].sum())
    if nb < 16 or tot <= 0:
        return {}, None
    p, w = ph[ok], dl[ok]

    def share(*centers):
        m = np.zeros(len(p), dtype=bool)
        for c in centers:
            m |= np.abs(((p - c + 0.5) % 1.0) - 0.5) <= TOL
        return float(w[m].sum() / tot), m

    s_on, m1 = share(0.0)
    s_off, m2 = share(0.5)
    s_16, m3 = share(0.25, 0.75)
    s_tri, m4 = share(1 / 3, 2 / 3)
    out = {"flux_per_beat": tot / nb, "flux_on": s_on, "flux_off": s_off, "flux_16": s_16,
           "flux_tri": s_tri, "flux_other": float(w[~(m1 | m2 | m3 | m4)].sum() / tot)}
    step = ((bn[ii[ok]] - 1) * 4 + np.round(p * 4).astype(int)) % 16
    hist = np.bincount(step, weights=w, minlength=16) / (nb / 4.0)
    return out, hist
''')

# 3) melody: voiced threshold is arbitrary without labels -> keep three variants
rep('''    voiced = act & (ratio >= 2.5)
    out["voiced_share"] = float(voiced.mean())
    pc = np.where(voiced, midi[top] % 12, -1)
    edges = np.nonzero(np.diff(pc) != 0)[0] + 1
    starts = np.concatenate(([0], edges))
    ends = np.concatenate((edges, [len(pc)]))
    notes = [(s, e, pc[s]) for s, e in zip(starts, ends) if pc[s] >= 0 and e - s >= 3]
    changes = sum(1 for a, b in zip(notes, notes[1:]) if b[2] != a[2] and b[0] - a[1] <= 12)
    secs = S.shape[1] * HOP / SR
    out["note_changes_per_s"] = float(changes / secs)
    out["note_changes_per_beat"] = float(changes / n_beats) if n_beats else None
    out["n_notes"] = len(notes)
''', '''    out["pitch_salience_p90"] = float(np.percentile(ratio[act], 90))
    secs = S.shape[1] * HOP / SR
    for thr in (3.0, 4.5, 6.0):
        voiced = act & (ratio >= thr)
        pc = np.where(voiced, midi[top] % 12, -1)
        edges = np.nonzero(np.diff(pc) != 0)[0] + 1
        starts = np.concatenate(([0], edges))
        ends = np.concatenate((edges, [len(pc)]))
        notes = [(s, e, pc[s]) for s, e in zip(starts, ends) if pc[s] >= 0 and e - s >= 3]
        changes = sum(1 for a, b in zip(notes, notes[1:]) if b[2] != a[2] and b[0] - a[1] <= 12)
        tag = f"_t{int(thr * 10)}"
        out["voiced_share" + tag] = float(voiced.mean())
        out["note_changes_per_beat" + tag] = float(changes / n_beats) if n_beats else None
        out["notes_per_beat" + tag] = float(len(notes) / n_beats) if n_beats else None
        if thr == 4.5:
            keep_notes = notes
            out["note_changes_per_s"] = float(changes / secs)
    notes = keep_notes
    out["n_notes"] = len(notes)
''')

# 4) bass: valid beats from the whole-interval maximum; event-based decays
rep('''    ref = np.percentile(peak_db, 90)
    valid = peak_db >= ref - 12.0
''', '''    full_max = np.array([e120db[max(ix(a - 0.05 * T[j]), 0) : ix(b - 0.05 * T[j])].max()
                         for j, (a, b) in enumerate(beats)])
    valid = full_max >= np.percentile(full_max, 90) - 12.0
''')
rep('''    out["low_onsets_per_beat"] = float(len(ph) / nb)
    out["low_onbeat_per_beat"] = float((dist(ph, 0.0) <= 0.08).sum() / nb)
    out["low_offbeat_per_beat"] = float((dist(ph, 0.5) <= 0.08).sum() / nb)
''', '''    out["low_onsets_per_beat"] = float(len(ph) / nb)
    out["low_onbeat_per_beat"] = float((dist(ph, 0.0) <= 0.10).sum() / nb)
    out["low_offbeat_per_beat"] = float((dist(ph, 0.5) <= 0.10).sum() / nb)
    out["low_between_per_beat"] = float((dist(ph, 0.0) > 0.10).sum() / nb)
    # event-based decay: T20 of every low-band onset, censored at the next low onset
    sel = ok & (t_on > 0.05) & (t_on < dur - 0.05)
    ev_t20, _ev_t10 = _decay_t20(envbp ** 2, _pk, fs, cap_ms=1000.0, guard_ms=10.0)
    ev = ev_t20[sel]
    is_on = dist(ph, 0.0) <= 0.10
    fin = np.isfinite(ev)
    out["kick_t20_ms"] = float(np.median(ev[fin & is_on])) if (fin & is_on).sum() >= 8 else None
    out["bassnote_t20_ms"] = float(np.median(ev[fin & ~is_on])) if (fin & ~is_on).sum() >= 8 else None
    out["lowevent_t20_ms"] = float(np.median(ev[fin])) if fin.sum() >= 8 else None
''')
p.write_text(s, encoding="utf-8")
print("patched ok")
