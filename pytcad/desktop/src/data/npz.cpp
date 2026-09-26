#include "npz.hpp"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <limits>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#ifdef TCAD_HAVE_ZLIB
#include <zlib.h>
#endif

namespace tcad::desktop {
namespace {

// -- little-endian field access with bounds checks ----------------------

struct Span {
    const std::uint8_t* p;
    std::size_t n;
    const std::string* label;

    void need(std::size_t off, std::size_t len, const char* what) const {
        if (off > n || len > n - off)
            throw NpzError(*label + ": truncated archive (reading " + what + ")");
    }
    std::uint16_t u16(std::size_t off, const char* what) const {
        need(off, 2, what);
        return static_cast<std::uint16_t>(p[off] | (p[off + 1] << 8));
    }
    std::uint32_t u32(std::size_t off, const char* what) const {
        need(off, 4, what);
        return static_cast<std::uint32_t>(p[off]) | (static_cast<std::uint32_t>(p[off + 1]) << 8) |
               (static_cast<std::uint32_t>(p[off + 2]) << 16) |
               (static_cast<std::uint32_t>(p[off + 3]) << 24);
    }
    std::uint64_t u64(std::size_t off, const char* what) const {
        return static_cast<std::uint64_t>(u32(off, what)) |
               (static_cast<std::uint64_t>(u32(off + 4, what)) << 32);
    }
};

constexpr std::uint32_t kEocdSig = 0x06054b50;
constexpr std::uint32_t kZip64EocdSig = 0x06064b50;
constexpr std::uint32_t kZip64LocatorSig = 0x07064b50;
constexpr std::uint32_t kCentralSig = 0x02014b50;
constexpr std::uint32_t kLocalSig = 0x04034b50;

std::uint32_t crc32(const std::uint8_t* data, std::size_t n) {
#ifdef TCAD_HAVE_ZLIB
    // zlib's CRC-32 (the zip polynomial) is several times faster than the
    // byte table below: 46 ms -> a few ms on a 32 MB archive (S5a profile).
    uLong c = ::crc32(0L, Z_NULL, 0);
    while (n > 0) {  // uInt lengths: feed at most 1 GiB at a time
        const uInt chunk = static_cast<uInt>(std::min<std::size_t>(n, std::size_t{1} << 30));
        c = ::crc32(c, data, chunk);
        data += chunk;
        n -= chunk;
    }
    return static_cast<std::uint32_t>(c);
#else
    static const std::array<std::uint32_t, 256> table = [] {
        std::array<std::uint32_t, 256> t{};
        for (std::uint32_t i = 0; i < 256; ++i) {
            std::uint32_t c = i;
            for (int k = 0; k < 8; ++k) c = (c & 1u) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            t[i] = c;
        }
        return t;
    }();
    std::uint32_t c = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < n; ++i) c = table[(c ^ data[i]) & 0xFFu] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
#endif
}

std::vector<std::uint8_t> inflate_raw(const std::uint8_t* src, std::size_t n,
                                      std::uint64_t out_size, const std::string& where) {
#ifdef TCAD_HAVE_ZLIB
    std::vector<std::uint8_t> out(static_cast<std::size_t>(out_size));
    z_stream zs{};
    if (inflateInit2(&zs, -MAX_WBITS) != Z_OK) throw NpzError(where + ": zlib init failed");
    zs.next_in = const_cast<Bytef*>(src);
    zs.avail_in = static_cast<uInt>(n);
    zs.next_out = out.data();
    zs.avail_out = static_cast<uInt>(out.size());
    const int rc = inflate(&zs, Z_FINISH);
    const auto produced = zs.total_out;
    inflateEnd(&zs);
    if (rc != Z_STREAM_END || produced != out_size)
        throw NpzError(where + ": corrupt deflate data");
    return out;
#else
    (void)src; (void)n; (void)out_size;
    throw NpzError(where + ": compressed entry (np.savez_compressed) but this build has no zlib");
#endif
}

// -- .npy header dictionary -------------------------------------------------

std::string header_value(const std::string& h, const std::string& key, const std::string& where) {
    const auto k = h.find("'" + key + "'");
    if (k == std::string::npos) throw NpzError(where + ": npy header has no '" + key + "'");
    auto colon = h.find(':', k);
    if (colon == std::string::npos) throw NpzError(where + ": malformed npy header");
    auto v = h.find_first_not_of(' ', colon + 1);
    if (v == std::string::npos) throw NpzError(where + ": malformed npy header");
    if (h[v] == '\'' || h[v] == '"') {
        const auto end = h.find(h[v], v + 1);
        if (end == std::string::npos) throw NpzError(where + ": malformed npy header");
        return h.substr(v, end - v + 1);
    }
    if (h[v] == '(' || h[v] == '[') {
        const char close = h[v] == '(' ? ')' : ']';
        const auto end = h.find(close, v);
        if (end == std::string::npos) throw NpzError(where + ": malformed npy header");
        return h.substr(v, end - v + 1);
    }
    const auto end = h.find_first_of(",}", v);
    return h.substr(v, end - v);
}

std::vector<std::size_t> parse_shape(const std::string& tuple, const std::string& where) {
    std::vector<std::size_t> shape;
    std::size_t i = 1;  // skip '('
    while (i < tuple.size()) {
        const auto c = tuple[i];
        if (c >= '0' && c <= '9') {
            std::size_t v = 0;
            while (i < tuple.size() && tuple[i] >= '0' && tuple[i] <= '9') {
                const std::size_t d = static_cast<std::size_t>(tuple[i] - '0');
                if (v > (std::numeric_limits<std::size_t>::max() - d) / 10)
                    throw NpzError(where + ": shape overflows");
                v = v * 10 + d;
                ++i;
            }
            shape.push_back(v);
        } else if (c == ',' || c == ' ' || c == ')' || c == 'L') {
            ++i;
        } else {
            throw NpzError(where + ": malformed shape " + tuple);
        }
    }
    return shape;
}

void parse_descr(const std::string& quoted, NpyArray& a, const std::string& where) {
    if (quoted.size() < 3 || (quoted.front() != '\'' && quoted.front() != '"'))
        throw NpzError(where + ": structured or unsupported dtype " + quoted);
    const std::string d = quoted.substr(1, quoted.size() - 2);
    a.descr = d;
    if (d.size() >= 2 && d[1] == 'O') throw NpzError(where + ": object (pickled) arrays are not supported");
    if (d.size() < 3) throw NpzError(where + ": unsupported dtype '" + d + "'");
    const char order = d[0];
    a.kind = d[1];
    std::size_t n = 0;
    for (std::size_t i = 2; i < d.size(); ++i) {
        if (d[i] < '0' || d[i] > '9') throw NpzError(where + ": unsupported dtype '" + d + "'");
        n = n * 10 + static_cast<std::size_t>(d[i] - '0');
    }
    switch (a.kind) {
        case 'b':
            if (n != 1) throw NpzError(where + ": unsupported dtype '" + d + "'");
            a.itemsize = 1;
            break;
        case 'i':
        case 'u':
            if (n != 1 && n != 2 && n != 4 && n != 8)
                throw NpzError(where + ": unsupported dtype '" + d + "'");
            a.itemsize = n;
            break;
        case 'f':
            if (n != 4 && n != 8) throw NpzError(where + ": unsupported dtype '" + d + "'");
            a.itemsize = n;
            break;
        case 'U':
            a.itemsize = 4 * n;  // numpy stores UCS-4
            break;
        default:
            throw NpzError(where + ": unsupported dtype '" + d + "'");
    }
    // '=' is native, which is little-endian on every Windows target.
    if (order == '>' && (a.itemsize > 1 || a.kind == 'U'))
        throw NpzError(where + ": big-endian data is not supported");
    if (order != '<' && order != '|' && order != '=' && order != '>')
        throw NpzError(where + ": unsupported byte order in '" + d + "'");
}

std::size_t storage_index(const NpyArray& a, std::size_t c_index) {
    if (!a.fortran_order || a.shape.size() < 2) return c_index;
    // Decompose the C-order flat index, recompose in Fortran order.
    std::size_t rem = c_index, f_index = 0, f_stride = 1;
    std::vector<std::size_t> idx(a.shape.size());
    for (std::size_t d = a.shape.size(); d-- > 0;) {
        idx[d] = rem % a.shape[d];
        rem /= a.shape[d];
    }
    for (std::size_t d = 0; d < a.shape.size(); ++d) {
        f_index += idx[d] * f_stride;
        f_stride *= a.shape[d];
    }
    return f_index;
}

double element_as_double(const NpyArray& a, std::size_t s) {
    const std::uint8_t* p = a.data.data() + s * a.itemsize;
    switch (a.kind) {
        case 'b': return *p ? 1.0 : 0.0;
        case 'f':
            if (a.itemsize == 8) { double v; std::memcpy(&v, p, 8); return v; }
            { float v; std::memcpy(&v, p, 4); return v; }
        case 'i':
            switch (a.itemsize) {
                case 1: { std::int8_t v; std::memcpy(&v, p, 1); return v; }
                case 2: { std::int16_t v; std::memcpy(&v, p, 2); return v; }
                case 4: { std::int32_t v; std::memcpy(&v, p, 4); return v; }
                default: { std::int64_t v; std::memcpy(&v, p, 8); return static_cast<double>(v); }
            }
        case 'u':
            switch (a.itemsize) {
                case 1: return *p;
                case 2: { std::uint16_t v; std::memcpy(&v, p, 2); return v; }
                case 4: { std::uint32_t v; std::memcpy(&v, p, 4); return v; }
                default: { std::uint64_t v; std::memcpy(&v, p, 8); return static_cast<double>(v); }
            }
        default: break;
    }
    throw NpzError("array of kind '" + std::string(1, a.kind) + "' is not numeric");
}

void append_utf8(std::string& out, std::uint32_t cp) {
    if (cp < 0x80) {
        out += static_cast<char>(cp);
    } else if (cp < 0x800) {
        out += static_cast<char>(0xC0 | (cp >> 6));
        out += static_cast<char>(0x80 | (cp & 0x3F));
    } else if (cp < 0x10000) {
        out += static_cast<char>(0xE0 | (cp >> 12));
        out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
        out += static_cast<char>(0x80 | (cp & 0x3F));
    } else if (cp <= 0x10FFFF) {
        out += static_cast<char>(0xF0 | (cp >> 18));
        out += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
        out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
        out += static_cast<char>(0x80 | (cp & 0x3F));
    } else {
        throw NpzError("invalid code point in unicode array");
    }
}

}  // namespace

