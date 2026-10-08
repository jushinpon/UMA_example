#!/bin/sh
#SBATCH --output=stage_test.out
#SBATCH --error=stage_test.err
#SBATCH --job-name=stage_test
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --partition=All
#SBATCH --hint=nomultithread

export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
export MKL_NUM_THREADS=$OMP_NUM_THREADS
export OPENBLAS_NUM_THREADS=$OMP_NUM_THREADS

if [ -f /opt/anaconda3/bin/activate ]; then
    source /opt/anaconda3/bin/activate fairchem
elif [ -f /opt/miniconda3/bin/activate ]; then
    source /opt/miniconda3/bin/activate fairchem
fi

# gcc-toolset-13: put g++ BEFORE mpicxx in PATH
if [ -f /opt/rh/gcc-toolset-13/enable ]; then
    source /opt/rh/gcc-toolset-13/enable
fi
export CXX=$(which g++)
export CC=$(which gcc)

# Remove stale stage files from previous run
rm -f stage_*.txt thermo_summary.png

hostname
echo "CXX=$CXX  g++ version: $(g++ --version | head -1)"

# Test with the NP data file, small steps
DATA=~/UMA_example/categorized_data4UMA/NP/Co0Cr0Cu10Fe30Ni30V30_NP_r75A.data
BASENAME=$(basename "$DATA")
ln -sf "$DATA" .

python -u ~/UMA_example/scripts/gptfakeQE.py \
    "$BASENAME" \
    3 0.2 3 0.1 5 1 \
    10 300.0 0.0 1.5 \
    20 300.0 600.0 0.0 1.5 5 \
    0 0 0 uma-s-1p2p1 omat

echo ""
echo "=== Generated files ==="
ls -la stage_*.txt thermo_summary.png 2>/dev/null
echo ""
for f in stage_*.txt; do echo "=== $f ==="; cat "$f" 2>/dev/null; echo ""; done
