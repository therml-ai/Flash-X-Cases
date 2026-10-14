# cache the value of current working directory

FlashSha="main"

FlashOptions="incompFlow/ChannelFlow -auto \
              -maxblocks=1000 -2d -nxb=16 -nyb=16 \
              -with-unit=physics/ImBound/ImBoundMain \
              +incomp +nolwf InsForceInOut=False +amrex +serialIO -site=$SiteHome"
