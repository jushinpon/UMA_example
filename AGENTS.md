# AGENTS.md — UMA_example
> **⚠️ 執行前必讀：** 請先閱讀 `AGENTS_WORKFLOW.md`，依序完成確認步驟後才能提交 job。

## Project Overview

FairChem UMA (Universal Materials Approach) ML potential pipeline.
Replaces expensive DFT calculations with machine-learning inference for relaxation + MD.

**Cluster:** any Slurm cluster (SSH alias/hostname is local configuration, not part of this repo) · **Conda env:** `fairchem` · **Partition:** `All` (the `.pl` default)

## Pipeline

```
LAMMPS .data → OPT-1 → OPT-2 → [Supercell] → Eq MD → Prod MD (heating) → fake QE output
```

1. **OPT-1**: Cell relaxation (FixAtoms, angles fixed)
2. **OPT-2**: Atoms + selected cell lengths (angles fixed)
3. **Supercell** (optional): Expand if < 12 Å, then OPT-2 again
4. **Eq MD**: Equilibrium MD (silent, no QE output; skip with eq_steps=0)
5. **Prod MD**: Production MD with **linear heating ramp** (prod_low → prod_high)

## gptfakeQE.py — CLI (22 args)

```bash
python gptfakeQE.py <input_data> <opt1_steps> <opt1_fmax> <opt2_steps> <opt2_fmax> \
    <npt_steps> <do_supercell 0/1> \
    <eq_steps> <eq_temp_K> <eq_press_GPa> <eq_timestep_fs> \
    <prod_steps> <prod_low_K> <prod_high_K> <prod_press_GPa> <prod_timestep_fs> <prod_freq> \
    <cx> <cy> <cz> <MODEL_NAME> <TASK_NAME>
```

### Key Arguments

| Arg | Description |
|-----|-------------|
| `do_supercell` | 0/1. Expand cell if shortest dim < 12 A |
| `eq_steps` | 0 = skip equilibrium MD |
| `prod_low_K` | Production MD starting temperature (heating ramp low) |
| `prod_high_K` | Production MD ending temperature (heating ramp high) |
| `prod_freq` | Output frequency: mod(step, prod_freq)==0 writes QE output |
| `cx cy cz` | 0/1 flags for cell DOF. 0 0 0 = NVT (cell fixed) |
| `MODEL_NAME` | `uma-s-1p2p1` (production default), `uma-s-1p1`, `uma-s-1` |
| `TASK_NAME` | UMA 1.2 heads: `omat`, `omol`, `oc20`, `oc22`, `oc25`, `odac`, `omc`. Production uses `oc25`; `omdyn` is **not** a FairChem task. |

### Temperature Ramp

Production MD applies a linear temperature ramp:
- Step 1: prod_low_K
- Step N: prod_high_K
- Each step: T(step) = prod_low + (step-1)/(prod_steps-1) * (prod_high - prod_low)
- Thermostat updated via dyn.set_temperature() at each step

## Running

```bash
# Activate conda
source /opt/anaconda3/bin/activate fairchem

# Arrange data + generate Slurm scripts (any cwd works — the .pl finds the repo root)
perl ~/UMA_example/scripts/arrange_data4UMA.pl
# WARNING: this deletes and rebuilds UMA_inputs/ — copy finished job dirs out first

# Submit all jobs
perl submit_allslurm_sh.pl

# Check job status
perl check_UMAjobs.pl

# Resubmit dead jobs
perl submit_sh4allDead.pl
```

## Quick Test (short run)

```bash
cd ~/UMA_example/test_run
sbatch test_heating.sh
# Check: tail -f test_heating.log
```

## Important Notes

- Conda env: fairchem (activate before running)
- GPU: Set export CUDA_VISIBLE_DEVICES=-1 for CPU-only
- SLURM: Use sbatch (never srun/salloc)
- Line endings: All scripts must be LF (Unix). Never CRLF.
- Model loading: First run downloads model weights; subsequent runs use cache
- Output: data_files/ dir contains .data snapshots; .sout is fake QE output

