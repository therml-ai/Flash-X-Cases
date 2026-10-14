# cache the value of current working directory

FlashSha="main"

FlashOptions="incompFlow/PoolBoiling -auto -maxblocks=400 -2d -nxb=8 -nyb=8 \
              +amrex +nolwf +serialIO -site=$SiteHome +incomp -tomlfile=$JobWorkDir/job.input --with-unitmods"
