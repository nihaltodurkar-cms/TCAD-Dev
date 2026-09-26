// Unit tests for the Qt-free data layer: .npy payload parsing and the
// DeviceSpec document. Whole-archive (.npz) conformance against numpy
// itself lives in gui/tests/test_desktop_contracts.py.
#include "data/npz.hpp"
#include "data/pyjson.hpp"
#include "document/device_spec_document.hpp"

#include <QtTest/QtTest>

#include <cstring>

using tcad::desktop::DeviceSpecDocument;
using tcad::desktop::NpzError;
using tcad::desktop::parse_npy;
using tcad::desktop::is_python_int;
using tcad::desktop::parse_python_json;
using tcad::desktop::PyJsonError;
using tcad::desktop::replace_nonfinite_tokens;

namespace {

// A version-1.0 .npy payload, header padded like numpy's.
std::vector<std::uint8_t> npy(const std::string& descr, bool fortran, const std::string& shape,
                              const std::vector<std::uint8_t>& data) {
    std::string h = "{'descr': " + descr + ", 'fortran_order': " + (fortran ? "True" : "False") +
                    ", 'shape': " + shape + ", }";
    while ((10 + h.size() + 1) % 64 != 0) h += ' ';
    h += '\n';
    std::vector<std::uint8_t> b = {0x93, 'N', 'U', 'M', 'P', 'Y', 1, 0};
    b.push_back(static_cast<std::uint8_t>(h.size() & 0xFF));
    b.push_back(static_cast<std::uint8_t>(h.size() >> 8));
    b.insert(b.end(), h.begin(), h.end());
    b.insert(b.end(), data.begin(), data.end());
    return b;
}

template <class T>
std::vector<std::uint8_t> bytes_of(std::initializer_list<T> v) {
    std::vector<std::uint8_t> b(v.size() * sizeof(T));
    std::memcpy(b.data(), std::data(v), b.size());
    return b;
}

}  // namespace

class TestData : public QObject {
    Q_OBJECT

private slots:
    void float64Vector() {
        const auto b = npy("'<f8'", false, "(3,)", bytes_of<double>({1.5, -2.0, 1e-30}));
        const auto a = parse_npy(b.data(), b.size());
        QCOMPARE(a.kind, 'f');
        QCOMPARE(a.shape, std::vector<std::size_t>({3}));
        QCOMPARE(a.to_doubles(), std::vector<double>({1.5, -2.0, 1e-30}));
    }

    void fortranOrderIsReturnedInCOrder() {
        // logical [[1,2,3],[4,5,6]] stored column-major: 1,4,2,5,3,6
        const auto b = npy("'<i8'", true, "(2, 3)", bytes_of<std::int64_t>({1, 4, 2, 5, 3, 6}));
        const auto a = parse_npy(b.data(), b.size());
        QVERIFY(a.fortran_order);
        QCOMPARE(a.to_doubles(), std::vector<double>({1, 2, 3, 4, 5, 6}));
    }

    void zeroDimensionalScalar() {
        const auto b = npy("'<i8'", false, "()", bytes_of<std::int64_t>({2}));
        const auto a = parse_npy(b.data(), b.size());
        QVERIFY(a.shape.empty());
        QCOMPARE(a.scalar(), 2.0);
    }

    void emptyArray() {
        const auto b = npy("'<f8'", false, "(0,)", {});
        const auto a = parse_npy(b.data(), b.size());
        QCOMPARE(a.count(), std::size_t(0));
        QVERIFY(a.to_doubles().empty());
    }

    void boolAndUnsigned() {
        const auto b = npy("'|b1'", false, "(3,)", {1, 0, 1});
        QCOMPARE(parse_npy(b.data(), b.size()).to_doubles(), std::vector<double>({1, 0, 1}));
        const auto u = npy("'|u1'", false, "(2,)", {7, 255});
        QCOMPARE(parse_npy(u.data(), u.size()).to_doubles(), std::vector<double>({7, 255}));
    }

    void unicodeStripsTrailingNulsAndEncodesUtf8() {
        // "cm^-3" in a <U6 (one trailing NUL) and "µm" (U+00B5) + 4 NULs
        std::vector<std::uint8_t> d;
        auto put = [&](char32_t c) {
            for (int k = 0; k < 4; ++k) d.push_back(static_cast<std::uint8_t>((c >> (8 * k)) & 0xFF));
        };
        for (char32_t c : std::u32string(U"cm^-3")) put(c);
        put(0);
        put(0x00B5);
        put(U'm');
        for (int k = 0; k < 4; ++k) put(0);
        const auto b = npy("'<U6'", false, "(2,)", d);
        const auto s = parse_npy(b.data(), b.size()).to_strings();
        QCOMPARE(s.size(), std::size_t(2));
        QCOMPARE(s[0], std::string("cm^-3"));
        QCOMPARE(s[1], std::string("\xC2\xB5m"));
    }