// -- NpyArray ---------------------------------------------------------------

std::size_t NpyArray::count() const {
    std::size_t n = 1;
    for (auto s : shape) n *= s;
    return n;
}

std::vector<double> NpyArray::to_doubles() const {
    if (!is_numeric()) throw NpzError("to_doubles() on a non-numeric array ('" + descr + "')");
    const std::size_t n = count();
    std::vector<double> out(n);
    if (n == 0) return out;
    const bool c_order = !fortran_order || shape.size() < 2;
    if (c_order && kind == 'f' && itemsize == 8) {  // every field the solver writes: one copy
        std::memcpy(out.data(), data.data(), n * sizeof(double));
        return out;
    }
    if (c_order) {
        for (std::size_t i = 0; i < n; ++i) out[i] = element_as_double(*this, i);
        return out;
    }
    // Fortran order: walk storage order once (first index fastest),
    // carrying a multi-index and its C-order flat index along.
    const std::size_t nd = shape.size();
    std::vector<std::size_t> idx(nd, 0), c_stride(nd, 1);
    for (std::size_t d = nd - 1; d-- > 0;) c_stride[d] = c_stride[d + 1] * shape[d + 1];
    std::size_t c = 0;
    for (std::size_t s = 0; s < n; ++s) {
        out[c] = element_as_double(*this, s);
        for (std::size_t d = 0; d < nd; ++d) {
            c += c_stride[d];
            if (++idx[d] < shape[d]) break;
            c -= shape[d] * c_stride[d];
            idx[d] = 0;
        }
    }
    return out;
}

