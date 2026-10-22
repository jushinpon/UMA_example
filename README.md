# UMA Example — FairChem ML Potential Pipeline

> **Cluster:** any Slurm cluster (site SSH alias is local config) · **Conda env:**`fairchem` · **FairChem:**`fairchem-core` 2.22.0 · **PyTorch:** 2.13.0+cu130 (jobs run CPU-pinned via `CUDA_VISIBLE_DEVICES=-1`)

---

## What This Does

This pipeline uses **FairChem's UMA (Universal Materials Approach)** machine-learning potential to replace expensive DFT calculations. It takes **LAMMPS `.data` structure files** and generates fake **Quantum ESPRESSO (QE) input/output** (`*.in`, `*.sout`) so downstream Perl analysis scripts can parse them seamlessly.

**In short:** LAMMPS `.data` → UMA relaxation + MD → QE-like output → your existing analysis tools.

---

## Quick Start (2 commands)

```bash
# Step 1: Arrange data and generate Slurm scripts
cd ~/UMA_example/scripts
perl arrange_data4UMA.pl

# Step 2: Submit all jobs
perl submit_allslurm_sh.pl
```

That's it. Two Perl scripts, two commands.

> `arrange_data4UMA.pl` resolves the repo root from its own location (`FindBin`), so it can be
> started from any directory: `perl /path/to/repo/scripts/arrange_data4UMA.pl`.

---

## Directory Structure

```
UMA_example/
├── README.md                          ← You are here
├── AGENTS.md                          ← Rules for agents/operators (output contract, PBC, guards)
├── AGENTS_WORKFLOW.md                 ← Step-by-step procedure to follow before every run
├── categorized_data4UMA/              ← PUT YOUR .data FILES HERE
│   ├── FCC/                           ← Example: FCC structures
│   │   ├── Al2Ni3_FCC.data
│   │   └── ...
│   ├── BCC/                           ← Example: BCC structures
│   ├── HCP/                           ← Example: HCP structures
│   ├── surface/                       ← any path containing "surface" gets $surface_c* cell DOF
│   └── ...                            ← Add your own categories
├── scripts/
│   ├── arrange_data4UMA.pl            ← Script 1: generate job folders + .sh files
│   ├── submit_allslurm_sh.pl          ← Script 2: submit all jobs via sbatch
│   ├── gptfakeQE.py                   ← Core: FairChem UMA inference engine
│   ├── check_UMAjobs.pl               ← Check job status (Done/Running/Dead)
│   ├── submit_sh4allDead.pl           ← Resubmit dead jobs
│   ├── plot_thermo.py                 ← Writes thermo_summary.png at job end
│   ├── README.md                      ← Scripts reference
│   └── mustRead.md                    ← gptfakeQE.py detailed manual
├── docs/
│   ├── RUNBOOK.md                     ← symptom → action triage
│   ├── theory-level.md                ← why one model + task per dataset
│   └── dispersion-d3.md               ← optional D3 note (NOT used in production)
└── UMA_inputs/                        ← GENERATED (after Step 1); wiped on every arrange run
    ├── FCC-UMA/
    │   ├── Al2Ni3_FCC-T300-P0/
    │   │   ├── Al2Ni3_FCC-T300-P0.data   (symlink)
    │   │   └── Al2Ni3_FCC-T300-P0.sh     (Slurm script)
    │   └── ...
    └── ...
```

---

## Step-by-Step Guide

### Step 0: Prepare Your Data Files

Place your **LAMMPS `.data` files** (atom_style atomic) into category folders under `categorized_data4UMA/`.

**Category naming:** Use descriptive names like `FCC`, `BCC`, `HCP`, `NP` (nanoparticle), `surface`, etc. These names appear in the output directory structure.

**Required format — `Masses` block must include element symbols:**

```
Masses

1 58.933194 # Co
2 51.9961   # Cr
3 63.546    # Cu
4 55.845    # Fe
5 58.6934   # Ni
6 50.9415   # V
```

> ⚠️ The `# Element` comment after each mass is **mandatory**. The script uses it to map atom types → atomic numbers. Without it, `gptfakeQE.py` will fail.

**Example:** the `Masses` block above shows the required shape — the `# Element` comments are what
`gptfakeQE.py` reads to map atom types to elements.

### Step 1: Arrange Data and Generate Scripts

```bash
cd ~/UMA_example/scripts
perl arrange_data4UMA.pl
```

