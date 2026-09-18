# gptfakeQE.py — Detailed Manual

> This script generates **fake Quantum ESPRESSO (QE) input/output** from LAMMPS `.data` files using FairChem's UMA ML potential. The fake QE output is designed to be parsed by existing Perl analysis tools (e.g., `QEout_analysis.pl`, `QEout2data.pl`).

---

## Overview

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
  │  Supercell   │  (optional) Expand if any dimension < 12 Å
  │  (if on)     │  Then re-run OPT-2 on expanded cell
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  MD          │  NPT or NVT depending on cx/cy/cz
  │  (NPT/NVT)  │  Produces time-stamped snapshots
  └──────┬──────┘
         ▼
  QE-like .in + .sout files
```

---

## Usage

```bash
python gptfakeQE.py <INPUT.data> \
    <opt1_steps> <opt1_fmax> \
    <opt2_steps> <opt2_fmax> \
    <npt_steps> <do_supercell> \
    <temp_K> <press_GPa> <timestep_fs> \
    <cx> <cy> <cz> \
    <MODEL_NAME> <TASK_NAME>
```

**Exactly 15 arguments** (no flags, no optional args).

### Example

```bash
python gptfakeQE.py Co0Cr0Cu10Fe30Ni30V30_NP_r75A-T300-P0.data \
    250 0.1  250 0.05 \
    250 0 \
    300.0 0.0 1.5 \
    0 0 0 \
    uma-s-1p1 omat
