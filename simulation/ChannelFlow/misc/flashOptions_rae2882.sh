# cache the value of current working directory

FlashSha="main"

FlashOptions="incompFlow/ChannelFlow -auto \
              -maxblocks=1000 -2d -nxb=8 -nyb=8 \
              -with-unit=physics/ImBound/ImBoundMain \
              +incomp +nolwf +amrex +serialIO -site=$SiteHome"