**What it does:**

1. Scans all `.data` files under `categorized_data4UMA/`
2. Creates `UMA_inputs/<category>-UMA/<prefix>-T<temp>-P<press>/` for each file
3. Symlinks the `.data` file into the job folder
4. Generates a Slurm `.sh` script with your configured parameters

**Before running**, edit the top section of `arrange_data4UMA.pl` — it takes **no command-line arguments**; every knob is a `my $... = ...;` line there.

| Parameter | Default | Description |
|---|---|---|
| `@tempw` | `(300)` | **Folder-name label only** (`-T300`). Does **not** set any MD temperature. |
| `@press` | `(0)` | **Folder-name label only** (`-P0`). Does **not** set any MD pressure. |
| `$model` | `"uma-s-1p2p1"` | UMA checkpoint → `gptfakeQE.py` arg 21 |
| `$task` | `"oc25"` | FairChem task head → arg 22 |
| `$opt1_steps` | `250` | Optimization stage 1 steps |
| `$opt1_fmax` | `0.1` | OPT-1 force convergence (eV/A) |
| `$opt2_steps` | `250` | Optimization stage 2 steps |
| `$opt2_fmax` | `0.05` | OPT-2 force convergence (eV/A) |
| `$npt_steps` | `250` | **Legacy, ignored.** `gptfakeQE.py` parses it as arg 6 and never uses it; MD length comes from `$eq_steps` / `$prod_steps`. Leave the value (keep ≤ 999). |
| `$do_supercell` | `0` | Auto-build supercell if a cell length < 12 A |
| `$eq_steps` | `500` | Equilibrium MD steps (0 = skip eq). Proposal datasets use `10000`. |
| `$eq_temp` | `10` | Equilibrium temperature (K) — new systems since 2026-10-22 |
| `$eq_press` | `0` | Equilibrium pressure (GPa) |
| `$eq_timestep` | `1.0` | Equilibrium MD timestep (fs) |
| `$prod_steps` | `10000` | Production MD steps (0 = SCF only) |
| `$prod_low` | `10` | Heating-ramp start (K) — new systems since 2026-10-22 |
| `$prod_high` | `360` | Heating-ramp end (K) — override per data class |
| `$prod_press` | `0` | Production pressure (GPa) |
| `$prod_timestep` | `1.0` | Production MD timestep (fs) |
| `$prod_freq` | `20` | Output frequency: `mod(step, prod_freq)==0` writes a QE block. `10000/20` → 500 frames |
| `($bulk_cx,$bulk_cy,$bulk_cz)` | `(1,1,1)` | Cell DOF for every file whose path does **not** contain `surface` |
| `($surface_cx,$surface_cy,$surface_cz)` | `(0,0,0)` | Cell DOF for every file whose path **does** contain `surface` |

> **`@tempw` / `@press` are labels, not physics.** The `.pl` only uses them to name the output
> folder (`$prefix-T$t-P$p`). The numbers actually passed to `gptfakeQE.py` are `$eq_temp`,
> `$eq_press`, `$prod_low`, `$prod_high`, `$prod_press`. Setting `@tempw=(600)` gives a folder
> called `-T600` that still runs at `$prod_high` — edit the real variables instead.

> **Which cell-DOF triple applies?** The only test is `if ($file =~ /surface/)`. So `surface/`,
> `surface_wet/`, `surface_pcet/` … use `$surface_c*`; `bulk/`, `cluster/`, `solvent/` all use
> `$bulk_c*`. Cluster and solvent therefore cannot use different DOF in one run — run them as
> separate passes.

> **Cell DOF explained:** `1` = allow that direction to change, `0` = fix it.
> - Bulk 3D: use `1,1,1` (NPT) or `0,0,0` (NVT)
> - Surface with vacuum in z: use `1,1,0`
> - Nanowire along z: use `0,0,1` (relaxes c only)
> - Isolated cluster (vacuum in all directions): use `0,0,0` — never relax a vacuum axis

> **DeePMD 訓練慣例(提案資料集):** 單一 `model=uma-s-1p2p1` + `task=oc25`;
> `eq_steps=10000`、`eq_temp=10`、`prod_steps=10000`、`prod_freq=20`
> → 每 job **500 幀**(`prod_steps/prod_freq`;末結構無能量/力,轉檔時丟棄)。
> 每類資料的完整建議參數 (含 EQ/PROD)見 `AGENTS_WORKFLOW.md` Step 3。