std::vector<std::string> NpyArray::to_strings() const {
    if (kind != 'U') throw NpzError("to_strings() on a non-unicode array ('" + descr + "')");
    const std::size_t n = count(), chars = itemsize / 4;
    std::vector<std::string> out(n);
    for (std::size_t i = 0; i < n; ++i) {
        const std::uint8_t* p = data.data() + storage_index(*this, i) * itemsize;
        std::size_t len = chars;
        auto cp_at = [p](std::size_t c) {
            return static_cast<std::uint32_t>(p[4 * c]) | (static_cast<std::uint32_t>(p[4 * c + 1]) << 8) |
                   (static_cast<std::uint32_t>(p[4 * c + 2]) << 16) |
                   (static_cast<std::uint32_t>(p[4 * c + 3]) << 24);
        };
        while (len > 0 && cp_at(len - 1) == 0) --len;
        for (std::size_t c = 0; c < len; ++c) append_utf8(out[i], cp_at(c));
    }
    return out;
}

double NpyArray::scalar() const {
    if (count() != 1) throw NpzError("scalar() on an array with " + std::to_string(count()) + " elements");
    return to_doubles()[0];
}

std::string NpyArray::string_scalar() const {
    if (count() != 1) throw NpzError("string_scalar() on an array with " + std::to_string(count()) + " elements");
    return to_strings()[0];
}

