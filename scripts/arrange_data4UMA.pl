=b
You must place all your data files in categorized folders, e.g., FCC, BCC, HCP, other, surface (you need to name surface if you have data files with surface) etc. 
Then place all those categorized folders in a main folder "categorized_data4UMA".
=cut

use warnings;
use strict;
use Cwd;
use FindBin;
use File::Spec;

my $currentPath = getcwd();

# Resolve the repo layout from this script's own location, so the pipeline works
# no matter where the repository is cloned (~/UMA_example, ~/projects/fork, ...).
# Run it from anywhere:  perl /path/to/repo/scripts/arrange_data4UMA.pl
my $repo_root = Cwd::abs_path(File::Spec->catdir($FindBin::Bin, ".."));
die "Cannot resolve repo root from $FindBin::Bin!" unless defined $repo_root && -d $repo_root;

my $data_main_folder = "$repo_root/categorized_data4UMA";#folder where you place all your .data files (rel. to repo root)
my $out_folder = "$repo_root/UMA_inputs";#folder having all subfolders (the same prefixes as data file) with the job scripts

if (@ARGV && $ARGV[0] eq "--check-paths") {
    print "repo root          : $repo_root\n";
    print "data_main_folder   : $data_main_folder\n";
    print "out_folder         : $out_folder\n";
    exit 0;
}
`rm -rf $out_folder`;
`mkdir $out_folder`;
## set Temperature and press 
my @tempw = (300);
my @press = (0);

#####YOU NEED TO SET THE FOLLOWING PARAMETERS FOR YOUROWN CASES#####
my $model = "uma-s-1p1"; #uma-s-1p1 uma-s-2p0 uma-m-1p1 uma-m-2p0
my $task = "omat";  #omat omdyn

# resolve gptfakeQE.py next to this script (not from the current directory)
my $python_path = Cwd::abs_path(File::Spec->catfile($FindBin::Bin, "gptfakeQE.py"));
die "No gptfakeQE.py found at $FindBin::Bin!" unless -f $python_path;

my $opt1_steps = 250;
my $opt1_fmax = 0.1;
my $opt2_steps = 250;
my $opt2_fmax = 0.05;
my $npt_steps = 250;#not larger than 999
my $do_supercell = 0; # 0 / 1

## Equilibrium MD (silent, no QE output; set eq_steps=0 to skip)
my $eq_steps = 500;     # 0 = skip equilibrium MD
my $eq_temp = 300;      # K
my $eq_press = 0;       # GPa
my $eq_timestep = 1.5;  # fs

## Production MD (with QE output, heating ramp)
my $prod_steps = 250;     # production MD steps (0 = SCF only)
my $prod_low = 300;       # K — heating ramp start
my $prod_high = 600;      # K — heating ramp end
my $prod_press = 0;       # GPa
my $prod_timestep = 1.5; # fs, for bulk UMA simulations without covalent bonds, 2.0 fs is recommended, For simulations with molecules or covalent bonds, 1.5 fs is recommended.
my $prod_freq = 5;       # output frequency: mod(step, prod_freq)==0 writes QE output

my ($bulk_cx, $bulk_cy, $bulk_cz) = (0, 0, 0);
 
#You must assign proper surface_cx, surface_cy, surface_cz for surface systems, 0 for not change lengths along that direction.
#For bulk systems, you can set them to 1,1,1
# 1,1,0 for surface with normal to z direction
# 0, 0, 1 for nanowire with axis along z direction

#current settings for surface systems
my $surface_cx = 0;
my $surface_cy = 0;
my $surface_cz = 0;

