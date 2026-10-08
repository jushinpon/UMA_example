# UMA Example — FairChem ML Potential Pipeline

> **Cluster:** `cluster186-jsp` · **Conda env:** `fairchem` · **FairChem:** 2.13.0 · **PyTorch:** 2.8.0 (CPU)

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

---

## Directory Structure

```
UMA_example/
├── README.md                          ← You are here
├── categorized_data4UMA/              ← PUT YOUR .data FILES HERE
│   ├── FCC/                           ← Example: FCC structures
│   │   ├── Al2Ni3_FCC.data
│   │   └── ...
│   ├── BCC/                           ← Example: BCC structures
│   ├── HCP/                           ← Example: HCP structures
│   ├── NP/                            ← Example: Nanoparticles
│   │   └── Co0Cr0Cu10Fe30Ni30V30_NP_r75A.data
│   └── ...                            ← Add your own categories
├── scripts/
│   ├── arrange_data4UMA.pl            ← Script 1: generate job folders + .sh files
│   ├── submit_allslurm_sh.pl          ← Script 2: submit all jobs via sbatch
│   ├── gptfakeQE.py                   ← Core: FairChem UMA inference engine
│   ├── check_UMAjobs.pl               ← Check job status (Done/Running/Dead)
│   ├── submit_sh4allDead.pl           ← Resubmit dead jobs
│   ├── README.md                      ← Scripts reference
│   └── mustRead.md                    ← gptfakeQE.py detailed manual
└── UMA_inputs/                        ← GENERATED (after Step 1)
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

**Example file:** see `categorized_data4UMA/NP/Co0Cr0Cu10Fe30Ni30V30_NP_r75A.data`.

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

**Before running**, edit the top section of `arrange_data4UMA.pl` to set your parameters:

| Parameter | Default | Description |
|---|---|---|
| `@tempw` | `(300)` | Temperature(s) in Kelvin |
| `@press` | `(0)` | Pressure(s) in GPa |
| `$model` | `"uma-s-1p1"` | UMA model size |
| `$task` | `"omat"` | FairChem task |
| `$opt1_steps` | `250` | Optimization stage 1 steps |
| `$opt1_fmax` | `0.1` | OPT-1 force convergence (eV/A) |
| `$opt2_steps` | `250` | Optimization stage 2 steps |
| `$opt2_fmax` | `0.05` | OPT-2 force convergence (eV/A) |
| `$npt_steps` | `250` | Production MD steps (0 = SCF only) |
| `$do_supercell` | `0` | Auto-build supercell if cell < 12 A |
| `$eq_steps` | `500` | Equilibrium MD steps (0 = skip eq) |
| `$eq_temp` | `300` | Equilibrium temperature (K) |
| `$eq_press` | `0` | Equilibrium pressure (GPa) |
| `$eq_timestep` | `1.5` | Equilibrium MD timestep (fs) |
| `$prod_steps` | `250` | Production MD steps (0 = SCF only) |
| `$prod_low` | `300` | Production starting temperature (K) — heating ramp low |
| `$prod_high` | `600` | Production ending temperature (K) — heating ramp high |
| `$prod_press` | `0` | Production pressure (GPa) |
| `$prod_timestep` | `1.5` | Production MD timestep (fs) |
| `$prod_freq` | `5` | Output frequency: mod(step, freq)==0 writes QE output |
| `($bulk_cx,$bulk_cy,$bulk_cz)` | `(0,0,0)` | Cell DOF for bulk (NVT when all 0) |
| `($surface_cx,$surface_cy,$surface_cz)` | `(0,0,0)` | Cell DOF for surface systems |

> **Cell DOF explained:** `1` = allow that direction to change, `0` = fix it.
> - Bulk 3D: use `1,1,1` (NPT) or `0,0,0` (NVT)
> - Surface with vacuum in z: use `1,1,0`
> - Nanowire along z: use `0,0,1`

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

| Model | Active Params | Speed | Use Case |
|---|---|---|---|
| `uma-s-1p1` | ~6.6M | Fastest | High-throughput, long MD (default) |
| `uma-m-1p1` | ~50M | Slower | High-precision relaxation |
| `uma-l` | Coming Soon | — | Not yet available |

### FairChem Tasks

| Task | Domain | Example Systems |
|---|---|---|
| `omat` | Inorganic Materials | Bulk crystals, alloys, semiconductors |
| `oc20` | Catalysis | Adsorbates on surfaces |
| `omol` | Molecules | Organic molecules, proteins |
| `odac` | MOFs | Metal-Organic Frameworks |
| `omc` | Molecular Crystals | Organic electronics, pharma crystals |

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
| 6 | `npt_steps` | int >= 0 | 0/1. Kept for backward compat; 1 = enable supercell |
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
| 21 | `MODEL_NAME` | string | `uma-s-1p1` (fast) or `uma-m-1p1` (accurate) |
| 22 | `TASK_NAME` | string | `omat`, `oc20`, `omol`, `odac`, or `omc` |
> **Note:** The old single-temperature/pressure interface is replaced by separate eq and prod stages. Set `eq_steps=0` to skip equilibration (equivalent to the old behavior where production starts immediately).

### Cell DOF Flags (cx, cy, cz)

These control which cell dimensions are free during OPT-1, OPT-2, and MD. Angles are **always fixed**.

| Scenario | cx cy cz | Behavior |
|---|---|---|
| 3D NPT (isotropic) | `1 1 1` | All cell lengths relax; MD uses NPT barostat |
| NVT (fixed cell) | `0 0 0` | Cell frozen; MD switches to NVT, pressure ignored |
| 2D slab (vacuum in z) | `1 1 0` | Relax x,y only; z stays fixed |
| Nanowire along z | `0 0 1` | Relax x,y only |

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
| `001.data` ... `NNN.data` | Production MD snapshots (one per step) |

### QE Output Format (Critical for Perl Parsers)

The `.sout` file mimics real Quantum ESPRESSO output:

1. **Iteration=1 block** — energy, forces, stress for initial structure (`000.data`)
2. **Energy blocks** — prod_steps/prod_freq blocks with "! total energy" markers (at steps where mod(step, prod_freq)==0)
3. **Final geometry** — `CELL_PARAMETERS` and `ATOMIC_POSITIONS` for the last step, but **no** `! total energy` block

> **Rule:** `nstep = prod_steps // prod_freq` → number of QE output blocks in `.sout`.

