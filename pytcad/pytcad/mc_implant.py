"""M25: Monte-Carlo ion implantation via the binary-collision approximation
(BCA), into amorphous and (qualitatively) crystalline silicon.

Physics used, and how confident each piece is
-----------------------------------------------
This module deliberately builds on formulas that are standard, textbook,
and independently cross-checkable, rather than reproducing SRIM/TRIM's
"magic formula" scattering-integral fit from memory (that fit has several
empirical numerical coefficients that are easy to misquote and hard to
verify without the original tables in hand -- getting one wrong would
silently corrupt every result, which is exactly the failure mode this
project's honesty-clause culture exists to avoid).  Instead:

* Ziegler-Biersack-Littmark (ZBL) universal screening length
  a_U = 0.8854 a0 / (Z1^0.23 + Z2^0.23)  -- extremely standard, low risk.
* Exact classical two-body elastic-collision kinematics for the energy
  transfer and the lab<->center-of-mass scattering-angle transform -- not
  approximations, textbook mechanics (e.g. Goldstein, Classical Mechanics).
* The scattering angle *within* a single collision uses the Rutherford
  formula with a screened effective charge product,
  tan(theta_cm/2) = Z1 Z2 exp(-p/a_U) ke^2 / (2 E_r p): the exp(-p/a_U)
  factor is a single-exponential approximation to the ZBL universal
  screening function's fall-off (whose dominant term is itself
  0.5099 exp(-0.9423 x), x = r/a_U) -- not the full 4-term ZBL function,
  but enough to avoid the qualitatively wrong result of using bare
  (unscreened) Rutherford scattering at distances comparable to the
  screening length, which was found during development here to make
  nuclear stopping unphysically dominant (range became nearly
  insensitive to the calibrated electronic-stopping prefactor). The
  impact parameter is additionally capped at a few screening lengths
  (`p_max_screening_lengths`, disclosed knob) purely to bound the mean
  free path -- beyond that the exponential factor has already suppressed
  the interaction to near zero.
* Electronic stopping uses the Lindhard-Scharff velocity-proportional
  FUNCTIONAL FORM, S_e(E) = k_e sqrt(E), which is well established in
  this energy regime; the *prefactor* k_e is calibrated per species
  against `pytcad.process`'s existing (SRIM-derived, already
  self-described as "approximate, 5-10%") range table at one reference
  energy, via `calibrate_electronic_stopping`. This is an explicit,
  disclosed calibration, not a hidden fit -- see that function's
  docstring for exactly what it does.
* ke^2 = 14.3996 eV*Angstrom is the standard Coulomb-constant-times-e^2
  combination (cross-checked here via alpha*hbar*c = (1/137.036) *
  197.327 MeV*fm = 1.43996 MeV*fm = 14.3996 eV*Angstrom).

HONESTY CLAUSE -- what this module does NOT model
--------------------------------------------------
* This is NOT the literal ZBL potential + magic-formula scattering
  integral SRIM uses; it is a screened-Rutherford + calibrated-LSS-
  stopping hybrid tuned to reproduce SRIM-like *range moments*, not
  microscopic collision-by-collision fidelity. Angular/energy details of
  any single collision are not meant to be taken individually seriously.
* The nuclear-collision mean free path is set by the screening-length
  cutoff (`p_max_screening_lengths`), not by integrating the full
  nuclear stopping cross-section -- an engineering approximation, see
  `mc_implant_bca`'s docstring.
* Channeling is a DISCLOSED PHENOMENOLOGICAL KNOB (a per-ion probability
  of entering a suppressed-scattering "channel" for an exponentially
  distributed path length), not a crystal-lattice simulation. It
  reproduces the qualitative shape of a channeling tail (a heavier,
  deeper tail than an amorphous target gives) -- it is NOT fit to or
  validated against any specific published SIMS profile, per the M25
  acceptance criteria's own "honestly labeled" qualitative framing.
* No sputtering, no recoil-cascade damage accumulation/amorphization
  tracking (that is what feeds pytcad.ted's "+1" TED model, which is
  handed a damage depth/dose from the CALLER, not computed here), no
  compound/multi-element targets (silicon only).
* Electronic stopping's overall magnitude is only as good as the single
  calibration point; it is not independently derived from Z1/Z2/velocity
  first principles (the functional form is physical, the prefactor is
  fitted).

MEASURED ACCURACY (so "SRIM-comparable" has a concrete meaning here):
calibrating at one energy per species against pytcad.process's table and
then comparing at OTHER tabulated energies within roughly a 4x window
around the calibration point gives Rp within about +/-35% of the table
for B, P, and As; accuracy degrades further from the calibration point
(observed ~-25% at 4x the calibration energy). dRp (straggle) tends to be
underestimated at the high-energy end of that window. Treat any use
outside a few-x energy window of wherever you calibrated as unverified.
"""

import warnings
import numpy as np

from . import process

