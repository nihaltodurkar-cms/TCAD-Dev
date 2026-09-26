// A line cut through a 2D scalar field (NATIVE-DESKTOP-PLAN.md 16.5,
// decision 1): the C++ port of gui/services/result_store.py's
// extract_line_cut -- the mesh row or column NEAREST the requested
// position, not interpolated, with the node actually used reported.
// Array slicing, not physics, so it runs here instead of a backend round
// trip per slider step. Qt-free; contract-tested against the Python
// function by gui/tests/test_desktop_contracts.py (uniform and graded
// meshes, both orientations, positions outside the mesh, and a request
// exactly midway between two nodes: numpy's argmin takes the FIRST
// minimum, and so does this).
#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace tcad::desktop {

enum class CutOrientation {
    Horizontal,  // cut at the nearest y; values vary along x
    Vertical,    // cut at the nearest x; values vary along y
};

struct LineCut {
    std::vector<double> coord;  // along the cut [the axes' unit]: x (horizontal) or y (vertical)
    std::vector<double> values;
    double actual = 0.0;        // the coordinate of the row/column used
    std::size_t index = 0;      // its index on the cut axis
};

// The node nearest `position` on `axis`: numpy's argmin(abs(axis - position)),
// first minimum on a tie; NaN propagates as in numpy (the first NaN distance
// wins, so a NaN position gives 0). Throws std::invalid_argument on an empty axis.
std::size_t nearest_node(const std::vector<double>& axis, double position);

// `values` in C order (Ny, Nx), x fastest. Throws std::invalid_argument
// when its size is not x.size() * y.size() or an axis is empty.
LineCut line_cut(const std::vector<double>& x, const std::vector<double>& y,
                 const std::vector<double>& values, CutOrientation orientation, double position);

// "horizontal" / "vertical" (extract_line_cut's own spellings); throws
// std::invalid_argument naming anything else.
CutOrientation cut_orientation_from_string(const std::string& s);

}  // namespace tcad::desktop
