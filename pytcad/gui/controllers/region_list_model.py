"""Read-only QAbstractListModel view onto StructureModel.regions.
AppController owns mutation (through the undo stack); this model just
mirrors whatever StructureModel currently holds, refreshed via
refresh()."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class RegionListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    BoundsRole = Qt.UserRole + 3
    DopingRole = Qt.UserRole + 4
    PriorityRole = Qt.UserRole + 5
    MaterialRole = Qt.UserRole + 6
    DopingProfileRole = Qt.UserRole + 7
    ProfilePeakRole = Qt.UserRole + 8
    ProfileSigmaYRole = Qt.UserRole + 9
    ProfileSigmaLatRole = Qt.UserRole + 10
    ProfileEdgeXRole = Qt.UserRole + 11
    ProfileHighSideRole = Qt.UserRole + 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self._regions = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._regions)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._regions[index.row()]
        if role in (Qt.DisplayRole, self.NameRole):
            return r.name
        if role == self.IdRole:
            return r.id
        if role == self.BoundsRole:
            return [r.x_min, r.x_max, r.y_min, r.y_max]
        if role == self.DopingRole:
            return r.net_doping_cm3
        if role == self.MaterialRole:
            return r.material
        if role == self.DopingProfileRole:
            return r.doping_profile
        if role == self.ProfilePeakRole:
            return r.profile_peak_cm3
        if role == self.ProfileSigmaYRole:
            return r.profile_sigma_y
        if role == self.ProfileSigmaLatRole:
            return r.profile_sigma_lat
        if role == self.ProfileEdgeXRole:
            return r.profile_edge_x
        if role == self.ProfileHighSideRole:
            return r.profile_high_side
        if role == self.PriorityRole:
            # compositing priority IS list position: regions.py's
            # rasterize_doping applies regions in list order, later
            # overwrites earlier. Row index doubles as a 1-based rank so
            # QML can show it without the model owning any extra state.
            return index.row() + 1
        return None

    def roleNames(self):
        return {self.IdRole: b"regionId", self.NameRole: b"name",
                self.BoundsRole: b"bounds", self.DopingRole: b"doping",
                self.PriorityRole: b"priority",
                self.MaterialRole: b"material",
                self.DopingProfileRole: b"dopingProfile",
                self.ProfilePeakRole: b"profilePeak",
                self.ProfileSigmaYRole: b"profileSigmaY",
                self.ProfileSigmaLatRole: b"profileSigmaLat",
                self.ProfileEdgeXRole: b"profileEdgeX",
                self.ProfileHighSideRole: b"profileHighSide"}

    def refresh(self, regions):
        self.beginResetModel()
        self._regions = list(regions)
        self.endResetModel()