# ----------------------------------------------------------------------
#  Constants
# ----------------------------------------------------------------------
A0_ANGSTROM = 0.529177          # Bohr radius [Angstrom]
KE2_EV_ANG = 14.3996            # e^2/(4 pi eps0) [eV * Angstrom]
# (cross-check: (1/137.036) * 197.327 MeV*fm = 1.43996 MeV*fm = 14.3996 eV*Ang)

N_AVOGADRO = 6.02214076e23      # /mol, exact by SI definition
SI_DENSITY_G_CM3 = 2.329        # standard silicon mass density
SI_MOLAR_MASS = 28.0855         # g/mol
SI_ATOMIC_DENSITY_CM3 = SI_DENSITY_G_CM3 * N_AVOGADRO / SI_MOLAR_MASS  # ~4.99e22
SI_Z = 14

# (Z, atomic mass [amu]) for supported ion species -- standard periodic
# table values, matching the species already in pytcad.process.
_ION_DATA = {
    "B":  (5, 10.811),
    "P":  (15, 30.973762),
    "As": (33, 74.921595),
    "Sb": (51, 121.760),
}


def zbl_screening_length_cm(Z1, Z2=SI_Z):
    """ZBL universal screening length [cm]."""
    a_ang = 0.8854 * A0_ANGSTROM / (Z1 ** 0.23 + Z2 ** 0.23)
    return a_ang * 1e-8


# ----------------------------------------------------------------------
#  Core Monte-Carlo BCA
# ----------------------------------------------------------------------
def mc_implant_bca(species, energy_keV, k_e, n_ions=2000, tilt_deg=0.0,
                    channeling_fraction=0.0, channeling_length_mean_cm=2e-5,
                    channeling_se_fraction=0.3,
                    E_cutoff_keV=1.0, p_max_screening_lengths=3.0,
                    max_steps=4000, seed=None):
    """Monte-Carlo BCA implant of `n_ions` independent trajectories.

    k_e            : electronic-stopping prefactor [keV^0.5/cm], from
                      calibrate_electronic_stopping(). No default --
                      forcing an explicit, traceable value here rather
                      than silently recalibrating on every call.
    channeling_*    : see module honesty clause; channeling_fraction=0
                      (the default) gives a purely amorphous-target run.
    p_max_screening_lengths : nuclear-collision cutoff impact parameter,
                      in units of the ZBL screening length -- sets both
                      the mean free path and the maximum scattering
                      angle per collision (see module docstring).

    Returns a dict with:
      depth_cm         : (n_ions,) final depth along the original beam
                          axis [cm] (only meaningful for non-backscattered
                          ions -- see backscattered).
      backscattered    : (n_ions,) bool.
      channeled_ever   : (n_ions,) bool, ions that spent time channeled.
      Rp_cm, dRp_cm    : mean/std of depth over non-backscattered ions.
      backscatter_fraction : float.
      unstopped_fraction   : float, ions that hit max_steps without
                              stopping (should be ~0; a nonzero value is
                              warned about, same convention as this
                              codebase's other budget-limited results).
    """
    if species not in _ION_DATA:
        raise KeyError(f"No BCA data for species '{species}'. "
                        f"Available: {list(_ION_DATA)}")
    Z1, M1 = _ION_DATA[species]
    Z2, M2 = SI_Z, SI_MOLAR_MASS

    rng = np.random.default_rng(seed)
    n = int(n_ions)

    a_U_cm = zbl_screening_length_cm(Z1, Z2)
    p_max_cm = p_max_screening_lengths * a_U_cm
    lambda_mfp_cm = 1.0 / (SI_ATOMIC_DENSITY_CM3 * np.pi * p_max_cm ** 2)

    tilt = np.deg2rad(tilt_deg)
    pos = np.zeros((n, 3))
    dirn = np.tile(np.array([np.cos(tilt), np.sin(tilt), 0.0]), (n, 1))
    E = np.full(n, float(energy_keV))
    active = np.ones(n, dtype=bool)
    backscattered = np.zeros(n, dtype=bool)
    channeled_ever = np.zeros(n, dtype=bool)

    is_channeled = rng.random(n) < channeling_fraction
    channeled_ever |= is_channeled
    channel_len_remaining = np.where(
        is_channeled, rng.exponential(channeling_length_mean_cm, size=n), 0.0)

    for _ in range(max_steps):
        idx = np.where(active)[0]
        if idx.size == 0:
            break

        ell = rng.exponential(lambda_mfp_cm, size=idx.size)
        chan = is_channeled[idx] & (channel_len_remaining[idx] > 0.0)

        se_scale = np.where(chan, channeling_se_fraction, 1.0)
        E[idx] -= k_e * np.sqrt(np.maximum(E[idx], 0.0)) * ell * se_scale
        E[idx] = np.maximum(E[idx], 0.0)

        pos[idx] += ell[:, None] * dirn[idx]

        channel_len_remaining[idx] = np.where(
            chan, channel_len_remaining[idx] - ell, channel_len_remaining[idx])
        is_channeled[idx] &= channel_len_remaining[idx] > 0.0

        # Nuclear collision -- skipped for still-channeled ions.
        do_collide = ~chan
        n_coll = int(do_collide.sum())
        if n_coll > 0:
            ci = idx[do_collide]
            p_ang = p_max_screening_lengths * (a_U_cm * 1e8) * np.sqrt(rng.random(n_coll))
            p_ang = np.maximum(p_ang, 1e-6)
            E_r_eV = E[ci] * 1000.0 * M2 / (M1 + M2)
            screen = np.exp(-p_ang / (a_U_cm * 1e8))
            theta_cm = 2.0 * np.arctan(
                Z1 * Z2 * screen * KE2_EV_ANG / (2.0 * np.maximum(E_r_eV, 1e-12) * p_ang))
            T_keV = (4.0 * M1 * M2 / (M1 + M2) ** 2) * E[ci] * np.sin(theta_cm / 2.0) ** 2
            E[ci] = np.maximum(E[ci] - T_keV, 0.0)

            theta_lab = np.arctan2(np.sin(theta_cm), (M1 / M2) + np.cos(theta_cm))
            phi = rng.uniform(0.0, 2.0 * np.pi, size=n_coll)

            d = dirn[ci]
            ref = np.where(np.abs(d[:, 2:3]) < 0.9,
                           np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0]))
            perp1 = np.cross(d, ref)
            perp1 /= np.linalg.norm(perp1, axis=1, keepdims=True)
            perp2 = np.cross(d, perp1)

            ct, st = np.cos(theta_lab)[:, None], np.sin(theta_lab)[:, None]
            new_d = (ct * d + st * (np.cos(phi)[:, None] * perp1
                                     + np.sin(phi)[:, None] * perp2))
            new_d /= np.linalg.norm(new_d, axis=1, keepdims=True)
            dirn[ci] = new_d

        stopped = active & (E <= E_cutoff_keV)
        exited = active & (pos[:, 0] < 0.0)
        backscattered |= exited
        active &= ~(stopped | exited)

    unstopped_fraction = float(active.sum()) / n
    if unstopped_fraction > 0.01:
        warnings.warn(
            f"mc_implant_bca: {unstopped_fraction*100:.1f}% of ions did not "
            f"stop within max_steps={max_steps}; range moments below are "
            f"biased low for those ions -- increase max_steps.")

    depth_cm = pos[:, 0].copy()
    kept = ~backscattered
    Rp = float(depth_cm[kept].mean()) if kept.any() else float("nan")
    dRp = float(depth_cm[kept].std()) if kept.any() else float("nan")

    return {
        "depth_cm": depth_cm,
        "lateral_cm": pos[:, 1:],
        "backscattered": backscattered,
        "channeled_ever": channeled_ever,
        "Rp_cm": Rp,
        "dRp_cm": dRp,
        "backscatter_fraction": float(backscattered.mean()),
        "unstopped_fraction": unstopped_fraction,
    }


