from __future__ import annotations

import json
from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHBoxLayout, QPushButton, QMessageBox, QInputDialog
)

from hsparc.models import db as dbm


COMMON_GAMEPAD_CODES = [
    # Axes (sticks/triggers)
    "ABS_X","ABS_Y","ABS_RX","ABS_RY","ABS_Z","ABS_RZ",
    # D-Pad
    "ABS_HAT0X","ABS_HAT0Y",
    # Face / shoulders / start/select / sticks
    "BTN_SOUTH","BTN_EAST","BTN_WEST","BTN_NORTH",
    "BTN_TL","BTN_TR","BTN_SELECT","BTN_START",
    "BTN_THUMBL","BTN_THUMBR",
]

HIDE_SENTINEL = "__HIDE__"   # if a label equals this, plots/exports will ignore that code


def _load_mapping_value(raw) -> Dict[str, str]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v is not None}
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return {str(k): str(v) for k, v in d.items() if v is not None}
    except Exception:
        pass
    return {}


class ControlMapDialog(QDialog):
    """
    Per-stream mapping of control codes -> construct labels.
    Hiding: set label to HIDE_SENTINEL to exclude from plots/exports.
    """
    def __init__(self, parent, *, stream_id: str):
        super().__init__(parent)
        self.setWindowTitle("Map controls to constructs")
        self.resize(680, 520)
        self._stream_id = stream_id

        layout = QVBoxLayout(self)

        st_name = self._stream_display_name(stream_id)
        hdr_txt = f"Stream: {st_name}\nAssign labels to each control code. Rows marked '{HIDE_SENTINEL}' are hidden."
        self._hdr = QLabel(hdr_txt)
        self._hdr.setWordWrap(True)
        layout.addWidget(self._hdr)

        codes = self._collect_codes_for_stream(stream_id)
        self._table = QTableWidget(max(1, len(codes)), 2)
        self._table.setHorizontalHeaderLabels(["Control code", "Construct label (or __HIDE__)"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self._table, 1)

        existing = self._load_existing_mapping(stream_id)

        if codes:
            self._table.setRowCount(len(codes))
            for r, code in enumerate(sorted(codes)):
                self._set_row(r, code, existing.get(code, ""))
        else:
            warn = QLabel("No controller events were found yet for this stream.\n"
                          "You can preload common gamepad controls or add codes manually.")
            warn.setStyleSheet("color:#666;")
            layout.addWidget(warn)
            self._table.setRowCount(1)
            self._set_row(0, "", "")

        # Buttons
        row = QHBoxLayout()
        self._btn_load_common = QPushButton("Load common gamepad controls")
        self._btn_add_code    = QPushButton("Add code…")
        self._btn_hide        = QPushButton("Hide selected")
        self._btn_unhide      = QPushButton("Unhide selected")
        self._btn_clear       = QPushButton("Clear labels")
        self._btn_save        = QPushButton("Save")
        self._btn_cancel      = QPushButton("Cancel")
        row.addWidget(self._btn_load_common)
        row.addWidget(self._btn_add_code)
        row.addStretch(1)
        row.addWidget(self._btn_hide)
        row.addWidget(self._btn_unhide)
        row.addWidget(self._btn_clear)
        row.addWidget(self._btn_save)
        row.addWidget(self._btn_cancel)
        layout.addLayout(row)

        # Wire
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_clear.clicked.connect(self._clear_all)
        self._btn_save.clicked.connect(self._save)
        self._btn_load_common.clicked.connect(self._load_common_rows)
        self._btn_add_code.clicked.connect(self._add_code_dialog)
        self._btn_hide.clicked.connect(self._hide_selected)
        self._btn_unhide.clicked.connect(self._unhide_selected)

    # --- helpers ---
    def _stream_display_name(self, stream_id: str) -> str:
        with dbm.get_session() as s:
            st = s.query(dbm.InputStream).filter_by(id=stream_id).first()
            if not st:
                return "(missing)"
            base = st.alias or st.device_name or "Source"
            return f"{base} — {st.id[:8]}"

    def _collect_codes_for_stream(self, stream_id: str) -> List[str]:
        codes: set[str] = set()
        with dbm.get_session() as s:
            evs = (s.query(dbm.InputEvent.code, dbm.InputEvent.kind)
                     .filter(dbm.InputEvent.stream_id == stream_id)
                     .distinct()
                     .all())
            for code, _ in evs:
                if code:
                    codes.add(code)
        return sorted(codes)

    def _load_existing_mapping(self, stream_id: str) -> Dict[str, str]:
        with dbm.get_session() as s:
            st = s.query(dbm.InputStream).filter_by(id=stream_id).first()
            if not st:
                return {}
            return _load_mapping_value(st.construct_mapping)

    def _set_row(self, row: int, code: str, label: str):
        it_code = QTableWidgetItem(code)
        if code:
            it_code.setFlags(it_code.flags() & ~Qt.ItemIsEditable)
        self._table.setItem(row, 0, it_code)
        self._table.setItem(row, 1, QTableWidgetItem(label))

    def _append_or_select_code(self, code: str):
        # if already present, select it; else append new row
        for r in range(self._table.rowCount()):
            it = self._table.item(r, 0)
            if it and it.text() == code:
                self._table.selectRow(r)
                return
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._set_row(r, code, "")
        self._table.selectRow(r)

    # --- UI actions ---
    def _clear_all(self):
        for r in range(self._table.rowCount()):
            if self._table.item(r, 1):
                self._table.item(r, 1).setText("")

    def _load_common_rows(self):
        existing_rows = set()
        for r in range(self._table.rowCount()):
            cell = self._table.item(r, 0)
            if cell and cell.text():
                existing_rows.add(cell.text())
        merged = sorted(existing_rows.union(COMMON_GAMEPAD_CODES))
        # rebuild rows with merged codes, keeping current labels when possible
        current = {}
        for r in range(self._table.rowCount()):
            c = self._table.item(r, 0).text() if self._table.item(r, 0) else ""
            v = self._table.item(r, 1).text() if self._table.item(r, 1) else ""
            if c: current[c] = v
        self._table.setRowCount(len(merged))
        for r, code in enumerate(merged):
            self._set_row(r, code, current.get(code, ""))

    def _add_code_dialog(self):
        code, ok = QInputDialog.getText(self, "Add control code", "Enter a control code (e.g., ABS_Y, BTN_SOUTH):")
        if not ok: return
        code = (code or "").strip()
        if not code: return
        self._append_or_select_code(code)

    def _hide_selected(self):
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "Hide", "Select one or more rows first.")
            return
        if QMessageBox.question(self, "Hide selected",
                                "Hide the selected control code(s) from plots and exports?\n"
                                "This does NOT delete raw data; you can unhide later.") != QMessageBox.Yes:
            return
        for r in rows:
            lab = self._table.item(r, 1)
            if lab is None:
                self._table.setItem(r, 1, QTableWidgetItem(HIDE_SENTINEL))
            else:
                lab.setText(HIDE_SENTINEL)

    def _unhide_selected(self):
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "Unhide", "Select one or more rows first.")
            return
        for r in rows:
            lab = self._table.item(r, 1)
            if lab:
                if lab.text().strip() == HIDE_SENTINEL:
                    lab.setText("")

    def _save(self):
        mapping: Dict[str, str] = {}
        for r in range(self._table.rowCount()):
            code_item = self._table.item(r, 0)
            label_item = self._table.item(r, 1)
            code = (code_item.text() if code_item else "").strip()
            if not code:
                continue
            label = (label_item.text() if label_item else "").strip()
            if label:  # include both regular labels and HIDE sentinel
                mapping[code] = label
            else:
                # empty label means "use raw code" (not hidden)
                mapping[code] = ""
        try:
            with dbm.get_session() as s:
                st = s.query(dbm.InputStream).filter_by(id=self._stream_id).first()
                if not st:
                    QMessageBox.warning(self, "Missing", "Input stream not found.")
                    return
                st.construct_mapping = json.dumps(mapping, ensure_ascii=False)
                s.commit()
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"Could not save mapping:\n{e}")
