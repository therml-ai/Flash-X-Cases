cd $JobWorkDir
echo "mpirun: $(which mpirun)"
echo "target: $(readlink -f job.target)"
mpirun $JobWorkDir/job.target
