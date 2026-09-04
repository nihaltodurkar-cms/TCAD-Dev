"""QML architecture cleanup: ThemedSpinBox.qml / ThemedComboBox.qml,
the shared "sunken input" background styling factored out of the
per-editor duplicated blocks (MeshEditor, DopingEditor, GateEditor,
OxidizeEditor, ImplantEditor -- 12 near-identical ~8-line Rectangle
blocks before this change). Pure visual extraction, no new behavior:
these tests just confirm the components instantiate correctly and
still behave like a real SpinBox/ComboBox (value/from/to, model),
since every editor's own existing tests already cover the actual
field-editing behavior and are the real regression gate for this
refactor.
"""
import os

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

QML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml"
)


def _make(qml_engine, qml_text, filename):
    component = QQmlComponent(qml_engine)
    component.setData(
        qml_text.encode("utf-8"),
        QUrl.fromLocalFile(os.path.join(QML_DIR, filename)),
    )
    obj = component.create()
    assert obj is not None, component.errorString()
    assert component.errorString() == ""
    # See test_theme_tokens.py's _make_probe: the component must
    # outlive the object it created.
    obj._keepalive_component = component
    return obj


def test_themed_spinbox_behaves_like_a_real_spinbox_with_default_width():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    obj = _make(engine, """
        import QtQuick
        import "components"
        ThemedSpinBox { from: 2; to: 2000; value: 80 }
    """, "_probe_spinbox.qml")
    assert obj.property("value") == 80
    assert obj.property("from") == 2
    assert obj.property("to") == 2000
    assert obj.property("fieldWidth") == 70


def test_themed_spinbox_field_width_is_overridable():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    obj = _make(engine, """
        import QtQuick
        import "components"
        ThemedSpinBox { fieldWidth: 90; from: -100000; to: 100000 }
    """, "_probe_spinbox_width.qml")
    assert obj.property("fieldWidth") == 90


def test_themed_combobox_behaves_like_a_real_combobox():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    obj = _make(engine, """
        import QtQuick
        import "components"
        ThemedComboBox { model: ["uniform", "graded"] }
    """, "_probe_combobox.qml")
    raw = obj.property("model")
    model = raw.toVariant() if hasattr(raw, "toVariant") else list(raw)
    assert list(model) == ["uniform", "graded"]
