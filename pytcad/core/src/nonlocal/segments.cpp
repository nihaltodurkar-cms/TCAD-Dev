#include "tcad/nonlocal/segments.hpp"

#include <cmath>

namespace tcad::nonlocal {
namespace {

constexpr double FLAT_DDELTA = 1e-10;   // btbt.FLAT_DDELTA

// np.maximum's scalar rule: keep a if a >= b or a is NaN.
inline double np_maximum(double a, double b) {
    return (a >= b || std::isnan(a)) ? a : b;
}

// np.clip(x, 0, 1) = MIN(MAX(x, 0), 1), NaN passes through (-0.0 -> 0.0).
inline double np_clip01(double x) {
    if (std::isnan(x)) return x;
    double m = x > 0.0 ? x : 0.0;
    return m < 1.0 ? m : 1.0;
}

struct AlphaC {
    double alpha, c;
};

// btbt._kane_alpha_c. `uu` = 0.25 * u * u and `hm`/`hp` = 0.5*(u -/+ 1),
// formed once exactly as the Python scalar expressions are.
inline AlphaC alpha_c(double delta, double u, double two_u, double uu,
                      double hm, double hp) {
    const double d = np_clip01(delta);
    const double S = std::sqrt(u * (d - 0.5) + uu + 0.25);
    const double one_p = two_u * d / (S + hm);
    const double one_m = two_u * (1.0 - d) / (S + hp);
    const double alpha = d < 0.5 ? one_p - 1.0 : 1.0 - one_m;
    return {alpha, std::sqrt(one_p * one_m)};
}

}  // namespace

void segment_integrals(const double* da, const double* db, const double* L,
                       std::int64_t n, double u, double Eg_J, double mr_kg,
                       double hbar, double* Ik, double* Iik, double* dIk_da,
                       double* dIk_db, double* dIik_da, double* dIik_db) {
    const double two_u = 2.0 * u;
    const double uu = 0.25 * u * u;
    const double hm = 0.5 * (u - 1.0);
    const double hp = 0.5 * (u + 1.0);
    const double half_u = 0.5 * u;
    const double s_mE = std::sqrt(mr_kg * Eg_J);
    const double pref_K = s_mE / (2.0 * u * hbar);     // kane_kappa_antideriv
    const double pref_I = hbar / (2.0 * u * s_mE);     // kane_invkappa_antideriv
    const double neg_s_mE = -s_mE;                     // dkappa_ddelta

    for (std::int64_t s = 0; s < n; ++s) {
        const double a = da[s], b = db[s], Ls = L[s];
        const double D = std::fabs(b - a);
        const bool rising = b >= a;
        const double vmin = rising ? a : b;
        const double vmax = rising ? b : a;
        const double lo = np_clip01(vmin);
        const double hi = np_clip01(vmax);
        const bool in_lo = (vmin > 0.0) && (vmin < 1.0);
        const bool in_hi = (vmax > 0.0) && (vmax < 1.0);
        const bool flat = D < FLAT_DDELTA;
        const double Ds = flat ? 1.0 : D;

        const AlphaC ch = alpha_c(hi, u, two_u, uu, hm, hp);
        const AlphaC cl = alpha_c(lo, u, two_u, uu, hm, hp);
        const double th_h = std::atan2(ch.alpha, ch.c);
        const double th_l = std::atan2(cl.alpha, cl.c);

        const double KA_h = pref_K * (half_u * (th_h + ch.alpha * ch.c) - ch.c * ch.c * ch.c / 3.0);
        const double KA_l = pref_K * (half_u * (th_l + cl.alpha * cl.c) - cl.c * cl.c * cl.c / 3.0);
        const double IA_h = pref_I * (u * th_h - ch.c);
        const double IA_l = pref_I * (u * th_l - cl.c);
        const double dK = np_maximum(KA_h - KA_l, 0.0);
        const double dG = np_maximum(IA_h - IA_l, 0.0);

        const double k_hi = s_mE * ch.c / hbar;
        const double k_lo = s_mE * cl.c / hbar;
        const double f_hi_k = in_hi ? k_hi : 0.0;
        const double f_lo_k = in_lo ? k_lo : 0.0;
        const double f_hi_i = in_hi ? 1.0 / k_hi : 0.0;
        const double f_lo_i = in_lo ? 1.0 / k_lo : 0.0;

        const double Ik_n = Ls * dK / Ds;
        const double Iik_n = Ls * dG / Ds;
        const double dIk_max = Ls * (f_hi_k - dK / Ds) / Ds;
        const double dIk_min = Ls * (-f_lo_k + dK / Ds) / Ds;
        const double dIik_max = Ls * (f_hi_i - dG / Ds) / Ds;
        const double dIik_min = Ls * (-f_lo_i + dG / Ds) / Ds;

        if (flat) {
            // L * f(mid), derivative split equally between the ends.
            const double mid = 0.5 * (a + b);
            const bool inm = (mid > 0.0) && (mid < 1.0);
            const double mids = inm ? np_maximum(mid, 1e-30) : 0.5;
            const AlphaC cm = alpha_c(mids, u, two_u, uu, hm, hp);
            const double km = s_mE * cm.c / hbar;
            const double Sm = 0.5 * (cm.alpha + u);
            const double dkm = neg_s_mE * cm.alpha * u / (hbar * np_maximum(cm.c, 1e-300) * Sm);
            const double fl_dIk = inm ? 0.5 * Ls * dkm : 0.0;
            const double fl_dIik = inm ? -0.5 * Ls * dkm / (km * km) : 0.0;
            Ik[s] = inm ? Ls * km : 0.0;
            Iik[s] = inm ? Ls / km : 0.0;
            dIk_da[s] = fl_dIk;
            dIk_db[s] = fl_dIk;
            dIik_da[s] = fl_dIik;
            dIik_db[s] = fl_dIik;
        } else {
            Ik[s] = Ik_n;
            Iik[s] = Iik_n;
            dIk_da[s] = rising ? dIk_min : dIk_max;
            dIk_db[s] = rising ? dIk_max : dIk_min;
            dIik_da[s] = rising ? dIik_min : dIik_max;
            dIik_db[s] = rising ? dIik_max : dIik_min;
        }
    }
}

}  // namespace tcad::nonlocal
