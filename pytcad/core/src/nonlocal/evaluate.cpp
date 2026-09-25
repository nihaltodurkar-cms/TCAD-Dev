#include "tcad/nonlocal/evaluate.hpp"

#include <cmath>
#include <limits>

#include "tcad/nonlocal/segments.hpp"

namespace tcad::nonlocal {
namespace {

inline double np_minimum(double a, double b) { return (a <= b || std::isnan(a)) ? a : b; }
inline double np_maximum(double a, double b) { return (a >= b || std::isnan(a)) ? a : b; }
inline double np_clip01(double x) {
    if (std::isnan(x)) return x;
    const double m = x > 0.0 ? x : 0.0;
    return m < 1.0 ? m : 1.0;
}
inline double np_sign(double x) {
    return x > 0.0 ? 1.0 : (x < 0.0 ? -1.0 : (x == 0.0 ? 0.0 : x));
}

// np.sum(v[0..n), axis=1) for one row, as numpy reduces it.
inline double np_rowsum(const double* v, std::int64_t n) {
    if (n < 8) {
        double r = -0.0;
        for (std::int64_t i = 0; i < n; ++i) r += v[i];
        return r;
    }
    double r[8];
    for (int j = 0; j < 8; ++j) r[j] = v[j];
    std::int64_t i = 8;
    for (; i < n - (n % 8); i += 8)
        for (int j = 0; j < 8; ++j) r[j] += v[i + j];
    double res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
    for (; i < n; ++i) res += v[i];
    return res;
}

// np.argmin / np.argmax: first extreme, or the first NaN if there is one.
inline std::int64_t np_argext(const double* x, std::int64_t n, bool want_min) {
    std::int64_t best = 0;
    for (std::int64_t i = 0; i < n; ++i) {
        if (std::isnan(x[i])) return i;
        if (want_min ? x[i] < x[best] : x[i] > x[best]) best = i;
    }
    return best;
}

}  // namespace

EvalResult evaluate_paths(const double* psi, std::int64_t N,
                          const std::int64_t* st, const std::int64_t* offset,
                          std::int64_t P, const std::int64_t* sidx,
                          const double* swts, std::int64_t S, std::int64_t K,
                          const double* seg_len, const std::int64_t* gidx,
                          const double* gwts, std::int64_t Kg, double VT,
                          double Eg_J, double mr_kg, double mc_kg, double mv_kg,
                          double u, double hbar, double q) {
    EvalResult R;
    const double sc = VT * q / Eg_J;

    // path of each sample; raw (unclipped) delta per sample
    std::vector<std::int64_t> ps(static_cast<std::size_t>(S));
    for (std::int64_t p = 0; p < P; ++p)
        for (std::int64_t s = offset[p]; s < offset[p + 1]; ++s) ps[s] = p;
    std::vector<double> raw(static_cast<std::size_t>(S)), prod(static_cast<std::size_t>(K > Kg ? K : Kg));
    for (std::int64_t s = 0; s < S; ++s) {
        for (std::int64_t k = 0; k < K; ++k) prod[k] = swts[s * K + k] * psi[sidx[s * K + k]];
        const double psi_s = np_rowsum(prod.data(), K);
        raw[s] = sc * (psi_s - psi[st[ps[s]]]);
    }

    // segments: every sample except the last of its path, ascending
    std::vector<std::int64_t> seg;
    seg.reserve(static_cast<std::size_t>(S));
    for (std::int64_t p = 0; p < P; ++p)
        for (std::int64_t s = offset[p]; s < offset[p + 1] - 1; ++s) seg.push_back(s);
    const auto nseg = static_cast<std::int64_t>(seg.size());
    std::vector<double> da(nseg), db(nseg), L(nseg);
    for (std::int64_t i = 0; i < nseg; ++i) {
        da[i] = raw[seg[i]];
        db[i] = raw[seg[i] + 1];
        L[i] = seg_len[seg[i]];
    }
    std::vector<double> Ik_s(nseg), Iik_s(nseg), dIk_a(nseg), dIk_b(nseg), dIik_a(nseg), dIik_b(nseg);
    segment_integrals(da.data(), db.data(), L.data(), nseg, u, Eg_J, mr_kg, hbar, Ik_s.data(),
                      Iik_s.data(), dIk_a.data(), dIk_b.data(), dIik_a.data(), dIik_b.data());

    R.Ik.assign(static_cast<std::size_t>(P), 0.0);
    R.Iik.assign(static_cast<std::size_t>(P), 0.0);
    R.fmin.assign(static_cast<std::size_t>(P), std::numeric_limits<double>::infinity());
    R.fmax.assign(static_cast<std::size_t>(P), -std::numeric_limits<double>::infinity());
    const std::int64_t big = S + 1;
    std::vector<std::int64_t> cross(static_cast<std::size_t>(P), big);
    for (std::int64_t i = 0; i < nseg; ++i) {
        const std::int64_t p = ps[seg[i]];
        R.Ik[p] += Ik_s[i];
        R.Iik[p] += Iik_s[i];
        const double a = da[i], b = db[i];
        const double D = std::fabs(b - a);
        const double lo = np_clip01(np_minimum(a, b));
        const double hi = np_clip01(np_maximum(a, b));
        if (hi > lo) {   // barrier segment: diagnostic field range
            const double F = L[i] > 0.0 ? D * Eg_J / (q * L[i]) : 0.0;
            R.fmin[p] = np_minimum(R.fmin[p], F);
            R.fmax[p] = np_maximum(R.fmax[p], F);
        }
        if (a < 1.0 && b >= 1.0 && seg[i] < cross[p]) cross[p] = seg[i];
    }

    // the delta = 1 crossing, arc length, and dt/d(raw) at it
    std::vector<std::int64_t> cseg(static_cast<std::size_t>(P));
    std::vector<double> t(P), dt_da(P), dt_db(P);
    R.reached.resize(static_cast<std::size_t>(P));
    R.length.resize(static_cast<std::size_t>(P));
    std::vector<double> cs(static_cast<std::size_t>(S) + 1);
    cs[0] = 0.0;
    {
        double acc = 0.0;   // np.cumsum: sequential
        for (std::int64_t s = 0; s < S; ++s) { acc = s == 0 ? seg_len[0] : acc + seg_len[s]; cs[s + 1] = acc; }
    }
    for (std::int64_t p = 0; p < P; ++p) {
        const bool rc = cross[p] < big;
        R.reached[p] = rc ? 1 : 0;
        cseg[p] = rc ? cross[p] : (offset[p + 1] - 1) - 1;
        const double ca = raw[cseg[p]], cb = raw[cseg[p] + 1];
        const double Dc = rc ? cb - ca : 1.0;
        t[p] = rc ? (1.0 - ca) / Dc : 1.0;
        dt_da[p] = rc ? (1.0 - cb) / (Dc * Dc) : 0.0;
        dt_db[p] = rc ? -(1.0 - ca) / (Dc * Dc) : 0.0;
        R.length[p] = cs[cseg[p]] - cs[offset[p]] + t[p] * seg_len[cseg[p]];
    }

    // eq (11) prefactor and eq (12) km^2, both live
    const std::int64_t imin = np_argext(psi, N, true);
    const std::int64_t imax = np_argext(psi, N, false);
    const double nqv = -q * VT;
    const double Emax = nqv * psi[imin];
    const double Emin = nqv * psi[imax] + Eg_J;
    const double two_mv = 2.0 * mv_kg, two_mc = 2.0 * mc_kg;
    const double hb2 = hbar * hbar, qv = q * VT, qVT = q * VT, den36 = 36.0 * hbar;
    const double c_a1 = -2.0 * mv_kg * qv, c_a2 = 2.0 * mv_kg * qv;
    const double c_b1 = -2.0 * mc_kg * qv, c_b2 = 2.0 * mc_kg * qv;
    const double neg_sc = -sc;

    R.G.resize(static_cast<std::size_t>(P));
    std::vector<double> dG_dIk(P), dG_dIik(P), dG_dkm2(P), dG_dg(P);
    std::vector<std::uint8_t> use_a(P), use_b(P);
    for (std::int64_t p = 0; p < P; ++p) {
        for (std::int64_t j = 0; j < Kg; ++j) prod[j] = gwts[p * Kg + j] * psi[gidx[p * Kg + j]];
        const double gval = np_rowsum(prod.data(), Kg);
        const double gabs = std::fabs(gval);
        const double Pf = qVT * gabs / den36;
        const double E = nqv * psi[st[p]];
        const double a_km = two_mv * (Emax - E);
        const double b_km = two_mc * (E - Emin);
        const double m_km = np_minimum(a_km, b_km);
        const double km2 = np_maximum(m_km, 0.0) / hb2;
        const double Iik = R.Iik[p], Ik = R.Ik[p];
        const bool ok = Iik > 0.0;
        const double A = ok ? 1.0 / Iik : 0.0;
        const double e1 = std::exp(-km2 * Iik);
        const double B = 1.0 - e1;
        const double C = std::exp(-2.0 * Ik);
        const double G = ok ? Pf * A * B * C : 0.0;
        R.G[p] = G;
        dG_dIk[p] = -2.0 * G;
        dG_dIik[p] = ok ? Pf * (-A * A * B * C + A * km2 * e1 * C) : 0.0;
        dG_dkm2[p] = ok ? Pf * C * e1 : 0.0;
        dG_dg[p] = (ok && gabs > 0.0 ? G / gabs : 0.0) * np_sign(gval);
        use_a[p] = (m_km > 0.0) && (a_km < b_km);
        use_b[p] = (m_km > 0.0) && !(a_km < b_km);
    }

    // g_raw: two add.at passes into zeros, in reference order
    std::vector<double> g_raw(static_cast<std::size_t>(S), 0.0);
    for (std::int64_t i = 0; i < nseg; ++i) {
        const std::int64_t p = ps[seg[i]];
        g_raw[seg[i]] += dG_dIk[p] * dIk_a[i] + dG_dIik[p] * dIik_a[i];
    }
    for (std::int64_t i = 0; i < nseg; ++i) {
        const std::int64_t p = ps[seg[i]];
        g_raw[seg[i] + 1] += dG_dIk[p] * dIk_b[i] + dG_dIik[p] * dIik_b[i];
    }

    // dG COO: [sample stencils] [sample start] [gradient stencil] [4 km2 terms]
    const std::int64_t nG = S * K + S + P * Kg + 4 * P;
    R.dG_rows.resize(nG); R.dG_cols.resize(nG); R.dG_vals.resize(nG);
    std::int64_t w = 0;
    for (std::int64_t s = 0; s < S; ++s)
        for (std::int64_t k = 0; k < K; ++k, ++w) {
            R.dG_rows[w] = ps[s];
            R.dG_cols[w] = sidx[s * K + k];
            R.dG_vals[w] = sc * swts[s * K + k] * g_raw[s];
        }
    for (std::int64_t s = 0; s < S; ++s, ++w) {
        R.dG_rows[w] = ps[s]; R.dG_cols[w] = st[ps[s]]; R.dG_vals[w] = neg_sc * g_raw[s];
    }
    for (std::int64_t p = 0; p < P; ++p)
        for (std::int64_t j = 0; j < Kg; ++j, ++w) {
            R.dG_rows[w] = p; R.dG_cols[w] = gidx[p * Kg + j]; R.dG_vals[w] = dG_dg[p] * gwts[p * Kg + j];
        }
    for (std::int64_t p = 0; p < P; ++p, ++w) {
        R.dG_rows[w] = p; R.dG_cols[w] = imin; R.dG_vals[w] = use_a[p] ? dG_dkm2[p] * c_a1 / hb2 : 0.0;
    }
    for (std::int64_t p = 0; p < P; ++p, ++w) {
        R.dG_rows[w] = p; R.dG_cols[w] = st[p]; R.dG_vals[w] = use_a[p] ? dG_dkm2[p] * c_a2 / hb2 : 0.0;
    }
    for (std::int64_t p = 0; p < P; ++p, ++w) {
        R.dG_rows[w] = p; R.dG_cols[w] = st[p]; R.dG_vals[w] = use_b[p] ? dG_dkm2[p] * c_b1 / hb2 : 0.0;
    }
    for (std::int64_t p = 0; p < P; ++p, ++w) {
        R.dG_rows[w] = p; R.dG_cols[w] = imax; R.dG_vals[w] = use_b[p] ? dG_dkm2[p] * c_b2 / hb2 : 0.0;
    }

    // electron deposit: (1 - t) on sample cseg, t on cseg + 1
    R.dep_rows.resize(2 * P * K); R.dep_cols.resize(2 * P * K); R.dep_vals.resize(2 * P * K);
    w = 0;
    for (std::int64_t p = 0; p < P; ++p)
        for (std::int64_t k = 0; k < K; ++k, ++w) {
            R.dep_rows[w] = p; R.dep_cols[w] = sidx[cseg[p] * K + k];
            R.dep_vals[w] = (1.0 - t[p]) * swts[cseg[p] * K + k];
        }
    for (std::int64_t p = 0; p < P; ++p)
        for (std::int64_t k = 0; k < K; ++k, ++w) {
            R.dep_rows[w] = p; R.dep_cols[w] = sidx[(cseg[p] + 1) * K + k];
            R.dep_vals[w] = t[p] * swts[(cseg[p] + 1) * K + k];
        }

    // d dep / d psi, p-major then deposit node then column, zeros dropped
    const std::int64_t nn = 2 * K, nc = 2 * K + 1;
    std::vector<std::int64_t> n_nodes(nn), c_cols(nc);
    std::vector<double> n_coef(nn), c_vals(nc);
    R.ddep_p.reserve(P * nn * nc); R.ddep_node.reserve(P * nn * nc);
    R.ddep_col.reserve(P * nn * nc); R.ddep_val.reserve(P * nn * nc);
    for (std::int64_t p = 0; p < P; ++p) {
        const std::int64_t sa = cseg[p], sb = cseg[p] + 1;
        for (std::int64_t k = 0; k < K; ++k) {
            n_nodes[k] = sidx[sa * K + k];       n_coef[k] = -swts[sa * K + k];
            n_nodes[K + k] = sidx[sb * K + k];   n_coef[K + k] = swts[sb * K + k];
            c_cols[k] = sidx[sa * K + k];        c_vals[k] = dt_da[p] * sc * swts[sa * K + k];
            c_cols[K + k] = sidx[sb * K + k];    c_vals[K + k] = dt_db[p] * sc * swts[sb * K + k];
        }
        c_cols[2 * K] = st[p];
        c_vals[2 * K] = neg_sc * (dt_da[p] + dt_db[p]);
        for (std::int64_t a = 0; a < nn; ++a)
            for (std::int64_t c = 0; c < nc; ++c) {
                const double v = n_coef[a] * c_vals[c];
                if (v != 0.0) {
                    R.ddep_p.push_back(p); R.ddep_node.push_back(n_nodes[a]);
                    R.ddep_col.push_back(c_cols[c]); R.ddep_val.push_back(v);
                }
            }
    }
    return R;
}

}  // namespace tcad::nonlocal
