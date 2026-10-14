# cache the value of current working directory

FlashSha="main"

FlashOptions="incompFlow/FlowBoiling -auto -maxblocks=200 -3d -nxb=16 -nyb=16 -nzb=16 \
              +amrex +serialIO +nolwf -site=$SiteHome +incomp HeaterFluxBC=True"

if [ $Profile = True ]; then
	FlashOptions="$FlashOptions +hpctoolkit"
fi
