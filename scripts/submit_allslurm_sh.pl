=b
make lmp input files for all strucutres in labelled folders.
You need to use this script in the dir with all dpgen collections (in all_cfgs folder)
perl ../tool_scripts/cfg2lmpinput.pl 
=cut
use warnings;
use strict;
use JSON::PP;
use Data::Dumper;
use List::Util qw(min max);
use Cwd;
use POSIX;
use Parallel::ForkManager;
use List::Util qw/shuffle/;

my $currentPath = getcwd();# dir for all scripts

# Resolve UMA_inputs from this script's own location, so the repository works
# no matter where it is cloned.
use FindBin;
use File::Spec;
my $repo_root = Cwd::abs_path(File::Spec->catdir($FindBin::Bin, ".."));
die "Cannot resolve repo root from $FindBin::Bin!" unless defined $repo_root && -d $repo_root;
my $filefold = "$repo_root/UMA_inputs";

if (@ARGV && $ARGV[0] eq "--check-paths") {
    print "repo root  : $repo_root\n";
    print "job folder : $filefold\n";
    exit 0;
}

my $forkNo = 1;#although we don't have so many cores, only for submitting jobs into slurm
my $pm = Parallel::ForkManager->new("$forkNo");

my @all_files = `find $filefold -type f -name "*.sh" `;
#my @all_files = `find $filefold -maxdepth 2 -mindepth 2 -type f -name "*.sh" `;
#my @all_files = `find $currentPath/$filefold -maxdepth 2 -mindepth 2 -type f -name "*.sh" -exec readlink -f {} \\;|sort`;
map { s/^\s+|\s+$//g; } @all_files;
@all_files = shuffle(@all_files);

for my $i (@all_files){
    my $dirname = `dirname $i`;
    $dirname =~ s/^\s+|\s+$//g;
    chdir($dirname);
    my $prefix = `basename $i`;
    $prefix =~ s/^\s+|\s+$//g;
    $prefix =~ s/\.sh//g;
    `sbatch $prefix.sh`;
}#  