### Step 2: Submit All Jobs

```bash
cd ~/UMA_example/scripts
perl submit_allslurm_sh.pl
```

This randomly shuffles and `sbatch` submits every `.sh` file under `UMA_inputs/`. Random order helps avoid I/O bursts from simultaneous model loading.

---

## Monitoring and Resubmission

### Check Job Status

```bash
cd ~/UMA_example/scripts
perl check_UMAjobs.pl
```

This creates `UMAjobs_status/` with:
- `Done.txt` — completed jobs
- `Running.txt` — currently running
- `Queueing.txt` — waiting in queue
- `Dead.txt` — failed or never submitted

### Resubmit Dead Jobs

```bash
perl submit_sh4allDead.pl
```

Reads `UMAjobs_status/Dead.txt` and resubmits each one.

**Workflow:** `check_UMAjobs.pl` → inspect `Dead.txt` → `submit_sh4allDead.pl` → repeat.

---

## Model and Task Reference

### UMA Models

| Model | Cached on this cluster | Use Case |
|---|---|---|
| `uma-s-1p2p1` | yes | **Default** — UMA 1.2 small; the proposal dataset's fixed model |
| `uma-s-1p1` | yes | Previous small release |
| `uma-s-1` | yes | Original small release |
| `uma-m-1p1`, `uma-m-2p0`, `uma-s-2p0` | no | Larger releases; would download on first use (unverified on this cluster) |

> Model names are resolved by `fairchem.core.pretrained_mlip.get_predict_unit(name)`. A name that
> is not in the cache triggers a download **inside the job** — on a compute node without network
> that fails. Check `~/.cache/fairchem/models--facebook--UMA/snapshots/*/checkpoints/` first.

### FairChem Tasks

The `uma-s-1p2p1` checkpoint carries **seven** heads; `FAIRChemCalculator` validates the name
against the checkpoint and prints the valid list if you pass anything else:

| Task | Domain | Example Systems |
|---|---|---|
| `omat` | Inorganic materials | Bulk crystals, alloys, semiconductors |
| `omol` | Molecules | Organic molecules, proteins |
| `oc20` | Catalysis (OC20) | Adsorbates on surfaces |
| `oc22` | Catalysis (OC22) | Oxide surfaces, OER intermediates |
| `oc25` | Catalysis (OC25) | **Solid–liquid interfaces — the proposal's fixed head** |
| `odac` | MOFs | Metal-Organic Frameworks |
| `omc` | Molecular crystals | Organic electronics, pharma crystals |

> `omdyn` appears in older notes but is **not** a FairChem 2.13 task (nothing by that name exists
> in the installed package); passing it fails the calculator's validation.

---


---

## gptfakeQE.py — Core Engine (Detailed Reference)

> Full manual also available at `scripts/mustRead.md`.

### What It Does

`gptfakeQE.py` is the heart of the pipeline. It takes a single LAMMPS `.data` file and:

1. Loads the structure into ASE
2. Initializes the FairChem UMA ML potential
3. Runs a multi-stage relaxation + MD workflow
4. Writes **fake QE input (`.in`)** and **output (`.sout`)** files that your existing Perl analysis scripts (`QEout_analysis.pl`, `QEout2data.pl`, etc.) can parse directly

### Execution Pipeline

```
LAMMPS .data file
       │
       ▼
  ┌─────────────┐
  │  OPT-1       │  Relax cell lengths only (atoms fixed)
  │  (cell only) │  Controlled by cx, cy, cz flags
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  OPT-2       │  Relax atoms + allowed cell lengths
  │  (full)      │  Angles always fixed
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Supercell   │  (optional, do_supercell=1)
  │  (if on)     │  Expand any dim < 12 A, then re-run OPT-2
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Equilibrium │  (optional, eq_steps>0)
  │  MD          │  Silent equilibration, no fake QE output
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Production  │  NPT or NVT at prod conditions
  │  MD          │  Produces time-stamped snapshots + QE output
  └──────┬──────┘
         ▼
  QE-like .in + .sout files
```

### Command-Line Usage (22 positional args)

```bash
python gptfakeQE.py <INPUT.data> \
    <opt1_steps> <opt1_fmax> \
    <opt2_steps> <opt2_fmax> \
    <npt_steps> <do_supercell> \
    <eq_steps> <eq_temp_K> <eq_press_GPa> <eq_timestep_fs> \
    <prod_steps> <prod_low_K> <prod_high_K> <prod_press_GPa> <prod_timestep_fs> <prod_freq> \
    <cx> <cy> <cz> \
    <MODEL_NAME> <TASK_NAME>
```

