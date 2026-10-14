"""Sanity checks for unblocked Flash-X data produced by bubbleml_unblocker.py

Runs three checks on every timestep of an unblocked HDF5 file:

  1. divergence   - discrete divergence of the staggered face velocities,
                    div = d(velfacex)/dx + d(velfacey)/dy. For an incompressible
                    projection this is ~0 away from the interface. Cells near the
                    interface are reported separately, since evaporative mass flux
                    makes the velocity field legitimately non-solenoidal there.
  2. eikonal      - |grad(dfun)| should be 1 for a signed distance function. Level
                    sets are typically only reinitialized in a band around the
                    interface, so the band is the part that must pass.
  3. nan/inf      - every dataset is scanned for non-finite values.

Exits non-zero if any check fails, so it can be used as a gate in a pipeline.
"""

import argparse
import sys

import h5py
import numpy as np


def finite_max(values):
    """Max |value| over finite entries only, 0 if there are none.

    Guards the tolerance arithmetic: a bare max() over an array holding Inf gives
    an infinite velocity scale, which would make every normalized divergence 0
    and report a corrupt timestep as clean. NaN would fail every comparison and
    do the same. Steps holding non-finite values are failed explicitly instead.
    """
    values = np.abs(values[np.isfinite(values)])
    return float(values.max()) if values.size else 0.0


def spacing(faces, name):
    """Return uniform grid spacing from a face coordinate array"""
    d = np.diff(faces)
    if not np.allclose(d, d[0]):
        raise ValueError(f'{name} is non-uniform, these checks assume a uniform grid')
    return float(d[0])


# fields the unblocker deliberately leaves NaN on the one cell domain boundary
# ring, because computing them there needs physical-BC ghost values the
# checkpoint does not carry. NaN inside the ring is still a failure.
RING_MASKED_FIELDS = {'continuity_residual', 'continuity_residual_lag'}


def check_nans(h5file):
    """Scan every dataset for NaN/Inf values"""
    print('--- non-finite values ---')
    failures = []
    for key in sorted(h5file.keys()):
        data = h5file[key][()]
        if not np.issubdtype(data.dtype, np.floating):
            continue
        if key in RING_MASKED_FIELDS and data.ndim == 3:
            ring = int(np.isnan(data).sum()) - int(np.isnan(data[:, 1:-1, 1:-1]).sum())
            data = data[:, 1:-1, 1:-1]
            print(f'  ---  {key:12s} {ring} NaN on the masked boundary ring (expected)')
        n_nan = int(np.isnan(data).sum())
        n_inf = int(np.isinf(data).sum())
        if n_nan or n_inf:
            failures.append(key)
            print(f'  FAIL {key:12s} {n_nan} NaN, {n_inf} Inf out of {data.size}')
            # report which timesteps are affected for time-varying fields
            if data.ndim == 3:
                bad = np.where(~np.isfinite(data).all(axis=(1, 2)))[0]
                print(f'       affected timesteps: {bad.tolist()}')
        else:
            print(f'  ok   {key:12s} {data.size} values finite')
    return failures


def check_divergence(h5file, dx, dy, dfun, band_cells, tol):
    """Discrete divergence of the staggered face velocity field"""
    print('--- divergence of face velocities ---')
    vfx, vfy = h5file['velfacex'][()], h5file['velfacey'][()]

    # div on cell centers from the surrounding faces
    div = (vfx[:, :, 1:] - vfx[:, :, :-1])/dx + (vfy[:, 1:, :] - vfy[:, :-1, :])/dy

    # cells whose distance to the interface is within band_cells of the grid size
    near = np.abs(dfun) <= band_cells*max(dx, dy)

    failures = []
    print(f'  {"step":>4s} {"max|div| bulk":>14s} {"normalized":>11s} '
          f'{"max|div| band":>14s} {"band cells":>11s}')
    for step in range(div.shape[0]):
        d, n = div[step], near[step]
        u_scale = max(finite_max(h5file['velx'][step]),
                      finite_max(h5file['vely'][step]), 1e-30)

        bulk = finite_max(d[~n]) if (~n).any() else 0.0
        band = finite_max(d[n]) if n.any() else 0.0

        # dimensionless: divergence scaled by the cell transit time dx/u
        normalized = bulk*min(dx, dy)/u_scale

        # non-finite values anywhere in the divergence fail the step outright
        nonfinite = int((~np.isfinite(d)).sum())
        status = 'ok  ' if normalized <= tol and not nonfinite else 'FAIL'
        if normalized > tol or nonfinite:
            failures.append(step)
        print(f'  {status} {step:>2d} {bulk:14.3e} {normalized:11.3e} '
              f'{band:14.3e} {int(n.sum()):11d}')
        if nonfinite:
            print(f'       {nonfinite} non-finite cells in the divergence field '
                  f'(bulk/band maxima above ignore them)')

        # localize the offending cells. A whole row or column lighting up points
        # at the seam between two blocks rather than at the pressure solve: the
        # unblocker keeps one block's shared face value and drops its neighbor's.
        if normalized > tol:
            offending = np.argwhere((np.abs(d) > tol*u_scale/min(dx, dy)) & ~n)
            rows, cols = np.unique(offending[:, 0]), np.unique(offending[:, 1])
            print(f'       {len(offending)} bulk cells over tolerance')
            print(f'       rows: {rows.tolist()}')
            print(f'       cols: {cols.tolist()}')
            for row in rows:
                if (np.abs(d[row]) > tol*u_scale/min(dx, dy)).sum() == d.shape[1]:
                    print(f'       row {row} is fully saturated - looks like a block seam, '
                          f'not a solver residual')

    print(f'  (bulk = cells more than {band_cells} cells from the interface; band '
          f'divergence is informational, evaporation makes it non-zero)')
    return failures


