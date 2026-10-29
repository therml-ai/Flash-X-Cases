## Project Background

Case files and build scripts for Flash-X multiphase simulations (pool boiling, flow boiling,
rising bubbles). This repository does not contain Flash-X; the setup scripts clone it. 

Everything is driven by [Jobrunner](https://github.com/Lab-Notebooks/Jobrunner) (`jobrunner`) and which
combinations of `Jobfile`s from the project root down to a working directory and runs the scripts they
list there. Run the `jobrunner` command from the project root.

- `configure`: writes `config.sh` (the site name) for `environment.sh`.
- `environment.sh`: sources `sites/<site>/environment.sh`, then exports `FLASHX_HOME`, `AMREX2D_HOME`,
  `AMREX3D_HOME`, `HDF5_HOME`, and the other paths every script uses.
- `sites/<site>/`: per-machine `environment.sh` (modules, MPI) and `Makefile.h` (Flash-X compiler flags).
  `sites/hpc3/setup.sbatch` runs `jobrunner setup` as a Slurm job.
- `software/<package>/`: scripts that clone and build AMReX, Flash-X, HDF5, and the rest into
  `software/<package>/<Package>/` (git-ignored).
- `simulation/{2d,3d}/<group>/<case>/`: one directory per simulation. `dev/` holds development and test cases.
- `tests/`: Flash-X test suites run through `flashxtest`.

## Setup

1. Python, managed with `uv` (the project needs Python < 3.12):

   ```console
   uv venv
   source .venv/bin/activate
   uv sync
   ```

   The site `environment.sh` activates `.venv`, so jobs launched by `jobrunner` use the
   same environment.

2. Configure the site, once per clone. This writes `config.sh`, which is git-ignored:

   ```console
   ./configure -s hpc3          # or e.g. sedona/gcc-12.3.0
   ```

   A new machine needs a `sites/<name>/` directory with `environment.sh` and `Makefile.h`. New
   files can be copied and modified from an existing site.

3. Build the dependencies. MPI must already be available (loaded in the site `environment.sh`). AMReX
   (2D and 3D), Flash-X, and HDF5 are built here. HDF5 is skipped if the site exports `HDF5_HOME`.

   ```console
   jobrunner setup software/amrex software/flashx software/hdf5 --verbose
   ```

   On hpc3, run this as a job rather than on the login node:

   ```console
   sbatch -A <account> sites/hpc3/setup.sbatch software/amrex software/flashx software/hdf5
   ```

   `software/flashx/setupFlashX.sh` clones `git@github.com:therml-ai/Flash-X` (branch `main`, needs
   access to the private repository) into `software/flashx/Flash-X`, which becomes `$FLASHX_HOME`. It
   skips the clone if that directory exists, so a symlink there makes builds use another checkout.

## Running a Simulation

A case's `Jobfile` lists its `setup` scripts (`flashOptions.sh`, `flashBuild.sh`) and its `submit` scripts
(`flashRun.sh`, plus e.g. `flashInput.sh` or `calResources.sh`). Parameters live in `flash.par` or
`flash.toml`. Scheduler options (`#SBATCH` lines) are the `schedular` sections of the Jobfiles along
the path, appended in order from the root, so a deeper Jobfile overrides a flag by repeating it
(`sbatch` takes the last value).

1. Build: `jobrunner setup <case dir> --verbose` (or `sbatch sites/hpc3/setup.sbatch <case dir>` on hpc3).
   `flashBuild.sh` runs `git checkout $FlashSha` and `./setup $FlashOptions` in `$FLASHX_HOME`, compiles
   in `$FLASHX_HOME/object`, and copies `flashx` (and `amrex.pc`, heater files, ...) into the case.
2. Run: `jobrunner submit <case dir> --verbose` writes `job.submit` and passes it to `sbatch`.
3. Inspect without running: add `--show` to either command to print the merged Jobfile configuration.

The outputs (`INS_*_hdf5_plt_cnt_*` plotfiles, `*_hdf5_chk_*` checkpoints, the `.log` file) are written
in the case directory.

Example, the 2D single bubble pool boiling cases, which share one executable:

```console
simulation/2d/PoolBoiling/SingleBubble-FC72-2D/generate.sh
jobrunner setup simulation/2d/PoolBoiling/SingleBubble-FC72-2D --verbose
jobrunner submit simulation/2d/PoolBoiling/SingleBubble-FC72-2D/case-twall-100 --verbose
```

## Things to Know

- Only one Flash-X build can run at a time: every build uses the same `$FLASHX_HOME/object` directory,
  and `flashBuild.sh` checks out `$FlashSha` in the shared Flash-X checkout. Commit or stash Flash-X
  edits you want to keep before a build changes branches.
- Builds use `make -j $SLURM_CPUS_PER_TASK`, so they are meant to run inside a Slurm allocation.
- Files `jobrunner` writes (`job.setup`, `job.submit`, `job.target`, `job.input`, `job.output`) are
  generated; do not edit them. Change the Jobfile or the scripts it lists instead.
- Generated case directories are not edited by hand or committed. A study built from cases, such as
  `SingleBubble-FC72-2D`, keeps a `generate.sh` that calls its `generate_cases.py` with the cases it
  runs; its `case-*` directories are git-ignored. To change the cases, edit the base `flash.toml`,
  `generate_cases.py`, or the arguments in `generate.sh`, then rerun `generate.sh`.
- cases should have a `parameters.json` file that tracks every parameter.
- `flash.toml` cases: `flashInput.py` merges the base and the case `flash.toml` into `flash.par` at
  submit, applying the case's `[Override.<Unit>]` tables. An override must name a parameter already set
  in the base `flash.toml`, so that Flash-X's setup checks it.
- Change the account, partition, and task count in the `schedular` section of a Jobfile, not in
  generated `job.submit` files. The root `Jobfile` sets the defaults.