**No flags, no optional args — exactly 22 arguments.**

### Arguments Explained

| # | Name | Type | Description |
|---|---|---|---|
| 1 | `INPUT.data` | file | LAMMPS data file (`atom_style atomic`, Masses block with `# Element` required) |
| 2 | `opt1_steps` | int >= 0 | OPT-1 steps: all atoms fixed, only cell lengths by cx/cy/cz relax |
| 3 | `opt1_fmax` | float >= 0 | OPT-1 force convergence (eV/A) |
| 4 | `opt2_steps` | int >= 0 | OPT-2 steps: atoms free + allowed cell lengths relax |
| 5 | `opt2_fmax` | float >= 0 | OPT-2 force convergence (eV/A) |
| 6 | `npt_steps` | int >= 0 | **Ignored.** Parsed and stored, never read again — the supercell switch is arg 7 and the MD lengths are args 8/12. Keep the legacy value (≤ 999). |
| 7 | `do_supercell` | 0 or 1 | After OPT-2, expand dims < 12 A → re-run OPT-2 |
| 8 | `eq_steps` | int >= 0 | Equilibrium MD steps. **0 = skip** (go straight to production) |
| 9 | `eq_temp_K` | float | Equilibrium temperature (K) |
| 10 | `eq_press_GPa` | float | Equilibrium pressure (GPa). Ignored in NVT. |
| 11 | `eq_timestep_fs` | float | Equilibrium MD timestep (fs) |
| 12 | `prod_steps` | int >= 0 | Production MD steps. **0 = SCF only** |
| 13 | `prod_low_K` | float | Production starting temperature (K) — heating ramp low |
| 14 | `prod_high_K` | float | Production ending temperature (K) — heating ramp high |
| 15 | `prod_press_GPa` | float | Production pressure (GPa). Ignored in NVT. |
| 16 | `prod_timestep_fs` | float | Production timestep (fs). Fake QE `dt = prod_timestep_fs x 20` |
| 17 | `prod_freq` | int >= 1 | Output frequency. `mod(step, prod_freq)==0` writes QE output |
| 18 | `cx` | 0 or 1 | Allow **a** length to change |
| 19 | `cy` | 0 or 1 | Allow **b** length to change |
| 20 | `cz` | 0 or 1 | Allow **c** length to change |
| 21 | `MODEL_NAME` | string | `uma-s-1p2p1` (production), `uma-s-1p1`, `uma-s-1` — must already be cached (see Model reference) |
| 22 | `TASK_NAME` | string | `oc25` (production), or another UMA-1.2 head: `omat`, `omol`, `oc20`, `oc22`, `odac`, `omc` |
> **Note:** The old single-temperature/pressure interface is replaced by separate eq and prod stages. Set `eq_steps=0` to skip equilibration (equivalent to the old behavior where production starts immediately).

### Cell DOF Flags (cx, cy, cz)

These control which cell dimensions are free during OPT-1, OPT-2, and MD. Angles are **always fixed**.

| Scenario | cx cy cz | Behavior |
|---|---|---|
| 3D NPT (isotropic) | `1 1 1` | All cell lengths relax; MD uses NPT barostat |
| NVT (fixed cell) | `0 0 0` | Cell frozen; MD switches to NVT, pressure ignored |
| 2D slab (vacuum in z) | `1 1 0` | Relax x,y only; z stays fixed |
| Nanowire along z | `0 0 1` | Relax **c (z) only**; a,b fixed |
| Isolated cluster (vacuum in all directions) | `0 0 0` | Fixed cell — never relax a vacuum axis |

### Output Files

For input `MyAlloy-T300-P0.data`:

**In the same directory as input:**

| File | Description |
|---|---|
| `MyAlloy-T300-P0.in` | Fake QE input file |
| `MyAlloy-T300-P0.sout` | Fake QE output (parsed by Perl scripts) |
| `elements.dat` | Element list for downstream tools |
| `_eq_profile.png` | Equilibrium MD profile (T, P, E, density vs step) |

**In `data_files/` subfolder (created fresh each run):**

