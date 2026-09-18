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
| `$opt1_fmax` | `0.1` | OPT-1 force convergence (eV/Å) |
| `$opt2_steps` | `250` | Optimization stage 2 steps |
| `$opt2_fmax` | `0.05` | OPT-2 force convergence (eV/Å) |
| `$npt_steps` | `250` | MD steps (0 = SCF only) |
| `$do_supercell` | `0` | Auto-build supercell if cell < 12 Å |
| `$timestep` | `1.5` | MD timestep in fs |
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
