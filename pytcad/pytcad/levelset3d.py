"""M35-S5: the level-set representation, advection, and topology ops
(deposit/etch/directional-etch/epitaxy/CMP) lifted to 3D. A direct
dimension-lift of `levelset2d.py`'s functions -- same algorithms, one
more axis, no new physics or design decisions. 3D oxidation/dopant
transport/silicidation live in the sibling modules
`oxidize_levelset3d.py`/`silicide_levelset3d.py` (same reason S3/S3b/S4
are separate modules from `levelset2d.py` in 2D). See
pytcad/M35-3D-PROCESS-PLAN.md sections 6, 16, 17.

Array convention: `X, Y, Z = np.meshgrid(x, y, z, indexing="ij")`, so
every `phi[name]` array has shape `(Nx, Ny, Nz)` -- NOT `levelset2d`'s
`(Ny, Nx)` order. This is an internally-consistent choice (every
function here uses it uniformly); a caller comparing against a 2D
result must transpose a `(Nx, Ny)` z-slice to `(Ny, Nx)` first (see the
S5 test file's own reduction gates for the exact pattern).

`marching_cubes_surface` (added for M35-S5/S6's smooth-geometry pass,
plan section 18) extracts a real triangulated isosurface from a
material's phi field -- the basis for `levelset3d_mesh.py`'s direct
tet meshing, as opposed to `gmsh_finfet3d.py`'s 2D-process-extrusion
path. It is a pure, read-only geometry query: it does not change any
advection/topology function above it, so it cannot affect (and does
not need to be reconciled against) the existing reduction-identity
gates.
"""
from dataclasses import dataclass
import numpy as np
from scipy.ndimage import distance_transform_edt, binary_dilation

from .levelset2d import MATERIAL_NAMES, _check_materials


@dataclass
class LevelSet3D:
    """3D analogue of `levelset2d.LevelSet2D` -- see that class's own
    docstring for the field-by-field meaning; only the added z extent
    is new here."""
    x0: float
    x1: float
    Nx: int
    y0: float
    y1: float
    Ny: int
    z0: float
    z1: float
    Nz: int
    materials: tuple = MATERIAL_NAMES
    phi: dict = None

    def __post_init__(self):
        self.materials = _check_materials(self.materials)
        self.x = np.linspace(self.x0, self.x1, self.Nx)
        self.y = np.linspace(self.y0, self.y1, self.Ny)
        self.z = np.linspace(self.z0, self.z1, self.Nz)
        self.dx = (self.x1 - self.x0) / (self.Nx - 1)
        self.dy = (self.y1 - self.y0) / (self.Ny - 1)
        self.dz = (self.z1 - self.z0) / (self.Nz - 1)
        self.X, self.Y, self.Z = np.meshgrid(self.x, self.y, self.z, indexing="ij")
        if self.phi is None:
            far = 10.0 * np.sqrt((self.x1 - self.x0) ** 2 + (self.y1 - self.y0) ** 2
                                  + (self.z1 - self.z0) ** 2)
            self.phi = {m: np.full((self.Nx, self.Ny, self.Nz), far) for m in self.materials}
        else:
            self.phi = {m: np.asarray(v, dtype=float).copy() for m, v in self.phi.items()}

    def copy(self):
        return LevelSet3D(self.x0, self.x1, self.Nx, self.y0, self.y1, self.Ny,
                           self.z0, self.z1, self.Nz, materials=self.materials,
                           phi={k: v.copy() for k, v in self.phi.items()})

    def material_map(self):
        stack = np.stack([self.phi[m] for m in self.materials], axis=0)
        return np.argmin(stack, axis=0)


