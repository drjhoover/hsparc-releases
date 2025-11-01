# hsparc/ui/stream_alias.py
from __future__ import annotations

from typing import Optional
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QHBoxLayout, QPushButton, QMessageBox

from hsparc.models import db as dbm


class StreamAliasDialog(QDialog):
    """
    Rename (alias) a single InputStream.
    """
    def __init__(self, parent=None, stream_id: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Rename Source")
        self.resize(420, 160)
        self.stream_id = stream_id

        with dbm.get_session() as s:
            self.stream = s.query(dbm.InputStream).filter_by(id=stream_id).first()
            if not self.stream:
                QMessageBox.critical(self, "Not found", "Input stream not found.")
                self.reject(); return
            current = self.stream.alias or self.stream.device_name or "Source"

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Enter a friendly name for this source (e.g., “Client A controller”)."))
        self.edt = QLineEdit(current)
        lay.addWidget(self.edt)

        row = QHBoxLayout()
        self.btn_save = QPushButton("Save"); self.btn_cancel = QPushButton("Cancel")
        row.addStretch(1); row.addWidget(self.btn_save); row.addWidget(self.btn_cancel)
        lay.addLayout(row)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._save)

    def _save(self):
        name = (self.edt.text() or "").strip()
        with dbm.get_session() as s:
            st = s.query(dbm.InputStream).filter_by(id=self.stream_id).first()
            if not st:
                QMessageBox.critical(self, "Not found", "Input stream not found.")
                return
            st.alias = name or None
            s.commit()
        self.accept()