```

---

## Arguments Explained

### (A) Optimization Parameters

| Arg | Name | Description |
|---|---|---|
| 1 | `opt1_steps` | Number of OPT-1 steps (cell-only relaxation) |
| 2 | `opt1_fmax` | Force convergence target for OPT-1 (eV/Å) |
| 3 | `opt2_steps` | Number of OPT-2 steps (atom + cell relaxation) |
| 4 | `opt2_fmax` | Force convergence target for OPT-2 (eV/Å) |

**OPT-1:** All atoms are fixed. Only cell lengths allowed by `cx/cy/cz` are relaxed. This quickly removes stress from the initial structure.

**OPT-2:** Atoms are free to move (with `FixAtoms` constraints if applicable). Cell lengths allowed by `cx/cy/cz` also relax. Angles are always fixed.

### (B) MD Parameters

| Arg | Name | Description |
|---|---|---|
| 5 | `npt_steps` | Number of MD steps. `0` = no MD (SCF only) |
| 8 | `temp_K` | Target temperature in Kelvin |
| 9 | `press_GPa` | Target pressure in GPa (ignored in NVT) |
| 10 | `timestep_fs` | MD timestep in femtoseconds |

When `npt_steps > 0`, the script runs MD using ASE's Melchionna NPT integrator. The QE input file uses `dt = timestep_fs × 20` and `nstep = npt_steps`.

When `npt_steps = 0`, no MD is performed. The script produces a single SCF-like output.

### (C) Supercell Toggle

| Arg | Name | Description |
|---|---|---|
| 6 | `do_supercell` | `0` = off, `1` = on |

When `1`: after OPT-2, checks all cell dimensions. Any dimension shorter than **12 Å** is repeated until it's ≥ 12 Å. OPT-2 is then re-run on the expanded supercell.

### (D) Cell DOF Flags

| Arg | Name | Description |
|---|---|---|
| 11 | `cx` | `1` = allow **a** length to change, `0` = fix |
| 12 | `cy` | `1` = allow **b** length to change, `0` = fix |
| 13 | `cz` | `1` = allow **c** length to change, `0` = fix |

These control which cell dimensions are free during OPT-1, OPT-2, and MD.

**Special behavior:** If `cx = cy = cz = 0` and `npt_steps > 0`, the MD switches from **NPT to NVT** (fixed cell, barostat disabled). `press_GPa` is ignored.

### (E) Model and Task

| Arg | Name | Description |
|---|---|---|
| 14 | `MODEL_NAME` | `uma-s-1p1` (fast) or `uma-m-1p1` (accurate) |
| 15 | `TASK_NAME` | `omat`, `oc20`, `omol`, `odac`, or `omc` |

---

## Output Files

For input file `/path/to/MyAlloy-T300-P0.data`:

### In the same directory as the input:

| File | Description |
|---|---|
| `MyAlloy-T300-P0.in` | Fake QE input file |
| `MyAlloy-T300-P0.sout` | Fake QE output (parsed by Perl scripts) |
| `elements.dat` | Element list for downstream tools |

### In a local `data_files/` subfolder:

| File | Description |
|---|---|
| `000.data` | Initial relaxed structure (Iteration=1) |
| `minimized_1.data` | After OPT-1 |
| `minimized_2.data` | After OPT-2 |
| `001.data` ... `NNN.data` | MD snapshots (if MD runs) |
| `supercell.data` | Expanded cell (if supercell was applied) |
| `minimized_2_supercell.data` | Re-optimized after supercell expansion |

---

## QE Output Format (Important for Perl Parser)

The `.sout` file mimics real QE output:

1. **Iteration=1 block** — prints energy, forces, stress for the initial structure (`000.data`)
2. **Energy blocks** — exactly `nstep` blocks with `! total energy` markers (steps 0 to nstep-1)
3. **Final geometry** — `CELL_PARAMETERS` and `ATOMIC_POSITIONS` for the last step, but **no** `! total energy` block

> **Rule:** `nstep=250` → exactly 250 `! total energy` lines → `250.data` exists with geometry only.

---

## Recommended Settings

### Quick Test (SCF only)

```bash
python gptfakeQE.py INPUT.data 5 0.2 5 0.1 0 0 300 0.0 1.0 1 1 1 uma-s-1p1 omat
```

### Bulk Metal — NVT (fixed cell)

```bash
python gptfakeQE.py INPUT.data 250 0.1 250 0.05 250 0 300.0 0.0 1.5 0 0 0 uma-s-1p1 omat
```

### Bulk Metal — NPT (isotropic)

```bash
python gptfakeQE.py INPUT.data 250 0.1 250 0.05 250 1 300.0 0.0 1.5 1 1 1 uma-s-1p1 omat
```

### 2D Surface (vacuum in z)

```bash
python gptfakeQE.py SLAB.data 250 0.1 250 0.05 250 1 300.0 0.0 1.5 1 1 0 uma-s-1p1 omat
```

### SCF + Supercell Expansion

```bash
python gptfakeQE.py SMALL.data 50 0.1 50 0.05 0 1 300 0.0 1.0 1 1 1 uma-s-1p1 omat
```

---

## Mode Reference Table

| Goal | npt_steps | cx cy cz | Result |
|---|---|---|---|
| SCF only (no MD) | `0` | any | `calculation=scf` |
| 3D NPT | `>0` | `1 1 1` | NPT in all directions |
| 2D slab + vacuum in z | `>0` | `1 1 0` | NPT in x,y only |
| NVT (fixed cell) | `>0` | `0 0 0` | NVT, pressure ignored |
| Nanowire along z | `>0` | `0 0 1` | Relax x,y only |

---

## Requirements

### Input File

- LAMMPS data file with `atom_style atomic`
- `Masses` block **must** include `# Element` comments:

```
Masses

1 26.9815385  # Al
2 58.933194   # Co
```

### Software (auto-loaded by `.sh` scripts)

- Python 3 with: `ase`, `numpy`, `torch`, `fairchem-core`
- Conda environment: `fairchem` (on cluster186: `/opt/anaconda3/envs/fairchem`)

---

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `Masses block missing valid '# Element'` | `.data` file lacks element symbols in Masses | Add `# Element` after each mass value |
| `fairchem-core not installed` | Wrong conda env | Ensure `.sh` script activates `fairchem` env |
| `CUDA out of memory` | GPU memory exhausted | Script uses CPU by default (`CUDA_VISIBLE_DEVICES=-1`). If you enabled GPU, reduce batch or switch to CPU |
| Very slow | Too few CPU threads | Check `OMP_NUM_THREADS` is set in the `.sh` script; request more CPUs via `--ntasks` |
| `sout` has wrong number of energy blocks | MD crashed early | Check `.err` file for traceback; increase `opt_steps` or `fmax` for better initial relaxation |
