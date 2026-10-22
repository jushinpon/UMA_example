# RUNBOOK — symptom → action

Fast triage for a misbehaving UMA job. Read `AGENTS.md` (Output Contract,
PBC Handling, Health Guards) before using this table.

## Job died / no usable .sout

| Symptom | Cause | Action |
|---|---|---|
| `ZeroDivisionError ... get_temperature` during OPT-1 | all atoms fixed → dof = 0 | **Fixed** (dof==0 → 0.0). If seen, the repo predates the fix — `git pull`. |
| Cell-assert failure right after OPT-2 or EQ | atoms crossed a **periodic** boundary; ASE MD never wraps | **Fixed** (wrap periodic axes only). If seen, `git pull`. |
| `[EQ-MD]/[PROD-MD] divergence at step N: E=... T=... vol=...` | one bad UMA force dissociated the system | Expected abort. Frames before N are still valid, but the run is unusable — fix the cause (bad structure/params) and rerun. Never train on a diverged partial run. |
| `torch` crash / empty `.sout` | OOM, timeout, or node death | `sacct -j <jobid>`; resubmit with `submit_sh4allDead.pl`. |
| 0 `!` energy blocks in `.sout` | job never reached PROD, or wrong grep pattern | Use line-start pattern: `grep -c "^!" file.sout`. Then check `stage_*.txt` for how far it got. |

## Outputs look wrong

| Symptom | Cause | Action |
|---|---|---|
| `thermo_summary.png` shows empty panels (6 blank axes; "No artists with labels" in `.err`) | old `plot_thermo.py` skipped the commented `#` header, columns became col0..colN | **Fixed**; regenerate: `python scripts/plot_thermo.py <job_dir>` (needs `fairchem` env). |
| `!`-block count ≠ 500 | wrong `prod_steps`/`prod_freq` in the job `.sh` | Convention: `prod_steps=10000`, `prod_freq=20` → **500** frames (`prod_steps//prod_freq`; the trailing structure at step 10000 carries no energy/forces and the converter drops it). Check the `.sh` arg line and rerun. |
| `data_files/` count ≠ 500 | ditto | `ls data_files \| wc -l` → 500 per finished job. |
| Coordinates outside the box in a snapshot | ASE MD does not wrap; unwrapped coords are normal in periodic runs | Do not hand-edit; wrap at conversion time if the consumer needs it. |
| PBC flag looks wrong | geometry near the 6.0 Å vacuum-gap threshold | Check the `[PBC] ...` log line; force a setting with env `UMA_PBC="T T F"` (per axis) and rerun. |
| `QEout_plot.png` / `sout_data.csv` missing or stale | written by **external** `/opt/qe_perl/QEout_analysis.pl` at job end, not by repo code | Re-run the perl step or accept repo plots (`thermo_summary.png`, `*_eq_profile.png`) as the authoritative view. |

## Routine operations

| Task | Command |
|---|---|
| Job status (Done/Running/Dead) | `perl scripts/check_UMAjobs.pl` |
| Resubmit dead jobs | `perl scripts/submit_sh4allDead.pl` |
| Regenerate thermo plots for a job | `python scripts/plot_thermo.py <job_dir>` |

Rules: submit with `sbatch` only (never `srun`/`salloc`); no compute on
login/master nodes; all repo files LF.