def _grad_upwind_components3d(phi, dx, dy, dz):
    Dxm = np.empty_like(phi); Dxp = np.empty_like(phi)
    Dym = np.empty_like(phi); Dyp = np.empty_like(phi)
    Dzm = np.empty_like(phi); Dzp = np.empty_like(phi)

    Dxm[1:, :, :] = (phi[1:, :, :] - phi[:-1, :, :]) / dx
    Dxm[0, :, :] = Dxm[1, :, :]
    Dxp[:-1, :, :] = (phi[1:, :, :] - phi[:-1, :, :]) / dx
    Dxp[-1, :, :] = Dxp[-2, :, :]

    Dym[:, 1:, :] = (phi[:, 1:, :] - phi[:, :-1, :]) / dy
    Dym[:, 0, :] = Dym[:, 1, :]
    Dyp[:, :-1, :] = (phi[:, 1:, :] - phi[:, :-1, :]) / dy
    Dyp[:, -1, :] = Dyp[:, -2, :]

    Dzm[:, :, 1:] = (phi[:, :, 1:] - phi[:, :, :-1]) / dz
    Dzm[:, :, 0] = Dzm[:, :, 1]
    Dzp[:, :, :-1] = (phi[:, :, 1:] - phi[:, :, :-1]) / dz
    Dzp[:, :, -1] = Dzp[:, :, -2]

    return Dxm, Dxp, Dym, Dyp, Dzm, Dzp


def _godunov_grad_mag3d(phi, dx, dy, dz, V):
    Dxm, Dxp, Dym, Dyp, Dzm, Dzp = _grad_upwind_components3d(phi, dx, dy, dz)
    Vpos = V > 0
    Vneg = ~Vpos

    def pp(a): return np.maximum(a, 0.0)
    def nn(a): return np.minimum(a, 0.0)

    grad_pos = np.sqrt(
        np.maximum(pp(Dxm) ** 2, nn(Dxp) ** 2)
        + np.maximum(pp(Dym) ** 2, nn(Dyp) ** 2)
        + np.maximum(pp(Dzm) ** 2, nn(Dzp) ** 2)
    )
    grad_neg = np.sqrt(
        np.maximum(nn(Dxm) ** 2, pp(Dxp) ** 2)
        + np.maximum(nn(Dym) ** 2, pp(Dyp) ** 2)
        + np.maximum(nn(Dzm) ** 2, pp(Dzp) ** 2)
    )
    return np.where(Vpos, grad_pos, np.where(Vneg, grad_neg, 0.0))


def advect_upwind3d(phi, V, dx, dy, dz, dt):
    V = np.asarray(V, dtype=float)
    grad_mag = _godunov_grad_mag3d(phi, dx, dy, dz, V if V.ndim else np.full_like(phi, V))
    return phi - dt * V * grad_mag


def cfl_dt3d(V, dx, dy, dz, cfl=0.5):
    Vmax = float(np.max(np.abs(V)))
    if Vmax == 0.0:
        return np.inf
    return cfl * min(dx, dy, dz) / Vmax


def _far_value3d(ls):
    return 10.0 * np.sqrt((ls.x1 - ls.x0) ** 2 + (ls.y1 - ls.y0) ** 2 + (ls.z1 - ls.z0) ** 2)


def _project_from_owner3d(ls, mat_idx):
    far = _far_value3d(ls)
    out = ls.copy()
    for i, name in enumerate(ls.materials):
        inside = (mat_idx == i)
        if np.all(inside):
            out.phi[name] = np.full(inside.shape, -far)
        elif not np.any(inside):
            out.phi[name] = np.full(inside.shape, far)
        else:
            d_in = distance_transform_edt(inside, sampling=(ls.dx, ls.dy, ls.dz))
            d_out = distance_transform_edt(~inside, sampling=(ls.dx, ls.dy, ls.dz))
            out.phi[name] = np.where(inside, -d_in, d_out)
    return out


def project3d(ls):
    return _project_from_owner3d(ls, ls.material_map())