| File | Description |
|---|---|
| `000.data` | Initial relaxed structure (Iteration=1) |
| `minimized_1.data` | After OPT-1 |
| `minimized_2.data` | After OPT-2 |
| `supercell.data` | Expanded cell (if `do_supercell=1` and expansion needed) |
| `minimized_2_supercell.data` | Re-optimized after supercell expansion |
| `001.data` … `NNN.data` | Production snapshots — one every `prod_freq` steps (`10000/20` → 500 files, `001`…`500`) |

### QE Output Format (Critical for Perl Parsers)

The `.sout` file mimics real Quantum ESPRESSO output:

1. **Iteration=1 block** — energy, forces, stress for initial structure (`000.data`)
2. **Energy blocks** — one `Iteration=1` block for the input structure, then one block per written step **except the last** (`prod_steps // prod_freq` blocks in total)
3. **Final geometry** — `CELL_PARAMETERS` and `ATOMIC_POSITIONS` for the last step, but **no** `! total energy` block

> **Rule:** the first `!` block is the `Iteration=1` block that pairs with the
> `.in` S0 structure; the loop writes a structure at every `mod(step, prod_freq)==0`
> and an energy block for all of them **except** the final step (`step == prod_steps`),
> which real QE never SCFs. Total `!` blocks = `prod_steps // prod_freq`;
> DeePMD convention `10000/20` → **500 frames** per job.

> **External artifacts:** `QEout_plot.png` and `sout_data.csv` in each job dir
> are written by `/opt/qe_perl/QEout_analysis.pl` (invoked at job end) — not by
> `gptfakeQE.py`/`plot_thermo.py`. `thermo_summary.png` and `*_eq_profile.png`
> come from the repo itself.

### Example Commands

