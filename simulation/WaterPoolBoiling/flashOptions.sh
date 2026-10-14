# cache the value of current working directory

FlashSha="main"

FlashOptions="incompFlow/PoolBoiling -auto -maxblocks=50 -2d -nxb=16 -nyb=16 \
              +amrex +nolwf +serialIO -site=$SiteHome +incomp -tomlfile=$JobWorkDir/job.input --with-unitmods"