def advance_material3d(ls, material, V, t_total, cfl=0.5):
    """3D analogue of `levelset2d.advance_material` -- see its docstring
    for the S1 ownership rule and the receding-with-no-successor limit
    (unchanged here)."""
    if material not in ls.materials:
        raise ValueError(f"{material!r} not in this level set's materials {ls.materials}")
    idx_active = ls.materials.index(material)
    prev_owner = ls.material_map()
    cur = ls.copy()
    Varr = np.asarray(V, dtype=float)
    t = 0.0
    while t < t_total - 1e-15:
        dt = cfl_dt3d(Varr, ls.dx, ls.dy, ls.dz, cfl)
        dt = min(dt, t_total - t)
        cur.phi[material] = advect_upwind3d(cur.phi[material], Varr, ls.dx, ls.dy, ls.dz, dt)
        t += dt

    active_inside = cur.phi[material] < 0
    if np.any((prev_owner == idx_active) & ~active_inside):
        raise NotImplementedError(
            f"{material!r} receded from a point it owned with no other "
            f"material advected to claim it -- use advance_front3d instead"
        )
    new_owner = np.where(active_inside, idx_active, prev_owner)
    return _project_from_owner3d(cur, new_owner)


def advance_front3d(ls, receding, growing, V, t_total, cfl=0.5):
    """3D analogue of `levelset2d.advance_front` -- identical algorithm
    (erode `receding`'s own valid signed distance, hand what it gives up
    to `growing`; local grid-adjacency exposure test recomputed every
    substep for a non-"ambient" receding material; periodic single-
    material reinit by accumulated travel distance). See that function's
    docstring for the full reasoning -- unchanged here, just one more
    axis in every array op."""
    if receding not in ls.materials:
        raise ValueError(f"{receding!r} not in this level set's materials {ls.materials}")
    if growing not in ls.materials:
        raise ValueError(f"{growing!r} not in this level set's materials {ls.materials}")
    if receding == growing:
        raise ValueError("receding and growing must be different materials")

    idx_recede = ls.materials.index(receding)
    idx_grow = ls.materials.index(growing)
    prev_owner = ls.material_map()

    def _exposure_mask(phi_recede_now):
        if receding == "ambient":
            return phi_recede_now < 0
        recede_region_now = (prev_owner == idx_recede) & (phi_recede_now < 0)
        growing_region_now = (prev_owner == idx_grow) | (
            (prev_owner == idx_recede) & (phi_recede_now >= 0))
        if not np.any(recede_region_now) or not np.any(growing_region_now):
            return np.zeros_like(recede_region_now)
        return recede_region_now & binary_dilation(growing_region_now)

    Vmag = np.asarray(V, dtype=float)
    phi_recede = ls.phi[receding].copy()
    t = 0.0
    dist_since_reinit = 0.0
    reinit_every = min(ls.dx, ls.dy, ls.dz)
    while t < t_total - 1e-15:
        dt = cfl_dt3d(Vmag, ls.dx, ls.dy, ls.dz, cfl)
        dt = min(dt, t_total - t)
        if receding == "ambient":
            phi_recede = advect_upwind3d(phi_recede, -Vmag, ls.dx, ls.dy, ls.dz, dt)
        else:
            mask = _exposure_mask(phi_recede)
            updated = advect_upwind3d(phi_recede, -Vmag, ls.dx, ls.dy, ls.dz, dt)
            phi_recede = np.where(mask, updated, phi_recede)
            dist_since_reinit += dt * float(np.max(Vmag))
            if dist_since_reinit >= reinit_every:
                inside = phi_recede < 0
                if np.any(inside) and not np.all(inside):
                    d_in = distance_transform_edt(inside, sampling=(ls.dx, ls.dy, ls.dz))
                    d_out = distance_transform_edt(~inside, sampling=(ls.dx, ls.dy, ls.dz))
                    phi_recede = np.where(inside, -d_in, d_out)
                dist_since_reinit = 0.0
        t += dt

    gave_up = (prev_owner == idx_recede) & (phi_recede >= 0)
    new_owner = np.where(gave_up, idx_grow, prev_owner)
    cur = ls.copy()
    cur.phi[receding] = phi_recede
    return _project_from_owner3d(cur, new_owner)


