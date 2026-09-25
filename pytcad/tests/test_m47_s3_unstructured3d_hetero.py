"""M47 Slice 3 -- heterojunctions in the unstructured 3D core
(`unstructured_dd3d.py`), a PORT of `unstructured_dd.py`'s 2D mechanism
(`materials_per_node` + `band_offset`), not new physics.

What the port adds, exactly as 2D has it:
  * per-node intrinsic density nie(material) -- SRH and the ohmic
    contact values use it node by node;
  * the Anderson band-offset edge term dlnnie = ln(nie_j/nie_i), ADDED
    to the electron SG argument and SUBTRACTED from the hole one
    (CLAUDE.md gotcha: a shared sign passes an FD-Jacobian check but
    breaks hole detailed balance -- gate G2 below is the one that
    catches it);
  * band_offset="affinity": one per-node shift s = ln(Nc/nie) + chi/VT,
    referenced to node 0, the SAME sign for both carriers, identically
    zero for a homojunction;
  * per-node mobility from each node's material.
Stated limits carried over from 2D unchanged: eps and SRH lifetimes
come from the reference `material`, not per node.

Gates:
  G1  default / uniform materials_per_node / explicit gauges are
      bit-identical to the pre-Slice-3 homojunction solve (bias and
      equilibrium entry points).
  G2  per-carrier equilibrium detailed balance on a real
      heterojunction, both gauges: each carrier's quasi-Fermi level is
      flat.
  G3  FD-Jacobian of the Python oracle with nonzero dlnnie AND ds.
  G4  compiled kernel == Python oracle, np.array_equal, with per-node
      nie and separate hole Bernoulli arrays.
  G5  built-in potential matches the Anderson rule.
  G6  equilibrium3d and a zero-bias solve_bias3d agree on the hetero
      junction.
  G7  (slow) forward current matches the structured Device3D
      heterojunction on the same geometry, same tolerance band as the
      existing homojunction comparison.
  G8  refusals: bad band_offset, wrong-length materials_per_node.
  G9  doping_mobility=True's per-material Caughey-Thomas branch is exact
      for physically identical materials, and a lower-mobility half
      lowers the current on both mobility branches.
  G10 gated hetero device: equilibrium3d and zero-bias solve_bias3d
      agree (the gate reference potential is written once per entry
      point), and the gate visibly moves the surface potential.
  G11 init= warm start from the converged hetero state is a fixed point.
  G12 return_diagnostics on a hetero solve: shape, finiteness, decay.
"""
import dataclasses
import warnings

import numpy as np
import pytest

gmsh = pytest.importorskip("gmsh")

from pytcad import _accel
from pytcad.gmsh_mesh3d import build_diode_mesh3d
from pytcad.materials import SILICON
from pytcad.unstructured_assembly3d import (
    build_unstructured_stencil3d, build_edge_flux_geometry3d)
from pytcad import unstructured_dd3d as u3
from pytcad.unstructured_dd3d import (
    evaluate_doping_at_nodes3d, solve_poisson_equilibrium3d, solve_bias3d)

warnings.simplefilter("ignore")

XJ = 1.0e-4
# Same eps_r/mobility/lifetimes as silicon, wider gap -> lower nie.
WIDE = dataclasses.replace(SILICON, name="Si-wide-gap", Eg0=SILICON.Eg0 + 0.12)
DOPING = {"p_region": -1e17, "n_region": 1e17}


@pytest.fixture(scope="module")
def geom():
    mesh = build_diode_mesh3d(Lx=2.0e-4, Ly=5.0e-5, Lz=3.0e-5, Xj=XJ,
                              Nd_scale=1e17)
    edge_list, node_vols = build_unstructured_stencil3d(mesh.nodes, mesh.tets)
    edges, trans = build_edge_flux_geometry3d(mesh.nodes, mesh.tets, edge_list)
    region_of_tet = np.empty(mesh.n_tets(), dtype=object)
    for name, idx in mesh.volume_tags.items():
        region_of_tet[idx] = name
    C = evaluate_doping_at_nodes3d(mesh.nodes, mesh.tets, region_of_tet, DOPING)
    contacts = {"left_contact": mesh.face_tags["left_contact"],
                "right_contact": mesh.face_tags["right_contact"]}
    return dict(mesh=mesh, edges=edges, vols=node_vols, trans=trans, C=C,
                contacts=contacts)


def _split(g, right):
    """Silicon for x < Xj, `right` for x >= Xj, per node."""
    x = g["mesh"].nodes[:, 0]
    return np.array([SILICON if xi < XJ else right for xi in x], dtype=object)