namespace {

// The header of one .npy payload: the array without its data, and where
// the data starts.
NpyArray parse_npy_header(const std::uint8_t* bytes, std::size_t size, std::size_t* data_off_out) {
    static const std::string where = "npy";
    static const std::uint8_t magic[6] = {0x93, 'N', 'U', 'M', 'P', 'Y'};
    if (size < 10 || std::memcmp(bytes, magic, 6) != 0) throw NpzError("not an npy payload (bad magic)");
    const std::string label = "npy";
    const Span s{bytes, size, &label};
    const std::uint8_t major = bytes[6];
    std::size_t header_len = 0, header_off = 0;
    if (major == 1) {
        header_len = s.u16(8, "npy header length");
        header_off = 10;
    } else if (major == 2 || major == 3) {
        header_len = s.u32(8, "npy header length");
        header_off = 12;
    } else {
        throw NpzError("unsupported npy format version " + std::to_string(major));
    }
    s.need(header_off, header_len, "npy header");
    const std::string h(reinterpret_cast<const char*>(bytes + header_off), header_len);

    NpyArray a;
    parse_descr(header_value(h, "descr", where), a, where);
    const std::string fo = header_value(h, "fortran_order", where);
    if (fo.rfind("True", 0) == 0) a.fortran_order = true;
    else if (fo.rfind("False", 0) == 0) a.fortran_order = false;
    else throw NpzError("malformed fortran_order in npy header");
    a.shape = parse_shape(header_value(h, "shape", where), where);

    const std::size_t data_off = header_off + header_len;
    std::size_t expected = a.itemsize;
    for (auto d : a.shape) {
        if (d != 0 && expected > std::numeric_limits<std::size_t>::max() / d)
            throw NpzError("npy array size overflows");
        expected *= d;
    }
    if (size - data_off != expected)
        throw NpzError("npy data is " + std::to_string(size - data_off) + " bytes, header implies " +
                       std::to_string(expected) + " (truncated or corrupt)");
    *data_off_out = data_off;
    return a;
}

// Parses a payload it owns: the header is dropped in place and the buffer
// becomes the array's data -- no second copy of a large array.
NpyArray parse_npy_owned(std::vector<std::uint8_t>&& payload) {
    std::size_t data_off = 0;
    NpyArray a = parse_npy_header(payload.data(), payload.size(), &data_off);
    payload.erase(payload.begin(), payload.begin() + static_cast<std::ptrdiff_t>(data_off));
    a.data = std::move(payload);
    return a;
}

}  // namespace