def deposit_conformal3d(ls, material, thickness_um, rate_um_s=1.0, windows=None):
    """3D analogue of `levelset2d.deposit_conformal`. `windows`, an
    optional list of `(x_lo,x_hi,z_lo,z_hi)` boxes (the 3D analogue of
    2D's lateral `x_windows`), makes this a first-class 3D mask/pattern
    constructor -- zero rate outside the box, reusing `advance_front3d`'s
    array-V support. `windows=None` is exactly the pre-existing blanket
    behavior, unchanged."""
    t_total = thickness_um / rate_um_s
    if windows is not None:
        allowed = np.zeros((ls.Nx, ls.Nz), dtype=bool)
        for x_lo, x_hi, z_lo, z_hi in windows:
            allowed |= (((ls.x >= x_lo) & (ls.x <= x_hi))[:, None]
                        & ((ls.z >= z_lo) & (ls.z <= z_hi))[None, :])
        V = np.where(allowed[:, None, :], rate_um_s, 0.0) * np.ones((1, ls.Ny, 1))
    else:
        V = rate_um_s
    return advance_front3d(ls, receding="ambient", growing=material,
                            V=V, t_total=t_total)


def etch_isotropic3d(ls, material, depth_um, rate_um_s=1.0):
    t_total = depth_um / rate_um_s
    return advance_front3d(ls, receding=material, growing="ambient",
                            V=rate_um_s, t_total=t_total)


def etch_directional3d(ls, material, depth_um, direction=(0.0, -1.0, 0.0), rate_um_s=1.0):
    """3D analogue of `levelset2d.etch_directional`: normal speed =
    rate * max(n_hat . direction, 0), n_hat the local outward normal of
    `material`'s own interface (central differences on all 3 axes)."""
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    phi = ls.phi[material]
    gx = np.gradient(phi, ls.dx, axis=0)
    gy = np.gradient(phi, ls.dy, axis=1)
    gz = np.gradient(phi, ls.dz, axis=2)
    gmag = np.sqrt(gx ** 2 + gy ** 2 + gz ** 2)
    gmag_safe = np.where(gmag > 1e-12, gmag, 1.0)
    nx, ny, nz = gx / gmag_safe, gy / gmag_safe, gz / gmag_safe
    cos_theta = nx * direction[0] + ny * direction[1] + nz * direction[2]
    V = rate_um_s * np.maximum(cos_theta, 0.0)
    t_total = depth_um / rate_um_s
    return advance_front3d(ls, receding=material, growing="ambient",
                            V=V, t_total=t_total)


def deposit_epitaxial3d(ls, material, thickness_um, rate_fn=None, rate_um_s=1.0):
    """3D analogue of `levelset2d.deposit_epitaxial` -- see that
    function's docstring for why the gradient of `ls.phi["ambient"]`
    must be NEGATED to give `rate_fn` the physically intuitive "growth
    direction" convention. `rate_fn=None` reduces exactly (same code
    path) to `deposit_conformal3d`."""
    if rate_fn is None:
        return deposit_conformal3d(ls, material, thickness_um, rate_um_s)
    gx = np.gradient(ls.phi["ambient"], ls.dx, axis=0)
    gy = np.gradient(ls.phi["ambient"], ls.dy, axis=1)
    gz = np.gradient(ls.phi["ambient"], ls.dz, axis=2)
    gmag = np.sqrt(gx ** 2 + gy ** 2 + gz ** 2)
    gmag_safe = np.where(gmag > 1e-12, gmag, 1.0)
    nx, ny, nz = -gx / gmag_safe, -gy / gmag_safe, -gz / gmag_safe
    V = rate_um_s * np.maximum(rate_fn(nx, ny, nz), 0.0)
    t_total = thickness_um / rate_um_s
    return advance_front3d(ls, receding="ambient", growing=material,
                            V=V, t_total=t_total)