def _bias(g, bias, **kw):
    return solve_bias3d(g["mesh"].nodes, g["mesh"].tets, g["edges"], g["vols"],
                        g["trans"], g["C"], g["contacts"], bias, **kw)


def _eq(g, **kw):
    return solve_poisson_equilibrium3d(g["mesh"].nodes, g["mesh"].tets,
                                       g["edges"], g["vols"], g["trans"],
                                       g["C"], g["contacts"], **kw)


# ---------------------------------------------------------------- G1
def test_g1_bias_default_uniform_and_gauges_bit_identical(geom):
    N = geom["C"].shape[0]
    ref = _bias(geom, {"left_contact": 0.3})
    variants = [
        dict(materials_per_node=np.array([SILICON] * N, dtype=object)),
        dict(band_offset="nie"),
        dict(band_offset="affinity"),
        dict(materials_per_node=np.array([SILICON] * N, dtype=object),
             band_offset="affinity"),
    ]
    for kw in variants:
        out = _bias(geom, {"left_contact": 0.3}, **kw)
        for a, b in zip(ref[:3], out[:3]):
            assert np.array_equal(a, b), kw
        assert ref[4] == out[4], kw


def test_g1_equilibrium_default_uniform_and_gauges_bit_identical(geom):
    N = geom["C"].shape[0]
    ref, _ = _eq(geom)
    for kw in (dict(materials_per_node=np.array([SILICON] * N, dtype=object)),
               dict(band_offset="nie"), dict(band_offset="affinity")):
        psi, _ = _eq(geom, **kw)
        assert np.array_equal(ref, psi), kw


# ---------------------------------------------------------------- G2
def _hetero_case(band_offset):
    """nie gauge: a band-GAP step (dlnnie != 0). affinity gauge: an
    affinity step on top of it (ds != 0 too)."""
    if band_offset == "nie":
        return WIDE
    return dataclasses.replace(WIDE, chi=SILICON.chi - 0.2)


@pytest.mark.parametrize("band_offset", ["nie", "affinity"])
def test_g2_equilibrium_detailed_balance_per_carrier(geom, band_offset):
    """At V=0 each carrier's SG edge current vanishes iff its
    quasi-Fermi level is flat:
        electron: ln(n/nie) - (psi + s)  constant,
        hole:     ln(p/nie) + (psi + s)  constant,
    with s the affinity-gauge band shift (0 on "nie"). A hole term with
    the electron's dlnnie sign fails the hole line, not the electron one."""
    right = _hetero_case(band_offset)
    mats = _split(geom, right)
    psi, n, p, scale, I = _bias(geom, {}, materials_per_node=mats,
                                band_offset=band_offset)
    assert scale["last_converged"]
    f = u3._material_fields3d(mats, 300.0, scale["VT"], scale["Ns"],
                              geom["edges"], band_offset)
    s = f["band_shift"]
    phi_n = np.log(n / f["nie_s"]) - (psi + s)
    phi_p = np.log(p / f["nie_s"]) + (psi + s)
    assert np.ptp(phi_n) < 1e-6, f"electron quasi-Fermi spread {np.ptp(phi_n):.3e}"
    assert np.ptp(phi_p) < 1e-6, f"hole quasi-Fermi spread {np.ptp(phi_p):.3e}"
    # and the band offset is real: dlnnie is nonzero on interface edges
    assert np.abs(f["dlnnie"]).max() > 1.0


# ---------------------------------------------------------------- G3/G4
def _coupled_state(g, band_offset, seed=0):
    """A converged forward-biased hetero state, slightly perturbed, plus
    every argument the coupled residual needs."""
    right = _hetero_case(band_offset)
    mats = _split(g, right)
    psi, n, p, scale, _ = _bias(g, {"left_contact": 0.3},
                                materials_per_node=mats, band_offset=band_offset)
    f = u3._material_fields3d(mats, 300.0, scale["VT"], scale["Ns"],
                              g["edges"], band_offset)
    rng = np.random.default_rng(seed)
    N = psi.shape[0]
    psi = psi + 0.02 * rng.standard_normal(N)
    n = n * (1 + 0.02 * rng.standard_normal(N))
    p = p * (1 + 0.02 * rng.standard_normal(N))
    VT, Ns, LD = scale["VT"], scale["Ns"], scale["LD"]
    from pytcad.device import D0_REF
    i_e, j_e = g["edges"][:, 0], g["edges"][:, 1]
    hm = lambda a, b: 2.0 * a * b / (a + b)
    kw = dict(C_s=g["C"] / Ns, nie_s=f["nie_s"], node_vols_s=g["vols"] / LD ** 3,
              edges=g["edges"], eps_trans=g["trans"] / LD,
              D_n_s=hm(f["mu_n"][i_e], f["mu_n"][j_e]) * VT / D0_REF,
              D_p_s=hm(f["mu_p"][i_e], f["mu_p"][j_e]) * VT / D0_REF,
              R0=scale["R0"], tau_n=np.full(N, SILICON.tau_n0),
              tau_p=np.full(N, SILICON.tau_p0), material=SILICON, Ns=Ns, LD=LD,
              srh=True, auger=True, dlnnie=f["dlnnie"], ds=f["ds_edge"])
    return psi, n, p, kw, f


