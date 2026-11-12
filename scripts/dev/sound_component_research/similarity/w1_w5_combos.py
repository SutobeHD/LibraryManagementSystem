"""Final W1 / W5 combinations on top of eval_sim.py (re-runs it silently)."""
import contextlib
import io
from pathlib import Path

HERE = Path(__file__).resolve().parent
g = {"__file__": str(HERE / "eval_sim.py"), "__name__": "eval_sim"}
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile((HERE / "eval_sim.py").read_text(encoding="utf-8"), str(HERE / "eval_sim.py"), "exec"), g)
norm_med, RES, report_D, genre_split = g["norm_med"], g["RES"], g["report_D"], g["genre_split"]
L = "line = rhy_flux16 + pit_C12_oti_u8"
for tag, snd in (("off", "snd_hrel6_off"), ("on", "snd_hrel4_on"), ("off4", "snd_hrel4_off")):
    nm = f"W1 {tag}: 0.5 {snd} + 0.5 line12u8"
    report_D(nm, 0.5 * norm_med(RES[snd]["A"][1]) + 0.5 * norm_med(RES[L]["A"][1]),
             0.5 * norm_med(RES[snd]["B"][1]) + 0.5 * norm_med(RES[L]["B"][1]), 0)
    genre_split(nm)
D1A = 0.75 * norm_med(RES["hat_postpow24"]["A"][1]) + 0.25 * norm_med(RES["hat_decay"]["A"][1])
D1B = 0.75 * norm_med(RES["hat_postpow24"]["B"][1]) + 0.25 * norm_med(RES["hat_decay"]["B"][1])
report_D("hat snd 0.75 postpow24 + 0.25 decay", D1A, D1B, 31)
genre_split("hat snd 0.75 postpow24 + 0.25 decay")
for w in (0.5, 0.75):
    nm = f"W5 {w} hat snd + {1 - w} flux16"
    report_D(nm, w * norm_med(D1A) + (1 - w) * norm_med(RES["hat_flux16"]["A"][1]),
             w * norm_med(D1B) + (1 - w) * norm_med(RES["hat_flux16"]["B"][1]), 47)
    genre_split(nm)
genre_split("hat_pre24")
genre_split("hat_postpow24")