def planarize3d(ls, y_cmp_um):
    """3D analogue of `levelset2d.planarize` -- CMP as a one-shot
    ownership rewrite, no PDE. `y` increases downward (this module's
    own convention, unchanged from 2D)."""
    y_cmp = y_cmp_um * 1.0e-4
    idx_amb = ls.materials.index("ambient")
    owner = ls.material_map()
    owner = np.where(ls.Y < y_cmp, idx_amb, owner)
    return _project_from_owner3d(ls, owner)


def _require_skimage():
    try:
        from skimage import measure  # noqa: F401
        return measure
    except ImportError as exc:
        raise ImportError(
            "this feature requires the optional 'scikit-image' package "
            f"(pip install scikit-image): {exc}") from exc


def marching_cubes_surface(ls, materials, level=0.0):
    """A real triangulated isosurface at `phi=level` (default 0) via
    `skimage.measure.marching_cubes` -- a genuinely continuous/smooth
    surface (piecewise-LINEAR at the grid's own resolution, not
    piecewise-CONSTANT/staircase the way `gmsh_finfet3d.py`'s 2D-
    extrusion path is), used as the basis for `levelset3d_mesh.py`'s
    direct tet meshing.

    `materials`: a single material name, OR a list/tuple of names, in
    which case the UNION's boundary is extracted via the standard
    level-set CSG identity phi_union = min_i(phi_i) -- a point is
    inside the union iff it is inside ANY listed material, and taking
    the elementwise min of already-valid local signed distances gives
    the correct SIGN (hence correct isosurface topology/location)
    everywhere, even though it is not the exact geodesic distance
    beyond the boundary (which marching_cubes never queries anyway).
    This reuses each material's own already-validated signed-distance
    field with no new geometry math -- the same trick
    `levelset3d.LevelSet3D.material_map`'s argmin ownership relies on,
    one level up.

    Returns (verts, faces): `verts` is `(V,3)` float in `ls`'s own
    physical (x,y,z) units [cm] (marching_cubes itself works in VOXEL-
    INDEX space; this function applies the affine map back to physical
    coordinates using `ls.dx/dy/dz` and `ls.x0/y0/z0`, so a caller never
    sees index space). `faces` is `(F,3)` int, 0-based indices into
    `verts`.

    Raises ValueError if the (unioned) phi never crosses `level`
    anywhere in the grid (marching_cubes itself raises a less legible
    error in that case -- checked explicitly here for a clear message).
    ImportError if `scikit-image` is not installed (an optional
    dependency, following this repo's existing devsim/gmsh/pyvista
    pattern -- see CLAUDE.md's "Optional deps stay optional" rule)."""
    measure = _require_skimage()
    names = [materials] if isinstance(materials, str) else list(materials)
    for name in names:
        if name not in ls.materials:
            raise ValueError(f"{name!r} not in this level set's materials {ls.materials}")
    phi = np.min(np.stack([ls.phi[name] for name in names], axis=0), axis=0)
    if phi.min() >= level or phi.max() <= level:
        raise ValueError(
            f"{names!r}'s (unioned) phi never crosses level={level} "
            f"(min={phi.min():.3e}, max={phi.max():.3e}) -- nothing to extract"
        )
    verts_idx, faces, _normals, _values = measure.marching_cubes(phi, level=level)
    verts = np.empty_like(verts_idx)
    verts[:, 0] = ls.x0 + verts_idx[:, 0] * ls.dx
    verts[:, 1] = ls.y0 + verts_idx[:, 1] * ls.dy
    verts[:, 2] = ls.z0 + verts_idx[:, 2] * ls.dz
    return verts, faces