### Example Commands

```bash
# SCF only (no MD) — quick test
python gptfakeQE.py INPUT.data 5 0.2 5 0.1 0 0 \
    0 300 0.0 1.0 \
    300 0.0 1.0 1 1 1 uma-s-1p1 omat

# Bulk metal — NVT (fixed cell), skip eq MD
python gptfakeQE.py INPUT.data 250 0.1 250 0.05 250 0 \
    0 300 0.0 1.5 \
    300 0.0 1.5 0 0 0 uma-s-1p1 omat

# Bulk metal — NPT (isotropic), 500 eq steps then 250 prod steps
python gptfakeQE.py INPUT.data 250 0.1 250 0.05 250 1 \
    500 600 2.0 1.5 \
    300 0.0 1.5 1 1 1 uma-s-1p1 omat

# 2D surface (vacuum in z)
python gptfakeQE.py SLAB.data 250 0.1 250 0.05 250 1 \
    500 300 0.0 1.5 \
    300 0.0 1.5 1 1 0 uma-s-1p1 omat

# SCF + supercell expansion
python gptfakeQE.py SMALL.data 50 0.1 50 0.05 0 1 \
    0 300 0.0 1.0 \
    300 0.0 1.0 1 1 1 uma-s-1p1 omat
```

### Mode Reference Table

| Goal | prod_steps | cx cy cz | Result |
|---|---|---|---|
| SCF only (no MD) | `0` | any | `calculation=scf` |
| 3D NPT production | `>0` | `1 1 1` | NPT in all directions |
| 2D slab + vacuum in z | `>0` | `1 1 0` | NPT in x,y only |
| NVT (fixed cell) | `>0` | `0 0 0` | NVT, pressure ignored |
| Nanowire along z | `>0` | `0 0 1` | Relax x,y only |

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

`gptfakeQE.py` auto-configures PyTorch threads from `SLURM_CPUS_PER_TASK` or `OMP_NUM_THREADS`. The generated `.sh` scripts set:

```bash
export OMP_NUM_THREADS=$SLURM_CPUS_ON_NODE
```

Request enough CPUs via `--ntasks` in the Slurm script for best performance.
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

### CUDA not available

`gptfakeQE.py` sets `CUDA_VISIBLE_DEVICES=-1` (CPU-only) by default. For GPU acceleration, edit the generated `.sh` files or modify `arrange_data4UMA.pl`.

---

## Customization Examples

### Run at 600 K with 2 GPa pressure

In `arrange_data4UMA.pl`, change:

```perl
my @tempw = (600);
my @press = (2);
```

### Multiple temperature/pressure points

```perl
my @tempw = (300, 600, 900);
my @press = (0, 1, 2);
```

This creates 9 combinations (3×3) for each data file.

### Use medium model for higher accuracy

```perl
my $model = "uma-m-1p1";
```

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
