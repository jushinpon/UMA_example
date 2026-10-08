#!/bin/sh
#SBATCH --output=1p2_test.out
#SBATCH --error=1p2_test.err
#SBATCH --job-name=1p2_test
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --partition=All
#SBATCH --hint=nomultithread

echo "==================== Slurm job info ===================="
echo "Job ID               : $SLURM_JOB_ID"
echo "Job Name             : $SLURM_JOB_NAME"
echo "Node List            : $SLURM_NODELIST"
echo "CPUs on node         : $SLURM_CPUS_ON_NODE"
echo "Submit directory     : $SLURM_SUBMIT_DIR"
echo "======================================================="

export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
export MKL_NUM_THREADS=$OMP_NUM_THREADS
export OPENBLAS_NUM_THREADS=$OMP_NUM_THREADS

hostname

if [ -f /opt/anaconda3/bin/activate ]; then
    source /opt/anaconda3/bin/activate fairchem
elif [ -f /opt/miniconda3/bin/activate ]; then
    source /opt/miniconda3/bin/activate fairchem
else
    echo "Error: conda activate not found."
    exit 1
fi

# Enable gcc-toolset-13 for C++20 support (torch.compile)
if [ -f /opt/rh/gcc-toolset-13/enable ]; then
    source /opt/rh/gcc-toolset-13/enable
    echo "gcc-toolset-13 ENABLED"
fi
export CXX=$(which g++)

echo "Python    : $(which python)"
echo "g++       : $(g++ --version | head -1)"
echo "C++20     : $(echo int main{} | g++ -std=c++20 -x c++ - -o /dev/null 2>&1 && echo YES || echo NO)"
echo "fairchem  : $(pip show fairchem-core 2>/dev/null | grep Version)"
echo "PyTorch   : $(python -c \"import torch; print(torch.__version__)\")"
echo "torch.compile : $(python -c \"import torch; print(hasattr(torch, \\\"compile\\\"))\")"
echo "======================================================="

cd ~/UMA_example/scripts
python -u 1p2_model_test.py

echo "======================================================="
echo "Job finished at $(date)"
echo "======================================================="
