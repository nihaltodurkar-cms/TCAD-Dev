// C++ counterpart of gui/services/result_store.py's NpzResultStore, for
// the parts the viewer needs: mesh axes, scalar and vector fields,
// terminal currents, region metadata and 3D sweep snapshots.
//
// Opening validates the file exactly as gui/services/solver_backend.py's
// validate_result does (NATIVE-DESKTOP-PLAN.md section 15, P1 S1): schema
// stamp, dimensionality, axes, fields and units, vector fields, the v2
// geometry block, record/trace JSON, terminal pairs, and the sweep,
// transient and AC blocks -- in the same order, with the same messages.
// Like the store, snapshots and region metadata are NOT checked at open;
// their accessors fail when read (validate_result never looks inside
// them, and a file it accepts must open here too).
//
// Deliberately stricter than Python, on inputs no writer produces: an
// integer key holding a non-integer float or a string (Python's int()
// truncates or parses it), and a non-numeric field, vector or series
// array (Python checks only its shape) are rejected here.
//
// Conformance gate: gui/tests/test_desktop_contracts.py.
#pragma once

#include "npz.hpp"

#include <nlohmann/json.hpp>

#include <array>
#include <optional>
#include <string>
#include <vector>

namespace tcad::desktop {

struct ResultSchemaError : NpzError {
    using NpzError::NpzError;
};

struct ScalarField {
    std::string name;
    std::string unit;
    std::vector<double> values;  // C order: (Nx) / (Ny,Nx) / (Nz,Ny,Nx), x fastest
};

struct VectorField {
    std::string name;
    std::string unit;
    // One entry per axis of the dimensionality, in axis order x, y, z;
    // each in the same C order as ScalarField::values.
    std::vector<std::vector<double>> components;
};

struct Terminal {
    std::string name;
    double value = 0.0;
    std::string unit;
};

struct SweepSnapshots {
    std::vector<double> voltages;          // [V], one per converged point
    std::vector<std::string> field_names;  // sorted
    std::vector<std::size_t> shape;        // mesh__shape as written: (Nz, Ny, Nx)
    std::size_t count() const { return voltages.size(); }
};

class ResultModel {
public:
    // The result grammar versions this build reads -- keep in step with
    // solver_backend.KNOWN_RESULT_SCHEMA_VERSIONS (contract-tested).
    static constexpr std::array<int, 3> kKnownSchemaVersions{1, 2, 3};
    // The largest mesh the viewer opens (NATIVE-DESKTOP-PLAN.md 15.23,
    // decision 1): 64M nodes, ~512 MB per field -- 64x the 1M bench grids.
    // Checked right after the axes, before any field is looked at.
    static constexpr std::size_t kMaxNodes = std::size_t{1} << 26;

    // Validates; throws ResultSchemaError naming the first violation.
    // `npz` must outlive the model (fields are decoded on demand).
    static ResultModel from_npz(const NpzFile& npz, const std::string& label = "<npz>");

    int dimensionality() const { return dim_; }
    int schema_version() const { return schema_; }
    // Node positions [cm]; axis 0/1/2 = x/y/z. Missing axes are empty.
    const std::vector<double>& axis(int a) const { return axes_[static_cast<std::size_t>(a)]; }
    // (Nx, Ny, Nz) with 1 for absent axes.
    std::array<std::size_t, 3> node_counts() const;

    // Sorted, like NpzResultStore.available_scalars() / _vectors() / _terminals().
    const std::vector<std::string>& scalar_names() const { return scalars_; }
    const std::vector<std::string>& vector_names() const { return vectors_; }
    const std::vector<std::string>& terminal_names() const { return terminals_; }
    ScalarField scalar(const std::string& name) const;
    VectorField vector(const std::string& name) const;
    Terminal terminal(const std::string& name) const;

    // Provenance and block sizes for the info panel (S3d):
    // solved_bias is Python's bool() of the 0-d array -- True for a
    // bias solve, False for equilibrium only. The APPLIED voltages are
    // not in the result grammar (they live in the job's DeviceSpec).
    bool solved_bias() const;
    // record__meta (validated as a JSON object at open); nullopt on pre-v2 files.
    std::optional<nlohmann::ordered_json> record() const;
    std::string geometry_kind() const;  // geom__kind, "" when absent
    std::size_t sweep_points() const;      // sweep__voltage length, 0 when absent
    std::size_t transient_points() const;  // transient__times length
    std::size_t ac_points() const;         // ac__freqs length

    // The DeviceSpec wire lists stamped as region_materials__meta /
    // structure_regions__meta; nullopt when absent. Throws
    // ResultSchemaError when present but not JSON (the store raises too).
    std::optional<nlohmann::ordered_json> region_materials() const;
    std::optional<nlohmann::ordered_json> structure_regions() const;

    // True when sweep__snapshot__voltages is present (field data may
    // still be missing -- sweep_snapshots() then throws, as the store does).
    bool has_sweep_snapshots() const;
    // Parses and checks every snapshot array against mesh__shape; throws
    // ResultSchemaError where NpzResultStore.sweep_snapshots() raises.
    SweepSnapshots sweep_snapshots() const;
    // One snapshot, C order. Throws for an unknown field, an index
    // outside [0, count()) or a missing array.
    std::vector<double> snapshot_field(const SweepSnapshots& s, const std::string& field,
                                       std::size_t index) const;

private:
    std::optional<nlohmann::ordered_json> json_meta(const std::string& key) const;

    const NpzFile* npz_ = nullptr;
    int dim_ = 0;
    int schema_ = 1;
    std::array<std::vector<double>, 3> axes_;
    std::vector<std::string> scalars_;
    std::vector<std::string> vectors_;
    std::vector<std::string> terminals_;
    std::string label_;
};

}  // namespace tcad::desktop
