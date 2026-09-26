// Reader for the solver's result files: numpy .npz archives written by
// np.savez (gui/services/solver_runner.py and friends).
//
// Scope is exactly what the result grammar uses (NATIVE-DESKTOP-PLAN.md
// section 4.2): little-endian (or byte-order-free) bool / signed and
// unsigned integer / float / fixed-width unicode arrays, C or Fortran
// order, any rank including 0-d. Anything else -- object (pickled)
// arrays, structured dtypes, big-endian data, encrypted or corrupt
// archives -- raises NpzError with a message naming the cause, never a
// silent misread.
//
// The conformance gate is gui/tests/test_desktop_contracts.py: for
// every array, this reader's dtype, order, shape and raw bytes must be
// identical to numpy's.
#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace tcad::desktop {

class NpzSource;  // npz.cpp: where an archive's bytes come from

struct NpzError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

struct NpyArray {
    std::string descr;               // numpy dtype.str, e.g. "<f8", "|b1", "<U12"
    char kind = 0;                   // 'b', 'i', 'u', 'f' or 'U'
    std::size_t itemsize = 0;        // bytes per element (4 per char for 'U')
    bool fortran_order = false;
    std::vector<std::size_t> shape;  // empty == 0-d scalar
    std::vector<std::uint8_t> data;  // raw element bytes, in storage order

    std::size_t count() const;       // number of elements (1 for 0-d)
    bool is_numeric() const { return kind == 'b' || kind == 'i' || kind == 'u' || kind == 'f'; }

    // Every element as double, in logical C (row-major) order whatever
    // the storage order. Numeric kinds only.
    std::vector<double> to_doubles() const;
    // Every element decoded to UTF-8 (trailing NULs stripped, as numpy's
    // str() does), in logical C order. 'U' kind only.
    std::vector<std::string> to_strings() const;
    // The single element of a 0-d (or one-element) array.
    double scalar() const;
    std::string string_scalar() const;
};

// Parse one .npy payload. Exposed for the unit tests.
NpyArray parse_npy(const std::uint8_t* bytes, std::size_t size);

class NpzFile {
public:
    // Reads every array eagerly (like the Python store's _LoadedNpz), so
    // no file handle stays open on Windows -- a mapped or open file could
    // not be deleted or replaced by the solver while it is shown.
    //
    // Memory is bounded (NATIVE-DESKTOP-PLAN.md 15.23, S8a): only the
    // archive's tail and central directory are read first; the total size
    // of its arrays is checked against `max_array_bytes` BEFORE any array
    // is read (a refusal names both numbers); then each array is read
    // straight into its own buffer, with no whole-file copy. A 2 GB file
    // that is not a zip costs its last 64 KB.
    static NpzFile open(const std::filesystem::path& path, std::uint64_t max_array_bytes = default_limit());
    static NpzFile from_bytes(const std::vector<std::uint8_t>& bytes,
                              const std::string& label = "<memory>",
                              std::uint64_t max_array_bytes = UINT64_MAX);
    // 3/4 of the physical memory free right now (UINT64_MAX if unknown).
    static std::uint64_t default_limit();
    // Total uncompressed bytes of the arrays read.
    std::uint64_t array_bytes() const { return array_bytes_; }

    // Array names in archive order, without the ".npy" suffix.
    const std::vector<std::string>& names() const { return names_; }
    bool contains(const std::string& name) const { return arrays_.count(name) != 0; }
    const NpyArray& at(const std::string& name) const;

private:
    void read_archive(const NpzSource& src, std::uint64_t max_array_bytes);
    std::vector<std::string> names_;
    std::map<std::string, NpyArray> arrays_;
    std::string label_;
    std::uint64_t array_bytes_ = 0;
};

}  // namespace tcad::desktop
