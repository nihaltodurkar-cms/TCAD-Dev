#include "info_panel.hpp"

#include "data/result_model.hpp"

#include <QFileInfo>
#include <QHeaderView>
#include <QLocale>

namespace tcad::desktop {
namespace {

QString qs(const std::string& s) { return QString::fromStdString(s); }

QString json_text(const nlohmann::ordered_json& j) {
    if (j.is_string()) return qs(j.get<std::string>());
    if (j.is_null()) return QString();
    return qs(j.dump());
}

}  // namespace

InfoPanel::InfoPanel(QWidget* parent) : QTreeWidget(parent) {
    setObjectName("InfoTree");
    setColumnCount(2);
    setHeaderLabels({tr("Property"), tr("Value")});
    setRootIsDecorated(true);
    setUniformRowHeights(true);
    setSelectionMode(QAbstractItemView::SingleSelection);
    header()->setSectionResizeMode(0, QHeaderView::ResizeToContents);
    header()->setStretchLastSection(true);
}

void InfoPanel::showResult(const ResultModel* m, const QString& path) {
    clear();
    if (!m) return;
    auto group = [this](const QString& name) {
        auto* g = new QTreeWidgetItem(this, {name});
        g->setFirstColumnSpanned(true);
        g->setExpanded(true);
        return g;
    };
    auto row = [](QTreeWidgetItem* g, const QString& k, const QString& v) {
        auto* r = new QTreeWidgetItem(g, {k, v});
        r->setToolTip(1, v);
        return r;
    };
    const QLocale c = QLocale::c();

    const QFileInfo fi(path);
    auto* file = group(tr("File"));
    row(file, tr("Name"), fi.fileName())->setToolTip(1, fi.absoluteFilePath());
    row(file, tr("Size"), QLocale().formattedDataSize(fi.size()));
    row(file, tr("Schema"), QString::number(m->schema_version()));

    auto* mesh = group(tr("Mesh"));
    const auto n = m->node_counts();
    row(mesh, tr("Dimensionality"), QString("%1D").arg(m->dimensionality()));
    QStringList dims;
    std::size_t total = 1;
    for (int a = 0; a < m->dimensionality(); ++a) {
        dims << QString::number(n[static_cast<std::size_t>(a)]);
        total *= n[static_cast<std::size_t>(a)];
    }
    row(mesh, tr("Nodes"), QString("%1 = %2").arg(dims.join(QString::fromUtf8(" \xC3\x97 ")), c.toString(static_cast<qulonglong>(total))));
    static const char* kAxis[3] = {"x", "y", "z"};
    for (int a = 0; a < m->dimensionality(); ++a) {
        const auto& ax = m->axis(a);
        row(mesh, QString("%1 range").arg(kAxis[a]),
            QString("%1 .. %2 um").arg(ax.front() * 1e4, 0, 'g', 6).arg(ax.back() * 1e4, 0, 'g', 6));
    }
    const std::string kind = m->geometry_kind();
    row(mesh, tr("Geometry"), kind.empty() ? tr("(not stamped)") : qs(kind));

    auto* fields = group(tr("Fields (%1)").arg(m->scalar_names().size()));
    for (const auto& name : m->scalar_names()) row(fields, qs(name), qs(m->scalar(name).unit));

    if (!m->vector_names().empty()) {
        auto* vectors = group(tr("Vectors (%1)").arg(m->vector_names().size()));
        for (const auto& name : m->vector_names()) row(vectors, qs(name), qs(m->vector(name).unit));
    }
    if (!m->terminal_names().empty()) {
        auto* terms = group(tr("Terminals (%1)").arg(m->terminal_names().size()));
        for (const auto& name : m->terminal_names()) {
            const Terminal t = m->terminal(name);
            row(terms, qs(name), QString("%1 %2").arg(t.value, 0, 'e', 4).arg(qs(t.unit)));
        }
    }

    auto* run = group(tr("Run"));
    row(run, tr("Bias solved"), m->solved_bias() ? tr("yes") : tr("no (equilibrium only)"));
    if (const auto rec = m->record()) {
        for (const char* key : {"backend", "created_utc", "material"})
            if (rec->contains(key)) row(run, QString::fromLatin1(key), json_text((*rec)[key]));
        if (rec->contains("T") && (*rec)["T"].is_number())
            row(run, "T", QString("%1 K").arg((*rec)["T"].get<double>(), 0, 'g', 6));
        if (rec->contains("models") && (*rec)["models"].is_object()) {
            QStringList on;
            for (const auto& [k, v] : (*rec)["models"].items())
                if (v.is_boolean() ? v.get<bool>() : !v.is_null()) on << qs(k);
            row(run, tr("Models on"), on.isEmpty() ? tr("(none)") : on.join(", "));
        }
    } else {
        row(run, tr("Record"), tr("(none: a pre-v2 file)"));
    }

    auto* blocks = group(tr("Blocks"));
    auto count = [&](const QString& what, std::size_t k) { row(blocks, what, k ? tr("%1 points").arg(k) : tr("none")); };
    count(tr("Sweep"), m->sweep_points());
    count(tr("Transient"), m->transient_points());
    count(tr("AC"), m->ac_points());
    if (m->has_sweep_snapshots()) {
        QString text;
        try {
            const auto s = m->sweep_snapshots();
            text = tr("%1 x %2 fields").arg(s.count()).arg(s.field_names.size());
        } catch (const std::exception& e) {
            text = tr("unreadable: %1").arg(QString::fromUtf8(e.what()));
        }
        row(blocks, tr("Snapshots"), text);
    }
}

QString InfoPanel::value(const QString& group, const QString& property) const {
    for (int i = 0; i < topLevelItemCount(); ++i) {
        const QTreeWidgetItem* g = topLevelItem(i);
        if (!g->text(0).startsWith(group)) continue;
        for (int j = 0; j < g->childCount(); ++j)
            if (g->child(j)->text(0) == property) return g->child(j)->text(1);
    }
    return {};
}

}  // namespace tcad::desktop