All 22 positional arguments, in order. (Normally you never type these — `arrange_data4UMA.pl`
writes them into each job's `.sh` — but this is what a manual run looks like.)

```bash
# SCF only (no MD) — quick engine test
python gptfakeQE.py INPUT.data 5 0.2 5 0.1 0 0 \
    0 10 0.0 1.0 \
    0 10 10 0.0 1.0 20 \
    0 0 0 uma-s-1p2p1 oc25

# Bulk metal — NVT (fixed cell), no eq MD, 10000 prod steps → 500 frames
python gptfakeQE.py INPUT.data 250 0.1 250 0.05 250 0 \
    0 10 0.0 2.0 \
    10000 10 900 0.0 2.0 20 \
    0 0 0 uma-s-1p2p1 oc25

# Bulk metal — NPT, 10000 eq steps then 10000 prod steps (ramp 10 → 900 K)
python gptfakeQE.py INPUT.data 250 0.1 250 0.05 250 0 \
    10000 10 0.0 2.0 \
    10000 10 900 0.0 2.0 20 \
    1 1 1 uma-s-1p2p1 oc25

# 2D slab (vacuum in z) — 1 fs, ramp 10 → 400 K, relax a,b only
python gptfakeQE.py SLAB.data 250 0.1 250 0.05 250 0 \
    10000 10 0.0 1.0 \
    10000 10 400 0.0 1.0 20 \
    1 1 0 uma-s-1p2p1 oc25

# SCF + supercell expansion (no MD)
python gptfakeQE.py SMALL.data 50 0.1 50 0.05 0 1 \
    0 10 0.0 1.0 \
    0 10 10 0.0 1.0 20 \
    1 1 1 uma-s-1p2p1 oc25
```

> The `0` after `250 0.1 250 0.05 250` is `npt_steps` — ignored, kept for CLI compatibility.

### Mode Reference Table

| Goal | prod_steps | cx cy cz | Result |
|---|---|---|---|
| SCF only (no MD) | `0` | any | `calculation=scf` |
| 3D NPT production | `>0` | `1 1 1` | NPT in all directions |
| 2D slab + vacuum in z | `>0` | `1 1 0` | NPT in x,y only |
| NVT (fixed cell) | `>0` | `0 0 0` | NVT, pressure ignored |
| Nanowire along z | `>0` | `0 0 1` | NPT along c (z) only |

### Key Constants

| Constant | Value | Description |
|---|---|---|
| `SUPERCELL_RCUT_A` | 6.0 A | Supercell cutoff: target length = 2 x rcut = 12 A |
| `OPT1_PRESS_TOL_GPA` | 1.0 | Pressure tolerance for OPT-1 |
| `OPT2_PRESS_TOL_GPA` | 0.2 | Pressure tolerance for OPT-2 |
| `OPT1_MAXSTEP` | 0.25 | Max step size for OPT-1 |
| `OPT2_MAXSTEP` | 0.20 | Max step size for OPT-2 |
| `TTIME_FS` | 25.0 fs | Thermostat time constant |
| `PFACTOR_COEFF` | 75.0 | Barostat p-factor coefficient |
| `FIX_ANGLES_NPT` | True | Angles always fixed in NPT |

### Thread Optimization

`gptfakeQE.py` takes its thread budget from `OMP_NUM_THREADS`. The generated `.sh` sets it from Slurm, preferring CPUs-per-task:

```bash
export OMP_PROC_BIND=spread
export OMP_PLACES=cores
if [ -n "$SLURM_CPUS_PER_TASK" ] && [ "$SLURM_CPUS_PER_TASK" -gt 1 ]; then
    export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
else
    export OMP_NUM_THREADS=$SLURM_CPUS_ON_NODE
fi
# MKL_NUM_THREADS / OPENBLAS_NUM_THREADS / NUMEXPR_NUM_THREADS / TORCH_NUM_THREADS follow it
```

Request CPU cores with `#SBATCH --cpus-per-task`; the job uses that many threads.

## Troubleshooting

### "Masses block missing valid '# Element'"

Your `.data` file's `Masses` block lacks element symbols. Fix:

```
Masses

1 26.9815385  # Al    ← must have "# Element"
2 58.933194   # Co
```

### Job shows as "Dead" immediately

- Check `<prefix>.err` in the job folder for Python traceback
- Common causes: missing conda activation, FairChem import error, bad `.data` format

### Very slow performance

The generated `.sh` script sets `OMP_NUM_THREADS=$SLURM_CPUS_ON_NODE`. Make sure you're requesting enough CPUs:

```bash
sinfo -Nh -o '%N|%T|%C|%m'   # check available nodes and CPUs
```

### Job runs on CPU (no GPU used)

The generated `.sh` template exports `CUDA_VISIBLE_DEVICES=-1`, so every job runs on CPU even
though the `fairchem` env carries a CUDA-enabled PyTorch (2.13.0+cu130). `gptfakeQE.py` itself does
not touch that variable; it picks `cuda` only when `torch.cuda.is_available()` is true. To use a
GPU node, remove that line from `arrange_data4UMA.pl`'s `.sh` template and request a `gpu` partition.

---

## Customization Examples

### Run the production ramp at 600 K / 2 GPa

`@tempw` / `@press` only label the folder — they do **not** change the run. Edit the physics:

```perl
my $eq_temp   = 600;   my $eq_press   = 2.0;
my $prod_low  = 600;   my $prod_high  = 900;   my $prod_press = 2.0;
```

(Optionally also `@tempw = (600); @press = (2);` so the folder name matches.)

### Multiple temperature/pressure points

The `.pl` loops over `@tempw` × `@press`, creating one folder per combination:

```perl
my @tempw = (300, 600, 900);
my @press = (0, 1, 2);
```

→ 9 folders per data file, but **all of them run the same MD settings** — only the folder names
differ. To make the 9 points physically different you must change `$eq_temp`/`$prod_low`/
`$prod_high` and re-run the `.pl` once per set (each re-run wipes `UMA_inputs/`).

### Use a larger model

```perl
my $model = "uma-m-1p1";
```

> `uma-m-1p1` / `uma-m-2p0` / `uma-s-2p0` are **not** in this cluster's cache
> (`~/.cache/fairchem/models--facebook--UMA/snapshots/*/checkpoints/`). The first job that asks for
> one will try to download it — on a compute node without network the job dies. Warm the cache
> first, then switch.

### Switch to NPT (isotropic)

```perl
my ($bulk_cx, $bulk_cy, $bulk_cz) = (1, 1, 1);
```

---

## File Summary

| File | Language | Purpose |
|---|---|---|
| `arrange_data4UMA.pl` | Perl | Generate job directories and Slurm scripts |
| `submit_allslurm_sh.pl` | Perl | Batch submit all jobs via `sbatch` |
| `gptfakeQE.py` | Python | FairChem UMA inference + QE-format output |
| `check_UMAjobs.pl` | Perl | Monitor job status |
| `submit_sh4allDead.pl` | Perl | Resubmit failed jobs |
| `fairchem_modified.sh` | Bash | Standalone example Slurm script (for testing) |