## PBC Handling (automatic)

The `.data` format cannot carry boundary flags, so `gptfakeQE.py` infers PBC
from geometry per job:

- Rule: any axis whose largest empty gap is ≥ 6.0 Å is treated as non-periodic.
- Expectations: bulk → `T T T`; isolated cluster → `F F F`; slab/surface →
  `T T F` (vacuum in z); water / solvated box → `T T T`.
- Override when geometry is borderline: env var `UMA_PBC="T T F"` (three
  space-separated flags) forces one setting for the whole job.
- Every log carries the verdict: `[PBC] T T F (vacuum-gap rule, ...)`.
- Cell DOF (`cx cy cz`) must agree with PBC: never relax the vacuum axis.

## Health Guards (built into gptfakeQE.py)

- `dof == 0` (all atoms fixed, e.g. OPT-1) → temperature is reported as 0.0
  instead of `ZeroDivisionError`.
- Cell assertions wrap atoms across **periodic** axes only (ASE MD does not
  wrap); an atom past a vacuum boundary still fails the run.
- EQ/PROD loops abort at the first non-finite E/T/volume or T > 5000 K
  (`[EQ-MD]/[PROD-MD] divergence at step N: ...`) **before** any corrupted
  frame is written. A diverged partial run is poison — do not train on it.

## Output Contract (one finished job)

With the DeePMD convention `prod_steps=10000`, `prod_freq=20`:

| Artifact | Expected |
|---|---|
| `data_files/*.data` | **500** snapshots (`prod_steps/prod_freq`) |
| `*.sout` | **500** `!` energy blocks (same count) |
| `stage_*.txt` | opt1/opt2/eq/prod logs; eq/prod start with `# step ...` header |
| `thermo_summary.png` | 6 panels **with curves** (blank panels = stale plot_thermo.py, see docs/RUNBOOK.md) |
| `*_eq_profile.png`, `QEout_plot.png`, `sout_data.csv` | eq 4-panel from the engine; QEout pair from external `/opt/qe_perl/QEout_analysis.pl` |

Quick verify: `ls <job>/data_files | wc -l` and `grep -c "^!" <job>/<name>.sout`
both → 500.

## Parameter Policy for DeePMD training datasets

- **One level of theory per dataset**: a single `model` + `task` for every
  file (like one DFT setting for a whole dataset). The electrocatalysis
  proposal uses `uma-s-1p2p1` + `oc25`. Never mix heads (omat/omol/oc22)
  inside one training database.
- Sampling conditions may vary per data class (timestep, heating ramp,
  cell DOF). The full per-class suggestion table **including EQ/PROD
  parameters** is in `AGENTS_WORKFLOW.md` Step 3.
- Evidence log (why mixing task heads corrupts a training set, why `oc25`
  is the solid-liquid-interface head, empirical head comparison, official
  tutorial cross-references): `docs/theory-level.md`.
- Optional D3 dispersion correction (knowledge note; NOT applied in
  production, opt-in only): `docs/dispersion-d3.md`.

## File Roles

| File | Role |
|------|------|
| gptfakeQE.py | Core: FairChem UMA inference + MD pipeline |
| arrange_data4UMA.pl | Generate job folders + Slurm scripts from categorized data |
| submit_allslurm_sh.pl | Submit all generated .sh scripts via sbatch |
| check_UMAjobs.pl | Monitor job status (Done/Running/Dead) |
| submit_sh4allDead.pl | Resubmit failed jobs |
| plot_thermo.py | Generates `thermo_summary.png` per job dir (run at job end) |
| mustRead.md | Detailed gptfakeQE.py manual (lives in `scripts/`, not the repo root) |
| docs/theory-level.md | Evidence log: one-task policy, oc25 domain, head comparison |
| docs/RUNBOOK.md | Symptom → action triage table |
