# cache the value of current working directory

FlashSha="main"

FlashOptions="incompFlow/BubblyFlow -auto -maxblocks=1024 -3d -nxb=32 -nyb=32 -nzb=32 \
              +amrex +nolwf -site=$SiteHome +incomp -tomlfile=$JobWorkDir/job.input --with-unitmods"