NpyArray parse_npy(const std::uint8_t* bytes, std::size_t size) {
    std::size_t data_off = 0;
    NpyArray a = parse_npy_header(bytes, size, &data_off);
    a.data.assign(bytes + data_off, bytes + size);
    return a;
}

// -- NpzFile ------------------------------------------------------------------

// Where an archive's bytes come from: a file read piece by piece
// (NpzFile::open) or a buffer (from_bytes). Reading past the end is a
// "truncated archive" error naming what was being read.
class NpzSource {
public:
    explicit NpzSource(const std::string* label) : label_(label) {}
    virtual ~NpzSource() = default;
    virtual std::uint64_t size() const = 0;
    std::vector<std::uint8_t> bytes(std::uint64_t off, std::uint64_t len, const char* what) const {
        if (off > size() || len > size() - off)
            throw NpzError(*label_ + ": truncated archive (reading " + what + ")");
        std::vector<std::uint8_t> v(static_cast<std::size_t>(len));
        if (len) read(off, v.data(), static_cast<std::size_t>(len), what);
        return v;
    }

protected:
    virtual void read(std::uint64_t off, std::uint8_t* dst, std::size_t len, const char* what) const = 0;
    const std::string* label_;
};

namespace {

class MemorySource final : public NpzSource {
public:
    MemorySource(const std::vector<std::uint8_t>& b, const std::string* label) : NpzSource(label), b_(b) {}
    std::uint64_t size() const override { return b_.size(); }

protected:
    void read(std::uint64_t off, std::uint8_t* dst, std::size_t len, const char*) const override {
        std::memcpy(dst, b_.data() + off, len);
    }

private:
    const std::vector<std::uint8_t>& b_;
};

class FileSource final : public NpzSource {
public:
    FileSource(const std::filesystem::path& path, const std::string* label) : NpzSource(label), in_(path, std::ios::binary) {
        if (!in_) throw NpzError(*label + ": cannot open");
        in_.seekg(0, std::ios::end);
        const std::streamoff n = in_.tellg();
        if (n < 0) throw NpzError(*label + ": cannot determine the file size");
        size_ = static_cast<std::uint64_t>(n);
    }
    std::uint64_t size() const override { return size_; }

protected:
    void read(std::uint64_t off, std::uint8_t* dst, std::size_t len, const char* what) const override {
        in_.clear();
        in_.seekg(static_cast<std::streamoff>(off), std::ios::beg);
        // One sized read per piece (S5a: a byte-at-a-time read took 150 ms of a 32 MB open).
        if (!in_.read(reinterpret_cast<char*>(dst), static_cast<std::streamsize>(len)))
            throw NpzError(*label_ + ": read failed (" + what + ")");
    }

private:
    mutable std::ifstream in_;
    std::uint64_t size_ = 0;
};

struct Entry {
    std::string name;
    std::uint16_t flags = 0, method = 0;
    std::uint32_t crc = 0;
    std::uint64_t csize = 0, usize = 0, loff = 0;
};

std::string gib(std::uint64_t bytes) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "%.2f GB", static_cast<double>(bytes) / 1e9);
    return buf;
}

}  // namespace

std::uint64_t NpzFile::default_limit() {
    MEMORYSTATUSEX ms{};
    ms.dwLength = sizeof ms;
    if (!GlobalMemoryStatusEx(&ms)) return UINT64_MAX;
    return ms.ullAvailPhys / 4 * 3;
}