@pytest.mark.parametrize("band_offset", ["nie", "affinity"])
def test_g3_fd_jacobian_with_band_offsets(geom, band_offset):
    psi, n, p, kw, f = _coupled_state(geom, band_offset)
    N = psi.shape[0]
    x0 = np.column_stack([psi, n, p]).ravel()

    def F_of(x):
        x3 = x.reshape(N, 3)
        return u3._residual_jacobian_dd3d_py(x3[:, 0], x3[:, 1], x3[:, 2], **kw)[0]

    _, J, _, _ = u3._residual_jacobian_dd3d_py(psi, n, p, **kw)
    J = J.tocsc()
    # Every column of every node on an interface edge (not a random
    # sample). Step and threshold are the in-tree M47 FD gate's own
    # (tests/test_m47_s1_unstructured3d_fd_jacobian.py): the n/p columns
    # carry O(1e-6..1e-5) finite-difference noise even on a homojunction
    # (measured 2026-09-24), so a tighter bound would gate FD truncation,
    # not the Jacobian. The hetero SIGN error an FD check cannot see is
    # G2's job.
    iface = np.unique(geom["edges"][np.abs(f["dlnnie"]) > 0].ravel())
    assert iface.size > 0
    F0 = F_of(x0)
    worst = 0.0
    for node in iface:
        for comp in range(3):
            k = 3 * node + comp
            h = 1e-7 * max(abs(x0[k]), 1.0)
            xp = x0.copy()
            xp[k] += h
            fd = (F_of(xp) - F0) / h
            an = J[:, k].toarray().ravel()
            worst = max(worst, np.abs(fd - an).max() / (np.abs(an).max() + 1e-30))
    assert worst < 1e-3, f"worst FD-vs-analytic column error {worst:.3e}"


@pytest.mark.skipif(not _accel.HAVE_ACCEL, reason="compiled extension not built")
@pytest.mark.parametrize("band_offset", ["nie", "affinity"])
def test_g4_compiled_kernel_matches_oracle_with_band_offsets(geom, band_offset):
    psi, n, p, kw, _ = _coupled_state(geom, band_offset, seed=1)
    F_py, J_py, Jn_py, Jp_py = u3._residual_jacobian_dd3d_py(psi, n, p, **kw)
    F_c, J_c, Jn_c, Jp_c = u3._residual_jacobian_dd3d(psi, n, p, **kw)
    assert np.array_equal(F_py, F_c)
    assert np.array_equal(Jn_py, Jn_c)
    assert np.array_equal(Jp_py, Jp_c)
    a, b = J_py.tocsc(), J_c.tocsc()
    assert np.array_equal(a.indptr, b.indptr)
    assert np.array_equal(a.indices, b.indices)
    assert np.array_equal(a.data, b.data)


# ---------------------------------------------------------------- G5/G6
def _bulk(g, psi):
    x = g["mesh"].nodes[:, 0]
    return (psi[(x > 0.2e-4) & (x < 0.6e-4)].mean(),
            psi[(x > 1.4e-4) & (x < 1.8e-4)].mean())


def test_g5_builtin_potential_matches_anderson_rule(geom):
    mats = _split(geom, WIDE)
    psi, n, p, scale, _ = _bias(geom, {}, materials_per_node=mats)
    assert scale["last_converged"]
    p_bulk, n_bulk = _bulk(geom, psi)
    analytic = (np.arcsinh(1e17 / (2 * WIDE.ni(300.0)))
                - np.arcsinh(-1e17 / (2 * SILICON.ni(300.0))))
    rel = abs((n_bulk - p_bulk) - analytic) / abs(analytic)
    assert rel < 0.05, f"psi_bi {n_bulk - p_bulk:.4f} vs {analytic:.4f} VT"


