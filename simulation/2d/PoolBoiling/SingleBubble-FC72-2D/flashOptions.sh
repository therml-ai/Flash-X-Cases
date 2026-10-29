# cache the value of current working directory

FlashSha="main"

# +incomp sets InsForceInOut=True (formerly SimForceInOut) and IOWriteGridFiles=True
FlashOptions="incompFlow/PoolBoiling -auto -maxblocks=100 -2d -nxb=16 -nyb=16 \
              +amrex +parallelIO +incomp -site=$SiteHome -tomlfile=$JobWorkDir/job.input --with-unitmods"

if [ $Profile = True ]; then
	FlashOptions="$FlashOptions +hpctoolkit"
fi
