# Scripts Reference

> This folder contains the complete pipeline for running UMA (FairChem) calculations.
> See the [main README](../README.md) for overview and quick start.

---

## Scripts at a Glance

| Script | What It Does | When to Run |
|---|---|---|
| `arrange_data4UMA.pl` | Scan data files → create job folders + Slurm `.sh` | **Step 1** (always first) |
| `submit_allslurm_sh.pl` | `sbatch` all generated `.sh` files | **Step 2** (after Step 1) |
| `check_UMAjobs.pl` | Check Done / Running / Dead status | Anytime |
| `submit_sh4allDead.pl` | Resubmit jobs listed in `Dead.txt` | After `check_UMAjobs.pl` |
| `gptfakeQE.py` | Core engine — called by the `.sh` scripts | **Do not run directly** |
| `fairchem_modified.sh` | Standalone example for manual testing | Debugging only |

---

## arrange_data4UMA.pl — Job Arranger

### What It Does

1. Finds all `*.data` files under `~/UMA_example/categorized_data4UMA/`
2. For each file, creates a job folder: `~/UMA_example/UMA_inputs/<category>-UMA/<name>-T<temp>-P<press>/`
3. Symlinks the `.data` file into the job folder
4. Generates a Slurm `.sh` script configured with your parameters

### How to Run

```bash
cd ~/UMA_example/scripts
perl arrange_data4UMA.pl
```

### What to Edit (Top of File)

Open `arrange_data4UMA.pl` in a text editor. The configurable section is at the top (~line 15–45):

```perl
## ===== EDIT THESE PARAMETERS =====

my @tempw = (300);          # Temperature(s) in K
my @press = (0);            # Pressure(s) in GPa

my $model = "uma-s-1p1";    # UMA model: uma-s-1p1 or uma-m-1p1
my $task  = "omat";         # Task: omat, oc20, omol, odac, omc

my $opt1_steps = 250;       # OPT-1 steps (cell-only relaxation)
my $opt1_fmax  = 0.1;       # OPT-1 force threshold (eV/Å)
my $opt2_steps = 250;       # OPT-2 steps (atom + cell relaxation)
my $opt2_fmax  = 0.05;      # OPT-2 force threshold (eV/Å)
my $npt_steps  = 250;       # MD steps (0 = SCF only, no MD)
my $do_supercell = 0;       # Auto supercell if cell < 12 Å (0/1)
my $timestep = 1.5;         # MD timestep (fs) — 1.5 for covalent, 2.0 for metals

# Cell degrees of freedom: 1 = relax, 0 = fix
my ($bulk_cx, $bulk_cy, $bulk_cz) = (0, 0, 0);       # bulk: 0,0,0 = NVT; 1,1,1 = NPT
my ($surface_cx, $surface_cy, $surface_cz) = (0, 0, 0); # surface

## ===== END EDITABLE SECTION =====
```

### Key Parameters Explained

| Parameter | What It Controls |
|---|---|
| `@tempw` | Simulation temperature. Multiple values create multiple jobs per structure. |
| `@press` | Target pressure in GPa. Used by NPT and OPT. Ignored in NVT. |
| `cx/cy/cz` | Which cell dimensions are free. All zeros → NVT (fixed cell). |
| `npt_steps` | MD length. Set to `0` for single-point SCF (no MD). |
| `do_supercell` | If `1`, expands any cell dimension < 12 Å before OPT-2. |

---

## submit_allslurm_sh.pl — Job Submitter

### What It Does

Finds all `.sh` files under `~/UMA_example/UMA_inputs/`, shuffles them randomly, and runs `sbatch` on each.

### How to Run

```bash
cd ~/UMA_example/scripts
perl submit_allslurm_sh.pl
```

### Why Random Order?

Randomizing submission order prevents many jobs from simultaneously loading the UMA model checkpoint, which can cause I/O bottlenecks.

### What It Does NOT Do

- Does not check if a job is already running
- Does not limit concurrent submissions (Slurm handles this via queue)
- Does not modify any `.sh` files

---

## check_UMAjobs.pl — Status Checker

### What It Does

Scans all `.data` files and checks whether each has a completed `.sout` with `JOB DONE`, is currently running/queuing in Slurm, or has failed.

### How to Run

```bash
cd ~/UMA_example/scripts
perl check_UMAjobs.pl
```

### Output

Creates `UMAjobs_status/` directory:

| File | Contents |
|---|---|
| `Done.txt` | Successfully completed jobs |
| `Running.txt` | Currently running (with Slurm job ID) |
| `Queueing.txt` | Waiting in Slurm queue |
| `Dead.txt` | Failed — not running, not queued, no `JOB DONE` |

**Note:** You must edit the `$source_folder` variable inside the script to point to your data directory. Check the comments at the top of the file.

---

## submit_sh4allDead.pl — Resubmit Failed Jobs

### What It Does

Reads `UMAjobs_status/Dead.txt`, extracts file paths, and runs `sbatch` on the corresponding `.sh` files.

### How to Run

```bash
cd ~/UMA_example/scripts
perl submit_sh4allDead.pl
```

### Prerequisite

Must run `check_UMAjobs.pl` first to generate `UMAjobs_status/Dead.txt`.

---

## gptfakeQE.py — Core Engine

This is the Python script that actually runs UMA inference. **You don't need to run it directly** — it's called automatically by the generated `.sh` scripts.

For detailed documentation, see [mustRead.md](mustRead.md).

---

## Typical Workflow

```
1. Place .data files in categorized_data4UMA/<category>/
         │
         ▼
2. perl arrange_data4UMA.pl
   → Creates UMA_inputs/ with job folders and .sh scripts
         │
         ▼
3. perl submit_allslurm_sh.pl
   → Submits all jobs to Slurm
         │
         ▼
4. perl check_UMAjobs.pl
   → Check progress
         │
         ▼
5. perl submit_sh4allDead.pl   (if needed)
   → Resubmit any failed jobs
         │
         ▼
6. Repeat steps 4-5 until all jobs are Done
```

---

## Gotchas

- **Re-running `arrange_data4UMA.pl`** deletes and recreates `UMA_inputs/`. Don't run it while jobs are active unless you want to regenerate everything.
- **`check_UMAjobs.pl` hardcodes `$source_folder`**. Update it to match your actual data location before running.
- **Each `.sh` script activates `fairchem` conda env** automatically. No manual activation needed.
- **`srun` is not supported** on this cluster. All scripts use `sbatch` + `mpirun`.