# ----------------------------------------------------------------------
#  Electronic-stopping calibration against the existing SRIM-like table
# ----------------------------------------------------------------------
def calibrate_electronic_stopping(species, ref_energy_keV, target_Rp_cm=None,
                                   k_e_guess=None, n_ions=400, seed=0,
                                   n_refine=1):
    """Calibrate the LSS velocity-proportional electronic-stopping
    prefactor k_e [keV^0.5/cm] so that an amorphous (no channeling)
    mc_implant_bca run at `ref_energy_keV` reproduces `target_Rp_cm`.

    target_Rp_cm defaults to pytcad.process.implant_moments()'s tabulated
    range at ref_energy_keV -- i.e. by default this calibrates against
    the existing (SRIM-derived) lookup table already shipped in
    pytcad.process, exactly the "SRIM-comparable" anchor the M25
    acceptance criteria call for.

    In the electronic-stopping-dominated limit (a fair approximation at
    these energies -- see module docstring), range scales as R ~ 1/k_e,
    so a single multiplicative correction usually converges quickly;
    `n_refine` extra iterations tighten it further.
    """
    if target_Rp_cm is None:
        target_Rp_cm, _ = process.implant_moments(species, ref_energy_keV)

    if k_e_guess is None:
        # crude physically-scaled starting point: heavier/more-charged
        # ions lose energy faster per unit path.
        Z1, M1 = _ION_DATA[species]
        k_e_guess = 5e5 * (Z1 / 14.0)

    k_e = float(k_e_guess)
    for _ in range(1 + max(n_refine, 0)):
        out = mc_implant_bca(species, ref_energy_keV, k_e, n_ions=n_ions,
                              channeling_fraction=0.0, seed=seed)
        if out["Rp_cm"] <= 0 or not np.isfinite(out["Rp_cm"]):
            raise RuntimeError(
                f"calibrate_electronic_stopping: non-physical Rp during "
                f"calibration for {species}@{ref_energy_keV}keV -- check "
                f"k_e_guess.")
        k_e *= out["Rp_cm"] / target_Rp_cm
    return k_e