#all data files
my @all_data_files = `find $data_main_folder -type f -name "*.data"`;#all QE template files
map { s/^\s+|\s+$//g; } @all_data_files;

#all folders with original data files
`rm -rf $data_main_folder/*-UMA`;#remove old UMA folders
my @ori_folders = `find $data_main_folder -maxdepth 1 -mindepth 1  -type d `;#all QE template files
map { s/^\s+|\s+$//g; } @ori_folders;

for my $of (@ori_folders){
    print "Original folder with data files: $of\n";
    my $of_base = `basename $of`;
    chomp $of_base;
    my $temp = "$out_folder/$of_base-UMA";
    `rm -rf $temp`;
    `mkdir $temp`;
}

###########You don't need to change anything below##############

#use for join optionmy
 my @para_keys = (
    'python_path',
    'INPUT_data',
    'opt1_steps',
    'opt1_fmax',
    'opt2_steps',
    'opt2_fmax',
    'npt_steps',
    'do_supercell',
    'eq_steps',
    'eq_temp',
    'eq_press',
    'eq_timestep',
    'prod_steps',
    'prod_low',
    'prod_high',
    'prod_press',
    'prod_timestep',
    'prod_freq',
    'cx',
    'cy',
    'cz',
    'model',
    'task',
);

my $counter = 0;
for my $f (@all_data_files){
    $counter++;
    print "Processing data file No. $counter: $f\n";
    $f =~ m{^(.+)/([^/]+)/([^/]+)\.data$}
    or die "Path format not matched";

    my ($parent_path, $folder, $prefix) = ($1, $2, $3);

    #print "parent_path = $parent_path\n";
    #print "folder      = $folder\n";
    #print "prefix      = $prefix\n";

    # the above settings have been done. 
    for my $t (@tempw){
        for my $p (@press){

            my $temp = $t;
            my $press = $p;
            my $foldname = "$prefix-T$t-P$p";
            #put data file and sh files in the new folder
            `mkdir -p $out_folder/$folder-UMA/$foldname`;
            `ln -sf $f $out_folder/$folder-UMA/$foldname/$foldname.data`;

            #`cp $f $parent_path/UMA_$folder/$foldname/$foldname.data`;

            #adjust cx, cy, cz for surface systems
            my ($cx, $cy, $cz);
            if($f =~ /surface/){
                $cx = $surface_cx;
                $cy = $surface_cy;
                $cz = $surface_cz;
            }else{
                $cx = $bulk_cx;
                $cy = $bulk_cy;
                $cz = $bulk_cz;
            }

            my $INPUT_data = "$out_folder/$folder-UMA/$foldname/$foldname.data";

            #INPUT.data opt1_steps opt1_fmax opt2_steps opt2_fmax npt_steps do_supercell  eq_steps eq_temp eq_press eq_timestep  prod_steps prod_low prod_high prod_press prod_timestep prod_freq  cx cy cz model task
            my %para = (
                python_path => "python -u $python_path",
                INPUT_data   => $INPUT_data,
                opt1_steps   => $opt1_steps,
                opt1_fmax    => $opt1_fmax,
                opt2_steps   => $opt2_steps,
                opt2_fmax    => $opt2_fmax,
                npt_steps    => $npt_steps,
                do_supercell => $do_supercell,   # 0 / 1
                eq_steps     => $eq_steps,       # 0 = skip eq MD
                eq_temp      => $eq_temp,        # K
                eq_press     => $eq_press,       # GPa
                eq_timestep  => $eq_timestep,    # fs
                prod_steps    => $prod_steps,    # production MD steps
                prod_low     => $prod_low,       # K — heating start
                prod_high    => $prod_high,      # K — heating end
                prod_press   => $prod_press,      # GPa
                prod_timestep=> $prod_timestep,   # fs
                prod_freq    => $prod_freq,       # output frequency
                cx           => $cx,
                cy           => $cy,
                cz           => $cz,
                model        => $model,
                task         => $task,
            );

            my $str = join " ", @para{@para_keys};

my $here_doc =<<"END_MESSAGE";
#!/bin/sh
#SBATCH --output=$prefix.log
#SBATCH --error=$prefix.err
#SBATCH --job-name=$prefix-UMA
#SBATCH --nodes=1
##SBATCH --cpus-per-task=1
#SBATCH --partition=All
##SBATCH --exclude=node23
#SBATCH --ntasks=1
#SBATCH --hint=nomultithread
##SBATCH --reservation=script_test

start_time=\$(date +%s)

hostname
echo "==================== Slurm job info ===================="
echo "Job ID               : \$SLURM_JOB_ID"
echo "Job Name             : \$SLURM_JOB_NAME"
echo "Partition            : \$SLURM_JOB_PARTITION"
echo "Node List            : \$SLURM_NODELIST"
echo "Nodes Allocated      : \$SLURM_JOB_NUM_NODES"
echo "Tasks (ntasks)       : \$SLURM_NTASKS"
echo "CPUs on node         : \$SLURM_CPUS_ON_NODE"
echo "CPUs per task        : \$SLURM_CPUS_PER_TASK"
echo "Submit directory     : \$SLURM_SUBMIT_DIR"
echo "======================================================="

# ============================
# OpenMP configuration
# ============================
export OMP_PROC_BIND=spread
export OMP_PLACES=cores

if [ -n "\$SLURM_CPUS_PER_TASK" ] && [ "\$SLURM_CPUS_PER_TASK" -gt 1 ]; then
    export OMP_NUM_THREADS=\$SLURM_CPUS_PER_TASK
else
    export OMP_NUM_THREADS=\$SLURM_CPUS_ON_NODE
fi

echo "================== OpenMP settings ====================="
echo "OMP_PROC_BIND        : \$OMP_PROC_BIND"
echo "OMP_PLACES           : \$OMP_PLACES"
echo "OMP_NUM_THREADS      : \$OMP_NUM_THREADS"
echo "======================================================="

# ============================
# BLAS / NumPy / PyTorch
# ============================
export MKL_NUM_THREADS=\$OMP_NUM_THREADS
export OPENBLAS_NUM_THREADS=\$OMP_NUM_THREADS
export NUMEXPR_NUM_THREADS=\$OMP_NUM_THREADS

echo "================== BLAS settings ======================="
echo "MKL_NUM_THREADS      : \$MKL_NUM_THREADS"
echo "OPENBLAS_NUM_THREADS : \$OPENBLAS_NUM_THREADS"
echo "NUMEXPR_NUM_THREADS  : \$NUMEXPR_NUM_THREADS"
echo "======================================================="

# ============================
# PyTorch (FairChem backend)
# ============================
export TORCH_NUM_THREADS=\$OMP_NUM_THREADS
export TORCH_DISTRIBUTED_DEBUG=OFF

echo "================ PyTorch settings ======================"
echo "TORCH_NUM_THREADS    : \$TORCH_NUM_THREADS"
echo "======================================================="


# ============================
# Run FairChem (NO srun)
# ============================



hostname

if [ -f /opt/anaconda3/bin/activate ]; then
    source /opt/anaconda3/bin/activate fairchem
elif [ -f /opt/miniconda3/bin/activate ]; then
    source /opt/miniconda3/bin/activate fairchem
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

#python gptfakeQE.py INPUT.data opt1_steps opt1_fmax opt2_steps opt2_fmax npt_steps do_supercell  eq_steps eq_temp eq_press eq_timestep  prod_steps prod_low prod_high prod_press prod_timestep prod_freq  cx cy cz model task
#python gptfakeQE.py 20260105_093642_optimized_out-fcc-Al04Co33Cr22Fe15Mo01Nb01Ni25Ta01Ti02W01_out.data 1 0.2 1 0.1 1 1 400.0 1.0 2.0 0 0 0 1 1 1 uma-s-1p1 omat
#see usage in fairchem.py
rm -f *.sout
rm -f *.in

#python -u gptfakeQE.py 20260105_093642_optimized_out-fcc-Al04Co33Cr22Fe15Mo01Nb01Ni25Ta01Ti02W01_out.data 5 0.2 5 0.1 20 1 300.0 0.0 1.0 1 1 1 uma-s-1p1 omat
export CUDA_VISIBLE_DEVICES=-1

$str

perl /opt/qe_perl/QEout_analysis.pl
perl /opt/qe_perl/QEout2data.pl

end_time=\$(date +%s)
elapsed=\$((end_time - start_time))

echo "Wall time: \${elapsed} seconds"
echo "Wall time: \$(date -u -d @\${elapsed} +%H:%M:%S)"

END_MESSAGE
        unlink "$out_folder/$folder-UMA/$foldname/$foldname.sh";
        open(FH, "> $out_folder/$folder-UMA/$foldname/$foldname.sh") or die $!;
        print FH $here_doc;
        close(FH);
        }
    }
}