def check_eikonal(dfun, dx, dy, band_cells, tol):
    """|grad(dfun)| should equal 1 for a signed distance function"""
    print('--- eikonal property of dfun ---')
    failures = []
    print(f'  {"step":>4s} {"median band":>12s} {"mean band":>10s} '
          f'{"max dev band":>13s} {"viol frac":>10s} {"median global":>14s}')
    for step in range(dfun.shape[0]):
        phi = dfun[step]
        # np.gradient returns d/d(axis0)=y first, arrays are indexed [y, x]
        dphi_dy, dphi_dx = np.gradient(phi, dy, dx)
        grad = np.hypot(dphi_dx, dphi_dy)

        near = np.abs(phi) <= band_cells*max(dx, dy)
        if not near.any():
            print(f'  WARN {step:>2d} no cells within {band_cells} cells of the interface')
            continue

        band = grad[near]
        deviation = np.abs(band - 1.0)
        viol = float((deviation > tol).mean())

        # a NaN median compares false against any tolerance, so check it explicitly
        nonfinite = int((~np.isfinite(grad)).sum())
        median = np.nanmedian(deviation) if np.isfinite(deviation).any() else np.nan

        status = 'ok  ' if median <= tol and not nonfinite else 'FAIL'
        if not (median <= tol) or nonfinite:
            failures.append(step)
        print(f'  {status} {step:>2d} {np.nanmedian(band):12.4f} {np.nanmean(band):10.4f} '
              f'{np.nanmax(deviation):13.4f} {viol:10.3f} {np.nanmedian(grad):14.4f}')
        if nonfinite:
            print(f'       {nonfinite} non-finite cells in grad(dfun)')

    print(f'  (band = |dfun| <= {band_cells} cells; tolerance on ||grad|-1| is {tol})')
    return failures


def check_file(path, band_cells, div_tol, eikonal_tol):
    """Run all three checks on one unblocked HDF5 file"""
    print(f'\n=== {path} ===')
    h5file = h5py.File(path, 'r')

    dx = spacing(h5file['x_faces'][()], 'x_faces')
    dy = spacing(h5file['y_faces'][()], 'y_faces')
    dfun = h5file['dfun'][()]
    print(f'{dfun.shape[0]} timesteps on a {dfun.shape[1]}x{dfun.shape[2]} grid, '
          f'dx={dx:.6g}, dy={dy:.6g}\n')

    nan_failures = check_nans(h5file)
    print()
    div_failures = check_divergence(h5file, dx, dy, dfun, band_cells, div_tol)
    print()
    eikonal_failures = check_eikonal(dfun, dx, dy, band_cells, eikonal_tol)

    print(f'\nsummary for {path}:')
    print(f'  non-finite  : {"FAIL " + str(nan_failures) if nan_failures else "pass"}')
    print(f'  divergence  : {"FAIL at steps " + str(div_failures) if div_failures else "pass"}')
    print(f'  eikonal     : {"FAIL at steps " + str(eikonal_failures) if eikonal_failures else "pass"}')

    return not (nan_failures or div_failures or eikonal_failures)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('path', type=str, nargs='+',
                        help='Path to unblocked hdf5 file(s) written by bubbleml_unblocker.py')
    parser.add_argument('--band_cells', type=float, default=3.0,
                        help='Width of the near-interface band, in cells (default 3)')
    parser.add_argument('--div_tol', type=float, default=1e-6,
                        help='Tolerance on normalized bulk divergence (default 1e-6)')
    parser.add_argument('--eikonal_tol', type=float, default=0.1,
                        help='Tolerance on ||grad(dfun)|-1| in the band (default 0.1)')

    args = parser.parse_args()

    ok = all([check_file(p, args.band_cells, args.div_tol, args.eikonal_tol)
              for p in args.path])

    print(f'\n{"✅ all checks passed" if ok else "❌ checks failed"}')
    sys.exit(0 if ok else 1)
