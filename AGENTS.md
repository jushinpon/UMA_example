# AGENTS.md — UMA_example
> **⚠️ 執行前必讀：** 請先閱讀 `AGENTS_WORKFLOW.md`，依序完成確認步驟後才能提交 job。

## Project Overview

FairChem UMA (Universal Materials Approach) ML potential pipeline.
Replaces expensive DFT calculations with machine-learning inference for relaxation + MD.

**Cluster:** `cluster186-jsp` · **Conda env:** `fairchem` · **Partition:** `All`

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
| `MODEL_NAME` | e.g. uma-s-1p1, uma-s-2p0, uma-m-1p1 |
| `TASK_NAME` | e.g. omat, omdyn |

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

# Arrange data + generate Slurm scripts
cd ~/UMA_example/scripts
perl arrange_data4UMA.pl

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

## File Roles

| File | Role |
|------|------|
| gptfakeQE.py | Core: FairChem UMA inference + MD pipeline |
| arrange_data4UMA.pl | Generate job folders + Slurm scripts from categorized data |
| submit_allslurm_sh.pl | Submit all generated .sh scripts via sbatch |
| check_UMAjobs.pl | Monitor job status (Done/Running/Dead) |
| submit_sh4allDead.pl | Resubmit failed jobs |
| mustRead.md | Detailed gptfakeQE.py manual |
