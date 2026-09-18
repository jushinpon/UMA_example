#!/bin/sh
#SBATCH --output=fairchem.log
#SBATCH --error=fairchem.err
#SBATCH --job-name=fairchem_cpu
#SBATCH --nodes=1
##SBATCH --cpus-per-task=1
#SBATCH --partition=All
##SBATCH --ntasks-per-node=12
##SBATCH --exclude=node23
#SBATCH --ntasks=1
#SBATCH --hint=nomultithread

echo "==================== Slurm job info ===================="
echo "Job ID               : $SLURM_JOB_ID"
echo "Job Name             : $SLURM_JOB_NAME"
echo "Partition            : $SLURM_JOB_PARTITION"
echo "Node List            : $SLURM_NODELIST"
echo "Nodes Allocated      : $SLURM_JOB_NUM_NODES"
echo "Tasks (ntasks)       : $SLURM_NTASKS"
echo "CPUs on node         : $SLURM_CPUS_ON_NODE"
echo "CPUs per task        : $SLURM_CPUS_PER_TASK"
echo "Submit directory     : $SLURM_SUBMIT_DIR"
echo "======================================================="

# ============================
# OpenMP configuration
# ============================
export OMP_PROC_BIND=spread
export OMP_PLACES=cores

if [ -n "$SLURM_CPUS_PER_TASK" ] && [ "$SLURM_CPUS_PER_TASK" -gt 1 ]; then
    export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
else
    export OMP_NUM_THREADS=$SLURM_CPUS_ON_NODE
fi

echo "================== OpenMP settings ====================="
echo "OMP_PROC_BIND        : $OMP_PROC_BIND"
echo "OMP_PLACES           : $OMP_PLACES"
echo "OMP_NUM_THREADS      : $OMP_NUM_THREADS"
echo "======================================================="

# ============================
# BLAS / NumPy / PyTorch
# ============================
export MKL_NUM_THREADS=$OMP_NUM_THREADS
export OPENBLAS_NUM_THREADS=$OMP_NUM_THREADS
export NUMEXPR_NUM_THREADS=$OMP_NUM_THREADS

echo "================== BLAS settings ======================="
echo "MKL_NUM_THREADS      : $MKL_NUM_THREADS"
echo "OPENBLAS_NUM_THREADS : $OPENBLAS_NUM_THREADS"
echo "NUMEXPR_NUM_THREADS  : $NUMEXPR_NUM_THREADS"
echo "======================================================="

# ============================
# PyTorch (FairChem backend)
# ============================
export TORCH_NUM_THREADS=$OMP_NUM_THREADS
export TORCH_DISTRIBUTED_DEBUG=OFF

echo "================ PyTorch settings ======================"
echo "TORCH_NUM_THREADS    : $TORCH_NUM_THREADS"
echo "======================================================="



# ============================
# Run FairChem (NO srun)
# ============================



hostname

if [ -f /opt/anaconda3/bin/activate ]; then
    
    source /opt/anaconda3/bin/activate fairchem
    #export LD_LIBRARY_PATH=/opt/deepmd-cpu-v3/lib:/opt/deepmd-cpu-v3/lib/deepmd_lmp:$LD_LIBRARY_PATH
    #export PATH=/opt/deepmd-cpu-v3/bin:$PATH

elif [ -f /opt/miniconda3/bin/activate ]; then
    source /opt/miniconda3/bin/activate fairchem
    #export LD_LIBRARY_PATH=/opt/deepmd-cpu-v3/lib:/opt/deepmd-cpu-v3/lib/deepmd_lmp:$LD_LIBRARY_PATH
    #export PATH=/opt/deepmd-cpu-v3/bin:$PATH
else
    echo "Error: Neither /opt/anaconda3/bin/activate nor /opt/miniconda3/bin/activate found."
    exit 1  # Exit the script if neither exists
fi

echo "================ Software versions ====================="
python - <<EOF
import torch, os
print("Python executable   :", os.sys.executable)
print("PyTorch version     :", torch.__version__)
print("CPU count (torch)   :", torch.get_num_threads())
EOF
echo "======================================================="

#python gptfakeQE.py INPUT.data opt1_steps opt1_fmax opt2_steps opt2_fmax npt_steps do_supercell(0/1)  temp(K) press(GPa) timestep(fs)  cx cy cz model task
#python gptfakeQE.py 20260105_093642_optimized_out-fcc-Al04Co33Cr22Fe15Mo01Nb01Ni25Ta01Ti02W01_out.data 1 0.2 1 0.1 1 1 400.0 1.0 2.0 0 0 0 1 1 1 uma-s-1p1 omat
#see usage in fairchem.py
rm -f *.sout
rm -f *.in
python -u gptfakeQE.py 20260105_093642_optimized_out-fcc-Al04Co33Cr22Fe15Mo01Nb01Ni25Ta01Ti02W01_out.data 5 0.2 5 0.1 20 1 300.0 0.0 1.0 1 1 1 uma-s-1p1 omat

perl /opt/qe_perl/QEout_analysis.pl
perl /opt/qe_perl/QEout2data.pl