@pytest.mark.parametrize("band_offset", ["nie", "affinity"])
def test_g6_equilibrium3d_agrees_with_zero_bias_solve(geom, band_offset):
    mats = _split(geom, _hetero_case(band_offset))
    psi_eq, _ = _eq(geom, materials_per_node=mats, band_offset=band_offset)
    psi_b, *_ = _bias(geom, {}, materials_per_node=mats, band_offset=band_offset)
    assert np.abs(psi_eq - psi_b).max() < 1e-4


# ---------------------------------------------------------------- G7
@pytest.mark.slow
def test_g7_forward_current_matches_structured_device3d_hetero(geom):
    from pytcad.mesh import graded_mesh
    from pytcad.mesh3d import Mesh3D
    from pytcad.device3d import Device3D
    from pytcad.device import Models

    V = 0.5
    mats = _split(geom, WIDE)
    _, _, _, scale, I = _bias(geom, {"left_contact": V}, materials_per_node=mats)
    assert scale["last_converged"]

    x = graded_mesh(2.0e-4, [XJ], 5e-7, 6e-6, 1.2)
    y = graded_mesh(5.0e-5, [0.0], 2e-6, 8e-6, 1.2)
    z = graded_mesh(3.0e-5, [0.0], 2e-6, 8e-6, 1.2)
    dop3d = np.tile(np.where(x < XJ, -1e17, 1e17), (z.size, y.size, 1))
    mats3 = [SILICON if xi < XJ else WIDE
             for _k in range(z.size) for _j in range(y.size) for xi in x]
    mesh3 = Mesh3D(x, y, z)
    dev = Device3D(mesh3, dop3d, material=mats3,
                   models=Models(bgn=False, doping_mobility=False, srh=True))
    jj, kk = np.meshgrid(np.arange(mesh3.Ny), np.arange(mesh3.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk)
    dev.add_contact("right", i=np.full_like(jj, mesh3.Nx - 1), j=jj, k=kk)
    dev.solve_equilibrium()
    dev.solve_bias({"left": V, "right": 0.0})
    I_s = dev.terminal_current("left")
    rel = abs(I["left_contact"] - I_s) / abs(I_s)
    # Same independent-discretization band the homojunction comparison in
    # tests/test_unstructured_dd3d.py established (~20-25%).
    assert rel < 0.30, f"unstructured {I['left_contact']:.4e} vs structured {I_s:.4e}"
    assert I["left_contact"] * I_s > 0


# ---------------------------------------------------------------- G8
def test_g8_refusals(geom):
    with pytest.raises(ValueError, match="band_offset"):
        _bias(geom, {}, band_offset="bogus")
    with pytest.raises(ValueError, match="band_offset"):
        _eq(geom, band_offset="bogus")
    with pytest.raises(ValueError, match="materials_per_node"):
        _bias(geom, {}, materials_per_node=np.array([SILICON] * 3, dtype=object))


# =======================================================================
# Coverage added 2026-09-24 for paths Slice 3 touched that G1-G8 did not
# exercise: per-material doping mobility, gates, warm start, diagnostics.
# =======================================================================
# Same physics as SILICON, a distinct object: exercises every
# per-material branch while the answer must not move.
SI_CLONE = dataclasses.replace(SILICON, name="Si-clone")
# Silicon with lower electron/hole mobility ceilings, same nie: a pure
# mobility heterostructure (dlnnie == 0).
SI_SLOW = dataclasses.replace(SILICON, name="Si-slow-mu",
                              mu_n_max=SILICON.mu_n_max / 4,
                              mu_p_max=SILICON.mu_p_max / 4)


def _ntot(g):
    return np.abs(g["C"])


# ---------------------------------------------------------------- G9
def test_g9_doping_mobility_per_material_branch_is_exact_for_clones(geom):
    """doping_mobility=True with materials_per_node runs the
    per-material-group Caughey-Thomas loop; with physically identical
    materials it must reproduce the single-material call bit-for-bit."""
    kw = dict(doping_mobility=True, Ntot_phys=_ntot(geom))
    ref = _bias(geom, {"left_contact": 0.4}, **kw)
    out = _bias(geom, {"left_contact": 0.4}, materials_per_node=_split(geom, SI_CLONE), **kw)
    for a, b in zip(ref[:3], out[:3]):
        assert np.array_equal(a, b)
    assert ref[4] == out[4]


@pytest.mark.parametrize("doping_mobility", [False, True])
def test_g9_per_node_mobility_actually_reaches_the_current(geom, doping_mobility):
    """A slower-mobility right half must LOWER the forward current, on
    both the constant-mobility and Caughey-Thomas branches -- proof the
    per-node mobility is used, not the reference material's."""
    kw = dict(doping_mobility=doping_mobility,
              Ntot_phys=_ntot(geom) if doping_mobility else None)
    I_si = _bias(geom, {"left_contact": 0.5}, **kw)[4]["left_contact"]
    I_slow = _bias(geom, {"left_contact": 0.5},
                   materials_per_node=_split(geom, SI_SLOW), **kw)[4]["left_contact"]
    assert I_si * I_slow > 0
    assert abs(I_slow) < 0.9 * abs(I_si), (I_si, I_slow)


# ---------------------------------------------------------------- G10
def _boundary_faces_y0(mesh):
    """Boundary triangles lying in the y = 0 plane (spans the junction)."""
    counts = {}
    for t in mesh.tets:
        for f in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)):
            key = tuple(sorted(int(t[i]) for i in f))
            counts[key] = counts.get(key, 0) + 1
    y = mesh.nodes[:, 1]
    faces = [k for k, c in counts.items() if c == 1 and np.all(np.abs(y[list(k)]) < 1e-12)]
    return np.array(faces, dtype=np.int64)


