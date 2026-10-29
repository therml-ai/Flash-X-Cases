# cache the value of current directory
NodeDir=$(realpath .)

# The executable is built once from the top-level flash.toml. Each
# case-twall-* run needs its own flash.par, and the heater file written
# at setup. jobrunner only writes job.input during setup, so the base and
# case flash.toml are merged here instead.
cd $JobWorkDir && python3 $NodeDir/flashInput.py --input $NodeDir/flash.toml $JobWorkDir/flash.toml

# the heater file is already in place when submitting from this directory
if [ "$(realpath $JobWorkDir)" != "$NodeDir" ]; then
	cp $NodeDir/*_hdf5_htr_* $JobWorkDir/
fi
