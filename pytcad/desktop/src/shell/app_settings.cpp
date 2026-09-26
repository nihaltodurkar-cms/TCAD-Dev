#include "app_settings.hpp"

#include <QDir>
#include <QFileInfo>
#include <QSettings>

namespace tcad::desktop {
namespace {

QString normalized(const QString& path) { return QDir::cleanPath(QFileInfo(path).absoluteFilePath()); }

}  // namespace

bool samePath(const QString& a, const QString& b) {
    return QString::compare(normalized(a), normalized(b), Qt::CaseInsensitive) == 0;
}

AppSettings::AppSettings(std::unique_ptr<QSettings> s) : settings_(std::move(s)) {}
AppSettings::~AppSettings() = default;

std::unique_ptr<AppSettings> AppSettings::userDefault() {
    return std::unique_ptr<AppSettings>(new AppSettings(
        std::make_unique<QSettings>(QSettings::IniFormat, QSettings::UserScope, "PyTCAD", "PyTCAD Desktop")));
}

std::unique_ptr<AppSettings> AppSettings::atFile(const QString& ini_path) {
    return std::unique_ptr<AppSettings>(new AppSettings(std::make_unique<QSettings>(ini_path, QSettings::IniFormat)));
}

std::unique_ptr<AppSettings> AppSettings::ephemeral() { return std::unique_ptr<AppSettings>(new AppSettings(nullptr)); }

bool AppSettings::writable() const {
    if (!settings_) return true;
    const QFileInfo f(settings_->fileName());
    if (f.exists()) return f.isWritable();
    return QFileInfo(f.absolutePath()).isWritable() || !QDir(f.absolutePath()).exists();
}

QString AppSettings::fileName() const { return settings_ ? settings_->fileName() : QString(); }

QStringList AppSettings::recentFiles() const {
    return settings_ ? settings_->value("recent/files").toStringList() : memory_recent_;
}

void AppSettings::setRecent(const QStringList& list) {
    if (settings_)
        settings_->setValue("recent/files", list);
    else
        memory_recent_ = list;
}

void AppSettings::addRecent(const QString& path) {
    QStringList list = recentFiles();
    list.removeIf([&](const QString& p) { return samePath(p, path); });
    list.prepend(normalized(path));
    while (list.size() > kMaxRecent) list.removeLast();
    setRecent(list);
}

void AppSettings::removeRecent(const QString& path) {
    QStringList list = recentFiles();
    list.removeIf([&](const QString& p) { return samePath(p, path); });
    setRecent(list);
}

void AppSettings::clearRecent() { setRecent({}); }

bool AppSettings::loadLayout(Layout* out) const {
    if (!settings_ || settings_->value("layout/version").toInt() != kLayoutVersion) return false;
    out->geometry = settings_->value("layout/geometry").toByteArray();
    out->docks = settings_->value("layout/docks").toByteArray();
    return !out->docks.isEmpty();
}

void AppSettings::saveLayout(const Layout& layout) {
    if (!settings_) return;
    settings_->setValue("layout/version", kLayoutVersion);
    settings_->setValue("layout/geometry", layout.geometry);
    settings_->setValue("layout/docks", layout.docks);
}

QString AppSettings::value(const QString& key, const QString& fallback) const {
    return settings_ ? settings_->value(key, fallback).toString() : fallback;
}

void AppSettings::setValue(const QString& key, const QString& v) {
    if (settings_) settings_->setValue(key, v);
}

bool AppSettings::sync() {
    if (!settings_) return true;
    settings_->sync();
    return settings_->status() == QSettings::NoError;
}

}  // namespace tcad::desktop