    void rejectsWhatTheGrammarNeverWrites_data() {
        QTest::addColumn<QString>("descr");
        QTest::addColumn<QString>("needle");
        QTest::newRow("pickled object") << "'|O'" << "pickled";
        QTest::newRow("big-endian") << "'>f8'" << "big-endian";
        QTest::newRow("structured") << "[('a', '<f8')]" << "structured";
        QTest::newRow("complex") << "'<c16'" << "unsupported dtype";
    }
    void rejectsWhatTheGrammarNeverWrites() {
        QFETCH(QString, descr);
        QFETCH(QString, needle);
        const auto b = npy(descr.toStdString(), false, "(1,)", std::vector<std::uint8_t>(16, 0));
        try {
            parse_npy(b.data(), b.size());
            QFAIL("expected NpzError");
        } catch (const NpzError& e) {
            QVERIFY2(QString(e.what()).contains(needle), e.what());
        }
    }

    void rejectsTruncatedData() {
        const auto b = npy("'<f8'", false, "(3,)", bytes_of<double>({1.0, 2.0}));
        QVERIFY_THROWS_EXCEPTION(NpzError, parse_npy(b.data(), b.size()));
    }

    void rejectsBadMagic() {
        std::vector<std::uint8_t> b(64, 0);
        QVERIFY_THROWS_EXCEPTION(NpzError, parse_npy(b.data(), b.size()));
    }

    void rejectsNonZipArchive() {
        const std::vector<std::uint8_t> junk(100, 'x');
        QVERIFY_THROWS_EXCEPTION(NpzError, tcad::desktop::NpzFile::from_bytes(junk));
    }

    void specDocumentIsLosslessAndTyped() {
        const std::string text =
            R"({"mesh": {"dimensionality": 2, "axes": {"x": [0.0, 1e-4], "y": [0.0, 5e-5, 1e-4]}},)"
            R"( "doping": {"kind": "array", "values": [[1, 2], [3, 4], [5, 6]]},)"
            R"( "contacts": [{"name": "anode"}, {"name": "cathode"}], "future_key": {"z": [1, 2]}})";
        const auto d = DeviceSpecDocument::parse(text);
        QCOMPARE(d.dimensionality(), 2);
        QCOMPARE(d.mesh_axis(1).size(), std::size_t(3));
        QVERIFY(d.mesh_axis(2).empty());
        QCOMPARE(d.contact_names(), std::vector<std::string>({"anode", "cathode"}));
        QCOMPARE(d.backend(), std::string("pytcad"));
        const auto again = DeviceSpecDocument::parse(d.dump());
        // QVERIFY, not QCOMPARE: QTest's printers probe json's implicit
        // conversions and trip over Qt's forward-declared Win32 MSG.
        QVERIFY(again.json() == d.json());
        QVERIFY(again.json().contains("future_key"));
        QCOMPARE(again.json().begin().key(), std::string("mesh"));  // key order kept
    }

    void specDocumentRejectsNonSpecs() {
        QVERIFY_THROWS_EXCEPTION(std::exception, DeviceSpecDocument::parse("[1, 2]"));
        QVERIFY_THROWS_EXCEPTION(std::exception, DeviceSpecDocument::parse(R"({"mesh": {}})"));
        QVERIFY_THROWS_EXCEPTION(std::exception, DeviceSpecDocument::parse("{not json"));
    }

    // Python's json.dumps writes NaN/Infinity/-Infinity; json.loads reads them.
    void pythonJsonReadsNonFiniteTokens() {
        const auto j = parse_python_json(R"({"a": NaN, "b": Infinity, "c": -Infinity, "d": [NaN]})");
        QVERIFY(j["a"].is_null());
        QVERIFY(j["b"].is_null());
        QVERIFY(j["c"].is_null());
        QVERIFY(j["d"][0].is_null());
    }

    void pythonJsonLeavesStringLiteralsAlone() {
        // Ordinary (not raw) literals: moc mis-lexes a raw string holding \" and
        // then emits no metaobject for this class.
        const auto j = parse_python_json("{\"note\": \"NaN \\\"Infinity\\\" -Infinity\\\\\", \"k\": 1}");
        QCOMPARE(j["note"].get<std::string>(), std::string("NaN \"Infinity\" -Infinity\\"));
        QCOMPARE(j["k"].get<int>(), 1);
        QCOMPARE(replace_nonfinite_tokens(R"(["NaN", NaN])"), std::string(R"(["NaN", null])"));
    }

    void pythonJsonRejectsWhatPythonRejects() {
        QVERIFY_THROWS_EXCEPTION(PyJsonError, parse_python_json("{not json"));
        QVERIFY_THROWS_EXCEPTION(PyJsonError, parse_python_json("nan"));  // lowercase is not a token
        QVERIFY_THROWS_EXCEPTION(PyJsonError, parse_python_json("[1,]"));
    }

    // isinstance(True, int) is True in Python; 2.0 is a float.
    void pythonIntIncludesBool() {
        QVERIFY(is_python_int(parse_python_json("2")));
        QVERIFY(is_python_int(parse_python_json("true")));
        QVERIFY(!is_python_int(parse_python_json("2.0")));
        QVERIFY(!is_python_int(parse_python_json(R"("2")")));
    }
};

QTEST_APPLESS_MAIN(TestData)
#include "test_data.moc"
