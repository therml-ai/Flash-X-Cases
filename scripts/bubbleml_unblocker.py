import argparse
import glob
import os
import json

from joblib import Parallel, delayed
import h5py
import numpy as np
import boxkit

# The staggered velocity is stored under different names depending on the file.
# Checkpoints carry every face variable as fc[xy]<n>, where <n> is the face
# variable index for that build (velc is 8 for a varDens multiphase setup, but
# the index moves if the unit set changes). Plotfiles carry only the velocity,
# written by name as fv_x/fv_y, so those are preferred when present.
FACE_VARS_BY_NAME = ['fv_x', 'fv_y']
FACE_VARS_BY_INDEX = ['fcx8', 'fcy8']


class FlashxLoader:
    def __init__(self, directory, file_tag='chk'):
        filenames = glob.glob(directory + '/*')
        # match the basename: a parent directory named e.g. plt_input would
        # otherwise pull in every file in the directory, heater file included
        chk_files = sorted([f for f in filenames if file_tag in os.path.basename(f)])
        if not chk_files:
            raise ValueError(f'No files matching "{file_tag}" in {directory}')
        # The heater file is metadata only. Older Flash-X configures the heater
        # through runtime parameters and writes no *_hdf5_htr_* file, so its
        # absence must not block unblocking the fields.
        heater_files = [f for f in filenames if 'htr' in os.path.basename(f)]
        heater = h5py.File(heater_files[0], 'r') if heater_files else None
        if heater is None:
            print('no heater file in directory, omitting heater metadata from the parameters json')

        frame = h5py.File(chk_files[0], 'r')

        # Pick the face velocity naming from the first frame, then require every
        # other frame to agree. A run directory can hold output from more than
        # one run - stale plotfiles written before fv_x existed, for instance -
        # and silently stitching those together would build a time series
        # spanning two different simulations.
        if all(var in frame for var in FACE_VARS_BY_NAME):
            self.face_vars = FACE_VARS_BY_NAME
        elif all(var in frame for var in FACE_VARS_BY_INDEX):
            self.face_vars = FACE_VARS_BY_INDEX
        else:
            raise ValueError(f'{chk_files[0]} has no face velocity: expected '
                             f'{FACE_VARS_BY_NAME} or {FACE_VARS_BY_INDEX}')

        stale = [f for f in chk_files
                 if not all(var in h5py.File(f, 'r') for var in self.face_vars)]
        if stale:
            raise ValueError(f'{len(stale)} of {len(chk_files)} files are missing '
                             f'{self.face_vars}, first is {stale[0]}. A directory holding '
                             f'output from more than one run has to be separated before '
                             f'unblocking.')
        print(f'{len(chk_files)} frames, face velocity from {self.face_vars}')
        string_runtime_params = {x[0].decode('UTF-8').strip(): x[1].decode('UTF-8').strip() for x in frame['string runtime parameters'][()]}
        real_runtime_params = {x[0].decode('UTF-8').strip(): x[1] for x in frame['real runtime parameters'][()]}

        integer_runtime_params = {x[0].decode('UTF-8').strip(): x[1] for x in frame['integer runtime parameters'][()]}
        nblocky, nblockx = int(integer_runtime_params['nblocky']), int(integer_runtime_params['nblockx'])

        integer_scalars = {x[0].decode('UTF-8').strip(): x[1] for x in frame['integer scalars'][()]}
        ny_block, nx_block = int(integer_scalars['nyb']), int(integer_scalars['nxb'])

        # cast to float64: older plotfiles store the bounding box in float32, and
        # np.linspace on float32 endpoints returns a float32 coordinate grid
        bounding_box = frame['bounding box'][()].astype(np.float64)
        xmax, xmin = bounding_box[:,0,:].max(), bounding_box[:,0,:].min()
        ymax, ymin = bounding_box[:,1,:].max(), bounding_box[:,1,:].min()

        Ny, Nx = nblocky*ny_block, nblockx*nx_block
        dx = (xmax - xmin)/Nx
        dy = (ymax - ymin)/Ny
        x_faces = np.linspace(xmin, xmax, Nx+1)
        y_faces = np.linspace(ymin, ymax, Ny+1)
        x_centers = 0.5*(x_faces[1:] + x_faces[:-1])
        y_centers = 0.5*(y_faces[1:] + y_faces[:-1])

        # domain origin and spacing, used to place each block in the global array
        self.xmin, self.ymin = xmin, ymin
        self.dx, self.dy = dx, dy

        # A plotfile only carries the variables named by plot_var_* in flash.toml,
        # so it can hold fewer fields than a checkpoint. Load what is there and say
        # what is missing rather than failing on the first absent one.
        cell_load = ['dfun', 'temp', 'velx', 'vely', 'nrmx', 'nrmy', 'mflx', 'pres', 'rhoc', 'lmfl']
        cell_save = ['dfun', 'temperature', 'velx', 'vely', 'normx', 'normy',
                     'massflux', 'pressure', 'rhoc', 'massflux_lag']

        absent = [v for v in cell_load if v not in frame]
        if absent:
            print(f'not in these files, skipping: {absent} '
                  f'(add them as plot_var_* in flash.toml to get them in plotfiles)')

        self.load_vars = [v for v in cell_load if v not in absent] + self.face_vars
        self.save_vars = [t for v, t in zip(cell_load, cell_save)
                          if v not in absent] + ['velfacex', 'velfacey']

        # Field arrays are filled from the worker results below; only the grid
        # coordinates are set here.
        self.data = {
                'x_centers': x_centers,
                'y_centers': y_centers,
                'x_faces': x_faces,
                'y_faces': y_faces,
                }

        self.parameters = {
                'geometry': string_runtime_params['geometry'],
                'xl_boundary_type': string_runtime_params['xl_boundary_type'],
                'xr_boundary_type': string_runtime_params['xr_boundary_type'],
                'yl_boundary_type': string_runtime_params['yl_boundary_type'],
                'yr_boundary_type': string_runtime_params['yr_boundary_type'],
                'num_blocks_x': nblockx,
                'num_blocks_y': nblocky,
                'nx_block': nx_block,
                'ny_block': ny_block,
                'dt': float(real_runtime_params['checkpointfileintervaltime']),
                't_initial': float(real_runtime_params['tinitial']),
                't_final': float(real_runtime_params['tmax']),
                'x_min': float(real_runtime_params['xmin']),
                'x_max': float(real_runtime_params['xmax']),
                'y_min': float(real_runtime_params['ymin']),
                'y_max': float(real_runtime_params['ymax']),
                'gravx': float(real_runtime_params['ins_gravx']),
                'gravy': float(real_runtime_params['ins_gravy']),
                'gravz': float(real_runtime_params['ins_gravz']),
                'prandtl': float(real_runtime_params['ht_prandtl']),
                'inv_reynolds': float(real_runtime_params['ins_invreynolds']),
                'inflow_velscale': float(real_runtime_params['ins_inflowvelscale']),
                'cpgas': float(real_runtime_params['mph_cpgas']),
                'mugas': float(real_runtime_params['mph_mugas']),
                'rhogas': float(real_runtime_params['mph_rhogas']),
                'thcogas': float(real_runtime_params['mph_thcogas']),
                'stefan': float(real_runtime_params['mph_stefan']),
            }
        if heater is not None:
            self.parameters.update({
                'heater': {k: heater['heater'][k][()].tolist()[0] for k in heater['heater'].keys()},
                'nuc_seed_radii': heater['init']['radii'][()].tolist(),
                'nuc_sites_x': heater['site']['x'][()].tolist(),
                'nuc_sites_y': heater['site']['y'][()].tolist(),
            })

        results = Parallel(n_jobs=-1)(delayed(self._load_data)(i, f) for i, f in enumerate(chk_files))

        # worst disagreement between two blocks sharing a face, over all frames
        seam_mismatch = max(result.pop('_seam_mismatch') for result in results)

        for k in results[0].keys():
            self.data[k] = np.array([result[k] for result in results], dtype=np.float64)
            print(f'{k} of shape {self.data[k].shape}')

        if seam_mismatch > 0.0:
            print(f'max disagreement between blocks at a shared face: {seam_mismatch:.3e} '
                  f'(averaged; this sets the divergence error at block seams)')

        if 'continuity_residual' not in self.data:
            print('continuity residual not computed: needs rhoc, mflx, nrmx, nrmy')
            return

        residual = self.data['continuity_residual']
        print(f'max |continuity residual| off the domain boundary: '
              f'{np.nanmax(np.abs(residual)):.3e} '
              f'({int(np.isnan(residual[0]).sum())} cells per frame masked as boundary)')
        if 'continuity_residual_lag' in self.data:
            print(f'max |continuity residual| with the lagged mass flux (lmfl): '
                  f'{np.nanmax(np.abs(self.data["continuity_residual_lag"])):.3e}')


    def _block_origin(self, block_xmin, block_ymin, x_bs, y_bs):
        """Index of a block's lower left cell in the global array.

        Snapped to a multiple of the block size so float noise in the bounding
        box cannot shift a block by a cell.
        """
        r = y_bs * int(round((block_ymin - self.ymin)/(self.dy*y_bs)))
        c = x_bs * int(round((block_xmin - self.xmin)/(self.dx*x_bs)))
        return r, c

    def _block_divergence(self, h5_frame, x_bs, y_bs, Ny, Nx):
        """div(u) evaluated inside each block, then stitched.

        Divergence is a cell quantity, so every cell is computed from the faces of
        the block that owns it and the disagreement between blocks at a shared
        face never enters the derivative. Assembling the global face array first
        and differentiating that would instead spread the seam mismatch into the
        cells on both sides of every block boundary.
        """
        div = np.zeros((Ny, Nx), dtype=np.float64)
        bbox = h5_frame['bounding box'][()]
        fcx, fcy = (h5_frame[self.face_vars[0]][()], h5_frame[self.face_vars[1]][()])

        for i in range(bbox.shape[0]):
            r, c = self._block_origin(bbox[i,0,:].min(), bbox[i,1,:].min(), x_bs, y_bs)
            div[r:r+y_bs, c:c+x_bs] = (
                (np.float64(fcx[i,0,:,1:]) - np.float64(fcx[i,0,:,:-1]))/self.dx
                + (np.float64(fcy[i,0,1:,:]) - np.float64(fcy[i,0,:-1,:]))/self.dy)

        return div

    def _continuity_residual(self, div_u, data_i, massflux):
        """div(u) + mflx*(n . grad(rho)), the mass source taken on the global field.

        grad(rho) is centered on the assembled array so it uses the real neighbors
        across block seams, rather than falling back on one-sided differences at
        every block edge. The one cell ring around the domain is set to NaN: those
        cells need ghost values from the physical boundary conditions
        (xl/xr/yl/yr_boundary_type), which the checkpoint does not carry.
        """
        rho = data_i['rhoc']
        grad_x, grad_y = np.zeros_like(rho), np.zeros_like(rho)
        grad_x[:, 1:-1] = (rho[:, 2:] - rho[:, :-2])/(2*self.dx)
        grad_y[1:-1, :] = (rho[2:, :] - rho[:-2, :])/(2*self.dy)

        source = massflux*(data_i['normx']*grad_x + data_i['normy']*grad_y)

        residual = div_u + source
        residual[0, :], residual[-1, :] = np.nan, np.nan
        residual[:, 0], residual[:, -1] = np.nan, np.nan

        return residual

    def _load_data(self, time_index, filename):
        h5_frame = h5py.File(filename, 'r')
        frame = boxkit.read_dataset(filename, source='flash')
        blocks = frame.blocklist

        nblockx, nblocky = self.parameters['num_blocks_x'], self.parameters['num_blocks_y']

        x_bs, y_bs = self.parameters['nx_block'], self.parameters['ny_block']

        # the placement math below assumes every block is a leaf at the coarsest
        # level, which is what makes a single uniform array the right target
        levels = h5_frame['refine level'][()]
        if not (levels == 1).all():
            raise ValueError(f'{filename} contains refined blocks (levels '
                             f'{sorted(set(levels.tolist()))}). Unblocking onto a '
                             f'{nblocky*y_bs}x{nblockx*x_bs} uniform grid would place '
                             f'fine blocks on coarse indices and overwrite siblings.')

        Ny, Nx = nblocky*y_bs, nblockx*x_bs
        data_i = {k: np.zeros((Ny, Nx), dtype=np.float64) for k in self.save_vars if k not in ['velfacex', 'velfacey']}

        # Face variables are shared between neighboring blocks: block b stores
        # nxb+1 x-faces, so its high face is the same physical face as its
        # neighbor's low face. Both copies are accumulated and divided by the
        # number of contributions, which averages the two values at a seam and
        # leaves every interior and domain-boundary face exactly as stored.
        # The previous version dropped each block's high face and reconstructed
        # the last one by extrapolating from the cell-centered velocity.
        face_shapes = {'velfacex': (Ny, Nx+1), 'velfacey': (Ny+1, Nx)}
        face_sum = {k: np.zeros(s, dtype=np.float64) for k, s in face_shapes.items()}
        face_count = {k: np.zeros(s, dtype=np.int32) for k, s in face_shapes.items()}
        face_lo = {k: np.full(s, np.inf) for k, s in face_shapes.items()}
        face_hi = {k: np.full(s, -np.inf) for k, s in face_shapes.items()}

        for load_var, save_var in zip(self.load_vars, self.save_vars):
            if load_var in frame.varlist:
                for block in blocks:
                    r, c = self._block_origin(block.xmin, block.ymin, x_bs, y_bs)
                    tmp = block[load_var]
                    data_i[save_var][r:r+y_bs, c:c+x_bs] = np.float64(tmp)
            else:
                for i, block in enumerate(h5_frame[load_var]):
                    block_xmin = h5_frame['bounding box'][()][i,0,:].min()
                    block_ymin = h5_frame['bounding box'][()][i,1,:].min()
                    r, c = self._block_origin(block_xmin, block_ymin, x_bs, y_bs)

                    if save_var in ['velfacex', 'velfacey']:
                        # every face the block owns, high face included.
                        # Keyed off save_var so the fv_x/fcx8 naming does not matter.
                        dr, dc = (0, 1) if save_var == 'velfacex' else (1, 0)
                        sl = (slice(r, r+y_bs+dr), slice(c, c+x_bs+dc))
                        values = np.float64(block[0])
                        face_sum[save_var][sl] += values
                        face_count[save_var][sl] += 1
                        face_lo[save_var][sl] = np.minimum(face_lo[save_var][sl], values)
                        face_hi[save_var][sl] = np.maximum(face_hi[save_var][sl], values)
                    else:
                        data_i[save_var][r:r+y_bs, c:c+x_bs] = np.float64(block[0])

        for key in face_shapes:
            if (face_count[key] == 0).any():
                raise ValueError(f'{filename}: {key} has faces no block wrote to')
            data_i[key] = face_sum[key]/face_count[key]

        # a seam where the two blocks disagree cannot be made divergence free on
        # both sides by any single valued face array, so report the disagreement
        # instead of hiding it
        data_i['_seam_mismatch'] = max(
            float(np.max(np.where(face_count[key] > 1, face_hi[key] - face_lo[key], 0.0)))
            for key in face_shapes)

        data_i['divergence'] = self._block_divergence(h5_frame, x_bs, y_bs, Ny, Nx)
        # the mass source needs rhoc/mflx and the interface normals; without them
        # only the divergence itself can be formed
        if all(v in data_i for v in ['rhoc', 'massflux', 'normx', 'normy']):
            data_i['continuity_residual'] = self._continuity_residual(
                data_i['divergence'], data_i, massflux=data_i['massflux'])
            # Files from the realigned-output branch also carry the mass flux the
            # projection actually used. Against that one the identity holds to
            # round-off; against the realigned mflx it holds to O(dt).
            if 'massflux_lag' in data_i:
                data_i['continuity_residual_lag'] = self._continuity_residual(
                    data_i['divergence'], data_i, massflux=data_i['massflux_lag'])

        return data_i

if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument('--sim_dir', type=str, help='Directory to load flashx simulation data from')
    parser.add_argument('--output_dir', type=str, help='Directory to save output visualization and unblocked hdf5 file')
    parser.add_argument('--file_tag', type=str, default='chk',
                        help='Substring selecting which files to load: "chk" for checkpoints '
                             '(face velocity as fcx8/fcy8), "plt" for plotfiles (fv_x/fv_y, '
                             'written at the plotfile cadence so a much longer time series)')

    args = parser.parse_args()

    sims = [d for d in os.listdir(args.sim_dir) if 'Twall' in d]
    print(sims)
    for sim in sims:
        print(f'Processing {sim}')
        sim_obj = FlashxLoader(os.path.join(args.sim_dir, sim), file_tag=args.file_tag)
        with h5py.File(os.path.join(args.output_dir, sim + '.hdf5'), 'w') as f:
            for key in sim_obj.data.keys():
                f.create_dataset(key, data=sim_obj.data[key])
        json_path = os.path.join(args.output_dir, sim + '.json')
        with open(json_path, 'w') as f_json:
            json.dump(sim_obj.parameters, f_json, indent=4, default=str)
        print(f'Wrote {sim} to {args.output_dir}')

    print(f"✅ Processing complete.")

