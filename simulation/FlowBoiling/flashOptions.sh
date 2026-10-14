# cache the value of current working directory

FlashSha="main"

FlashOptions="incompFlow/FlowBoiling -auto -maxblocks=300 -2d -nxb=8 -nyb=8 \
              +amrex +parallelIO +nolwf -site=$SiteHome +incomp -tomlfile=$JobWorkDir/job.input --with-unitmods"

if [ $Profile = True ]; then
	FlashOptions="$FlashOptions +hpctoolkit"
fi
