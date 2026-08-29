"""Builder controller (M5): parametric templates -> existing Structure
workbench.  Builds an AUTHORED DomainDevice via the domain-core
template, converts it through the standard adapter, and hands the
result to AppController.adoptStructure() -- so every editing,
validation, rendering and Run behavior of the Structure workbench
applies unchanged.  No second device-editing path exists."""
from PySide6.QtCore import QObject, Property, Signal, Slot

from workbench.core.templates import get_template, list_templates


class BuilderController(QObject):
    buildCompleted = Signal(str)             # template title
    buildError = Signal(str, str)            # summary, details
    paramsChanged = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._tid = list_templates()[0]
        self._values = {}

    @Property(list, constant=True)
    def templateIds(self):
        return list_templates()

    @Slot(str)
    def selectTemplate(self, tid):
        try:
            get_template(tid)
        except KeyError as exc:
            # a raw KeyError across the QML boundary is just a console
            # warning -- surface it through the builder's error channel
            self.buildError.emit("Unknown template", str(exc))
            return
        self._tid = tid
        self._values = {}
        self.paramsChanged.emit()

    @Slot(result=str)
    def selectedTemplateId(self):
        return self._tid

    @Slot(result="QVariant")
    def selectedParams(self):
        t = get_template(self._tid)
        return [{"name": p.name, "label": f"{p.label} [{p.unit}]",
                 "value": repr(self._values.get(p.name, p.default))}
                for p in t.params]

    @Slot(str, str)
    def setParameterValue(self, name, text):
        """Store a parameter edit.  Parsing happens here; full validation
        (ranges, unknown names) is the template's build() contract."""
        try:
            value = float(text)
        except (TypeError, ValueError):
            self.buildError.emit(
                f"Parameter '{name}' must be a number", f"got {text!r}")
            return
        self._values[name] = value

    @Slot()
    def build(self):
        template = get_template(self._tid)
        try:
            device = template.build(self._values)
        except ValueError as exc:
            self.buildError.emit("Cannot build device", str(exc))
            return
        from workbench.adapters.spec import structure_from_domain
        structure, mesh_model = structure_from_domain(device)
        self._app.adoptStructure(structure, mesh_model, template.title)
        self.buildCompleted.emit(template.title)