@pytest.fixture(scope="module")
def gate(geom):
    faces = _boundary_faces_y0(geom["mesh"])
    assert len(faces) > 0
    return faces


def _gates(faces, Vg):
    return {"g": {"faces": faces, "tox_cm": 5e-7, "Vfb": 0.0, "Vg": Vg}}


@pytest.mark.parametrize("band_offset", ["nie", "affinity"])
def test_g10_gated_hetero_equilibrium_agrees_between_entry_points(geom, gate, band_offset):
    """The gate's reference potential (per-node nie, -band_shift) is
    written twice, once per entry point. At zero bias the two solves
    must agree -- a mistake in either copy breaks this."""
    mats = _split(geom, _hetero_case(band_offset))
    g = _gates(gate, 0.3)
    psi_eq, _ = _eq(geom, materials_per_node=mats, band_offset=band_offset, gates=g)
    psi_b, *_ = _bias(geom, {}, materials_per_node=mats, band_offset=band_offset, gates=g)
    assert np.abs(psi_eq - psi_b).max() < 1e-4


def test_g10_gate_moves_a_hetero_solution(geom, gate):
    mats = _split(geom, WIDE)
    lo = _bias(geom, {}, materials_per_node=mats, gates=_gates(gate, -0.5))[0]
    hi = _bias(geom, {}, materials_per_node=mats, gates=_gates(gate, +0.5))[0]
    y = geom["mesh"].nodes[:, 1]
    surf = np.abs(y) < 1e-12
    assert (hi[surf] - lo[surf]).mean() > 1.0   # scaled psi, i.e. > 1 VT


# ---------------------------------------------------------------- G11
@pytest.mark.parametrize("band_offset", ["nie", "affinity"])
def test_g11_warm_start_from_own_solution_is_a_fixed_point(geom, band_offset):
    """init= with the converged hetero state must stay put and converge
    at once -- catches an init path that re-applies band_shift or uses
    the wrong nie."""
    mats = _split(geom, _hetero_case(band_offset))
    bias = {"left_contact": 0.3}
    psi, n, p, sc, I = _bias(geom, bias, materials_per_node=mats, band_offset=band_offset)
    out = _bias(geom, bias, materials_per_node=mats, band_offset=band_offset,
                init=dict(psi=psi, n=n, p=p), return_diagnostics=True)
    psi2, n2, p2, sc2, I2, diag = out
    assert sc2["last_converged"]
    assert diag["n_iter"] <= 2
    assert np.abs(psi2 - psi).max() < 1e-8
    assert np.abs(n2 / n - 1).max() < 1e-8
    assert np.abs(p2 / p - 1).max() < 1e-8


# ---------------------------------------------------------------- G12
def test_g12_diagnostics_shape_and_decay_on_a_hetero_solve(geom):
    mats = _split(geom, WIDE)
    *_, diag = _bias(geom, {"left_contact": 0.3}, materials_per_node=mats,
                     return_diagnostics=True)
    hist = diag["residual_node_history"]
    assert hist.shape == (diag["n_iter"], geom["C"].shape[0])
    assert np.all(np.isfinite(hist))
    assert hist[-1].max() < hist[0].max()