NpzFile NpzFile::open(const std::filesystem::path& path, std::uint64_t max_array_bytes) {
    // The label is UTF-8. path.string() converts to the ANSI code page on
    // Windows and THROWS for a character outside it (an emoji in a
    // directory name did, in the S3 shell probe), failing a file that
    // opens fine through the wide path.
    const std::u8string u8 = path.u8string();
    NpzFile f;
    f.label_.assign(reinterpret_cast<const char*>(u8.data()), u8.size());
    const FileSource src(path, &f.label_);
    f.read_archive(src, max_array_bytes);
    return f;  // the file closes with `src`
}

NpzFile NpzFile::from_bytes(const std::vector<std::uint8_t>& bytes, const std::string& label,
                            std::uint64_t max_array_bytes) {
    NpzFile f;
    f.label_ = label;
    const MemorySource src(bytes, &f.label_);
    f.read_archive(src, max_array_bytes);
    return f;
}

void NpzFile::read_archive(const NpzSource& src, std::uint64_t max_array_bytes) {
    const std::string& label = label_;
    const std::uint64_t size = src.size();
    if (size < 22) throw NpzError(label + ": not a zip archive (too small)");

    // End of central directory: scan back over a possible comment, in the
    // file's last 64 KB only.
    const std::uint64_t tail_len = std::min<std::uint64_t>(size, 22 + 65535);
    const std::uint64_t tail_off = size - tail_len;
    const std::vector<std::uint8_t> tail = src.bytes(tail_off, tail_len, "EOCD");
    const Span t{tail.data(), tail.size(), &label};
    std::size_t eocd = std::string::npos;
    for (std::size_t i = tail.size() - 22 + 1; i-- > 0;) {
        if (t.u32(i, "EOCD") == kEocdSig) { eocd = i; break; }
    }
    if (eocd == std::string::npos) throw NpzError(label + ": not a zip archive (no end-of-directory record)");
    const std::uint64_t eocd_abs = tail_off + eocd;

    std::uint64_t entries = t.u16(eocd + 10, "EOCD");
    std::uint64_t cd_size = t.u32(eocd + 12, "EOCD");
    std::uint64_t cd_off = t.u32(eocd + 16, "EOCD");
    if (entries == 0xFFFF || cd_off == 0xFFFFFFFF || cd_size == 0xFFFFFFFF) {
        if (eocd_abs < 20) throw NpzError(label + ": zip64 archive without a zip64 locator");
        const std::vector<std::uint8_t> loc = src.bytes(eocd_abs - 20, 20, "zip64 locator");
        const Span l{loc.data(), loc.size(), &label};
        if (l.u32(0, "zip64 locator") != kZip64LocatorSig)
            throw NpzError(label + ": zip64 archive without a zip64 locator");
        const std::vector<std::uint8_t> z = src.bytes(l.u64(8, "zip64 locator"), 56, "zip64 EOCD");
        const Span zs{z.data(), z.size(), &label};
        if (zs.u32(0, "zip64 EOCD") != kZip64EocdSig) throw NpzError(label + ": bad zip64 end-of-directory record");
        entries = zs.u64(32, "zip64 EOCD");
        cd_size = zs.u64(40, "zip64 EOCD");
        cd_off = zs.u64(48, "zip64 EOCD");
    }

    // The central directory, then every entry's description -- nothing of
    // the arrays themselves yet.
    const std::vector<std::uint8_t> cd = src.bytes(cd_off, cd_size, "central directory");
    const Span s{cd.data(), cd.size(), &label};
    std::vector<Entry> list;
    std::uint64_t total = 0;
    std::size_t p = 0;
    for (std::uint64_t e = 0; e < entries; ++e) {
        if (s.u32(p, "central directory") != kCentralSig)
            throw NpzError(label + ": corrupt central directory");
        Entry en;
        en.flags = s.u16(p + 8, "central directory");
        en.method = s.u16(p + 10, "central directory");
        en.crc = s.u32(p + 16, "central directory");
        en.csize = s.u32(p + 20, "central directory");
        en.usize = s.u32(p + 24, "central directory");
        const std::uint16_t nlen = s.u16(p + 28, "central directory");
        const std::uint16_t xlen = s.u16(p + 30, "central directory");
        const std::uint16_t clen = s.u16(p + 32, "central directory");
        en.loff = s.u32(p + 42, "central directory");
        s.need(p + 46, nlen, "entry name");
        en.name.assign(reinterpret_cast<const char*>(cd.data() + p + 46), nlen);

        // zip64 extra field: the 0xFFFFFFFF placeholders, in this order.
        std::size_t x = p + 46 + nlen;
        const std::size_t xend = x + xlen;
        s.need(x, xlen, "extra field");
        while (x + 4 <= xend) {
            const std::uint16_t id = s.u16(x, "extra field");
            const std::uint16_t len = s.u16(x + 2, "extra field");
            std::size_t q = x + 4;
            if (id == 0x0001) {
                if (en.usize == 0xFFFFFFFF) { en.usize = s.u64(q, "zip64 extra"); q += 8; }
                if (en.csize == 0xFFFFFFFF) { en.csize = s.u64(q, "zip64 extra"); q += 8; }
                if (en.loff == 0xFFFFFFFF) { en.loff = s.u64(q, "zip64 extra"); q += 8; }
            }
            x += 4 + len;
        }
        p = xend + clen;

        const std::string where = label + ": " + en.name;
        if (en.flags & 0x0001) throw NpzError(where + ": encrypted entries are not supported");
        if (en.name.size() < 4 || en.name.compare(en.name.size() - 4, 4, ".npy") != 0) continue;
        if (en.usize > UINT64_MAX - total) throw NpzError(where + ": entry sizes overflow");
        total += en.usize;
        list.push_back(std::move(en));
    }
    // Bounded memory: refuse before reading a single array.
    if (total > max_array_bytes)
        throw NpzError(label + ": the result's arrays need " + gib(total) + " of memory, over the limit of " +
                       gib(max_array_bytes) + " (by default 3/4 of the memory free when it is opened)");

    for (Entry& en : list) {
        const std::string where = label + ": " + en.name;
        const std::vector<std::uint8_t> lh = src.bytes(en.loff, 30, "local header");
        const Span ls{lh.data(), lh.size(), &label};
        if (ls.u32(0, "local header") != kLocalSig) throw NpzError(where + ": corrupt local header");
        const std::uint64_t data_off = en.loff + 30 + ls.u16(26, "local header") + ls.u16(28, "local header");
        std::vector<std::uint8_t> payload = src.bytes(data_off, en.csize, "entry data");
        if (en.method == 0) {
            if (en.csize != en.usize) throw NpzError(where + ": stored entry size mismatch");
        } else if (en.method == 8) {
            payload = inflate_raw(payload.data(), payload.size(), en.usize, where);
        } else {
            throw NpzError(where + ": unsupported zip compression method " + std::to_string(en.method));
        }
        if (crc32(payload.data(), payload.size()) != en.crc) throw NpzError(where + ": CRC mismatch (corrupt archive)");

        NpyArray arr;
        try {
            arr = parse_npy_owned(std::move(payload));
        } catch (const NpzError& err) {
            throw NpzError(where + ": " + err.what());
        }
        const std::string key = en.name.substr(0, en.name.size() - 4);
        if (arrays_.count(key)) throw NpzError(where + ": duplicate entry");
        array_bytes_ += arr.data.size();
        names_.push_back(key);
        arrays_.emplace(key, std::move(arr));
    }
}

const NpyArray& NpzFile::at(const std::string& name) const {
    const auto it = arrays_.find(name);
    if (it == arrays_.end()) throw NpzError(label_ + ": no array '" + name + "'");
    return it->second;
}

}  // namespace tcad::desktop
