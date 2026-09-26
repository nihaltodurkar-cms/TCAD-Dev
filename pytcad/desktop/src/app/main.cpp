// tcad_desktop -- the native desktop shell (NATIVE-DESKTOP-PLAN.md).
//
//   tcad_desktop [--settings <file.ini>] [result.npz]
//   tcad_desktop --bench <result.npz> [--frames N] [--json out.json]
//   tcad_desktop --selftest <a.npz> [<b.npz> ...]   (exit 0 only if every check passed)
//   tcad_desktop --soak <a.npz> [<b.npz> ...] [--cycles N]   (memory and GL over N cycles)
//   --size WxH sets the view's logical size for --bench / --selftest.
// The theme (Fusion + palette from src/theme) is applied by MainWindow.
#include "bench/bench.hpp"
#include "bench/bench_backend.hpp"
#include "bench/selftest.hpp"
#include "shell/main_window.hpp"
#include "views/colormaps.hpp"

#include <vtkLookupTable.h>
#include <vtkNew.h>

#include <QApplication>
#include <QSurfaceFormat>
#include <QVTKOpenGLNativeWidget.h>

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <iostream>

int main(int argc, char** argv) {
    const double process_start = tcad::desktop::process_start_epoch_s();
    QSurfaceFormat::setDefaultFormat(QVTKOpenGLNativeWidget::defaultFormat());
    QApplication app(argc, argv);
    QApplication::setApplicationName("PyTCAD Desktop");

    const QStringList args = app.arguments();
    auto option = [&](const char* name) -> QString {  // the value after --name, or ""
        const int i = static_cast<int>(args.indexOf(name));
        return (i >= 0 && i + 1 < args.size()) ? args[i + 1] : QString();
    };
    const int selftest = static_cast<int>(args.indexOf("--selftest"));
    const int bench = static_cast<int>(args.indexOf("--bench"));

    // --lut-probe <map> <lo> <hi> <v>...: the colour VTK's lookup table
    // gives each value (S5b contract: equal to matplotlib's cmap(Normalize)).
    if (const int lp = static_cast<int>(args.indexOf("--lut-probe")); lp >= 0) {
        if (lp + 3 >= args.size()) {
            std::cerr << "--lut-probe needs <map> <lo> <hi> [values...]" << std::endl;
            return 1;
        }
        const auto map = tcad::desktop::colorMapFromName(args[lp + 1].toStdString());
        if (!map) {
            std::cerr << "unknown colour map " << args[lp + 1].toStdString() << std::endl;
            return 1;
        }
        vtkNew<vtkLookupTable> lut;
        tcad::desktop::fill_lut(lut, *map);  // over [0, 1]: the views' own path
        const double lo = args[lp + 2].toDouble(), hi = args[lp + 3].toDouble();
        nlohmann::json out = nlohmann::json::array();
        for (int i = lp + 4; i < args.size(); ++i) {
            double rgb[3];
            lut->GetColor(tcad::desktop::lut_input(args[i].toDouble(), lo, hi), rgb);
            out.push_back({rgb[0], rgb[1], rgb[2]});
        }
        std::cout << out.dump() << std::endl;
        return 0;
    }

    // --bench-backend <npz> [--repeats N]: no window, just the backend.
    if (const int bb = static_cast<int>(args.indexOf("--bench-backend")); bb >= 0) {
        if (bb + 1 >= args.size()) {
            std::cerr << "--bench-backend needs a result file" << std::endl;
            return 1;
        }
        tcad::desktop::BackendBenchOptions o;
        o.result_path = args[bb + 1];
        if (const QString n = option("--repeats"); !n.isEmpty()) o.repeats = std::max(1, n.toInt());
        o.warm = args.contains("--warm");
        try {
            std::cout << tcad::desktop::run_backend_benchmark(o).dump(2) << std::endl;
        } catch (const std::exception& e) {
            std::cout << nlohmann::json{{"error", e.what()}}.dump() << std::endl;
            return 2;
        }
        return 0;
    }
    // --size WxH: the FieldView's logical size for --bench / --selftest
    // (the HiDPI runs need one that fits the screen at 2x, section 15.13).
    int width = 1200, height = 800;
    if (const QString size = option("--size"); !size.isEmpty()) {
        const QStringList wh = size.split('x');
        if (wh.size() != 2 || wh[0].toInt() <= 0 || wh[1].toInt() <= 0) {
            std::cerr << "--size needs WxH, e.g. 600x360\n";
            return 1;
        }
        width = wh[0].toInt();
        height = wh[1].toInt();
    }

    // Measurement modes never read or write the user's settings.
    std::unique_ptr<tcad::desktop::AppSettings> settings;
    const int soak = static_cast<int>(args.indexOf("--soak"));
    if (selftest >= 0 || bench >= 0 || soak >= 0)
        settings = tcad::desktop::AppSettings::ephemeral();
    else if (const QString ini = option("--settings"); !ini.isEmpty())
        settings = tcad::desktop::AppSettings::atFile(ini);
    else
        settings = tcad::desktop::AppSettings::userDefault();
    tcad::desktop::MainWindow window(std::move(settings));

    if (selftest >= 0) {
        tcad::desktop::SelftestOptions o;
        o.width = width;
        o.height = height;
        for (int i = selftest + 1; i < args.size() && !args[i].startsWith("--"); ++i) o.result_paths << args[i];
        if (o.result_paths.isEmpty()) {
            std::cerr << "--selftest needs at least one result file\n";
            return 1;
        }
        nlohmann::ordered_json result;
        try {
            result = tcad::desktop::run_selftest(window, o);
        } catch (const std::exception& e) {
            std::cout << nlohmann::json{{"ok", false}, {"error", e.what()}}.dump() << "\n";
            return 2;
        }
        std::cout << result.dump(2) << "\n";
        return result["ok"].get<bool>() ? 0 : 3;
    }

    if (soak >= 0) {
        QStringList files;
        for (int i = soak + 1; i < args.size() && !args[i].startsWith("--"); ++i) files << args[i];
        const int ci = static_cast<int>(args.indexOf("--cycles"));
        const int cycles = ci >= 0 && ci + 1 < args.size() ? args[ci + 1].toInt() : 30;
        if (files.isEmpty() || cycles < 2) {
            std::cerr << "--soak needs result files and --cycles >= 2\n";
            return 1;
        }
        nlohmann::ordered_json result;
        try {
            result = tcad::desktop::run_soak(window, files, cycles, width, height);
        } catch (const std::exception& e) {
            std::cout << nlohmann::json{{"ok", false}, {"error", e.what()}}.dump() << "\n";
            return 2;
        }
        std::cout << result.dump() << "\n";
        return result["ok"].get<bool>() ? 0 : 3;
    }

    if (bench >= 0) {
        if (bench + 1 >= args.size()) {
            std::cerr << "--bench needs a result file\n";
            return 1;
        }
        tcad::desktop::BenchOptions o;
        o.width = width;
        o.height = height;
        o.result_path = args[bench + 1];
        o.process_start_s = process_start;
        const int frames = static_cast<int>(args.indexOf("--frames"));
        if (frames >= 0 && frames + 1 < args.size()) o.frames = args[frames + 1].toInt();
        nlohmann::ordered_json result;
        try {
            result = tcad::desktop::run_benchmark(window, o);
        } catch (const std::exception& e) {
            std::cout << nlohmann::json{{"error", e.what()}}.dump() << "\n";
            return 2;
        }
        const int json = static_cast<int>(args.indexOf("--json"));
        if (json >= 0 && json + 1 < args.size()) {
            std::ofstream(args[json + 1].toStdWString()) << result.dump(2) << "\n";
        }
        std::cout << result.dump(2) << "\n";
        return 0;
    }

    window.show();
    // The positional argument: the first one that is neither an --option
    // nor an option's value.
    for (int i = 1; i < args.size(); ++i) {
        if (args[i] == "--settings" || args[i] == "--size") {
            ++i;
            continue;
        }
        if (args[i].startsWith("--")) continue;
        window.tryOpen(args[i]);  // a failure is reported in the window
        break;
    }
    return app.exec();
}
