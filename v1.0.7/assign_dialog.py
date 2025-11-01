
from __future__ import annotations

import os
import json
from typing import Optional, Dict, List
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QWidget, QDialogButtonBox, QFrame, QLineEdit
)

try:
    import evdev
    from evdev import ecodes
except Exception:
    evdev = None
    ecodes = None

@dataclass
class SlotData:
    realpath: Optional[str] = None
    pretty: Optional[str] = None
    vid: Optional[int] = None
    pid: Optional[int] = None
    phys: Optional[str] = None
    uniq: Optional[str] = None

class AssignControllersDialog(QDialog):
    """
    Assign controllers by *first input*. No auto-populate on discovery.
    Returns {"A": realpath_or_None, "B": realpath_or_None}.
    """
    def __init__(self, parent=None, title="Assign Controllers"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)

        if evdev is None:
            self._error = QLabel("evdev is not available. Cannot assign controllers on this system.")
            lay = QVBoxLayout(self); lay.addWidget(self._error)
            self._result = {"A": None, "B": None}
            return

        self.a = SlotData()
        self.b = SlotData()
        self._devices: List[evdev.InputDevice] = []
        self._timer = QTimer(self); self._timer.setInterval(20); self._timer.timeout.connect(self._poll_once)

        root = QVBoxLayout(self)

        root.addWidget(QLabel("Tap a button or move a stick on the controller to assign Participant A and B."))

        self.boxA = self._slot_group("Participant A")
        self.lblA = QLabel("—")
        self.btnClearA = QPushButton("Clear")
        self.btnClearA.clicked.connect(lambda: self._clear_slot("A"))
        self.boxA.layout().addWidget(self.lblA, 0, 0)
        self.boxA.layout().addWidget(self.btnClearA, 0, 1)
        self.nameA = QLineEdit(self); self.nameA.setPlaceholderText('Participant A name'); self.nameA.setText('Participant A')
        self.boxA.layout().addWidget(self.nameA, 1, 0, 1, 2)
        root.addWidget(self.boxA)

        self.boxB = self._slot_group("Participant B")
        self.lblB = QLabel("—")
        self.btnClearB = QPushButton("Clear")
        self.btnClearB.clicked.connect(lambda: self._clear_slot("B"))
        self.boxB.layout().addWidget(self.lblB, 0, 0)
        self.boxB.layout().addWidget(self.btnClearB, 0, 1)
        self.nameB = QLineEdit(self); self.nameB.setPlaceholderText('Participant B name'); self.nameB.setText('Participant B')
        self.boxB.layout().addWidget(self.nameB, 1, 0, 1, 2)
        root.addWidget(self.boxB)

        root.addWidget(self._hline())

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self._open_devices()
        self._timer.start()

    def _slot_group(self, title):
        gb = QGroupBox(title, self)
        gl = QGridLayout(gb); gl.setContentsMargins(8, 6, 8, 6)
        gb.setLayout(gl)
        return gb

    def _hline(self):
        line = QFrame(self); line.setFrameShape(QFrame.HLine); line.setFrameShadow(QFrame.Sunken)
        return line

    def _open_devices(self):
        # Prefer stable by-id links
        paths = []
        byid = "/dev/input/by-id"
        if os.path.isdir(byid):
            for name in os.listdir(byid):
                if name.endswith("-event-joystick"):
                    paths.append(os.path.join(byid, name))
        # Fallback: all event* devices
        if not paths:
            for p in os.listdir("/dev/input"):
                if p.startswith("event"):
                    paths.append(os.path.join("/dev/input", p))

        seen = set()
        for p in paths:
            try:
                dev = evdev.InputDevice(p)
                if dev.fd in seen:
                    continue
                self._devices.append(dev)
                seen.add(dev.fd)
            except Exception:
                continue

    def _fmt(self, dev: "evdev.InputDevice", realpath: str):
        try:
            info = dev.info
            vid = getattr(info, "vendor", None)
            pid = getattr(info, "product", None)
        except Exception:
            vid = pid = None
        return f"{dev.name or 'Gamepad'}  [{realpath}]  VID:PID={vid:04x}:{pid:04x}  phys={getattr(dev, 'phys', '-')}"

    def _poll_once(self):
        if evdev is None:
            return
        for d in list(self._devices):
            try:
                e = d.read_one()
            except Exception:
                continue
            if not e:
                continue
            if e.type not in (ecodes.EV_KEY, ecodes.EV_ABS):
                continue
            rp = os.path.realpath(d.path)
            if self.a.realpath is None:
                self.a.realpath = rp; self.a.pretty = d.name
                self.lblA.setText(self._fmt(d, rp))
            elif self.b.realpath is None and rp != self.a.realpath:
                self.b.realpath = rp; self.b.pretty = d.name
                self.lblB.setText(self._fmt(d, rp))

            # stop early if both assigned
            if self.a.realpath and self.b.realpath:
                break

    def _clear_slot(self, which: str):
        if which == "A":
            self.a = SlotData(); self.lblA.setText("—"); self.nameA.setText('Participant A')
        else:
            self.b = SlotData(); self.lblB.setText("—"); self.nameB.setText('Participant B')

    def get_result(self) -> Dict[str, Optional[dict]]:
        return {
            "A": {"path": self.a.realpath, "name": self.nameA.text().strip() or 'Participant A'} if self.a.realpath else None,
            "B": {"path": self.b.realpath, "name": self.nameB.text().strip() or 'Participant B'} if self.b.realpath else None,
        }

    @staticmethod
    def assign(parent=None, title="Assign Controllers") -> Dict[str, Optional[dict]]:
        """Assign controllers and optionally calibrate them."""
        print(f"[assign_dialog] assign() called with title: {title}")
        dlg = AssignControllersDialog(parent, title=title)
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            
            # Now calibrate each assigned controller
            from hsparc.ui.widgets.controller_calibration_dialog import ControllerCalibrationDialog
            
            for slot in ("A", "B"):
                ctrl = result.get(slot)
                if not ctrl or not ctrl.get("path"):
                    continue
                
                print(f"[assign_dialog] Starting calibration for {slot}: {ctrl['name']}")
                
                # Show calibration dialog
                cal_dialog = ControllerCalibrationDialog(
                    parent,
                    controller_path=ctrl["path"],
                    controller_name=ctrl["name"]
                )
                
                cal_state = None
                
                def on_calibration_complete(state):
                    nonlocal cal_state
                    cal_state = state
                
                cal_dialog.calibration_complete.connect(on_calibration_complete)
                
                if cal_dialog.exec() == QDialog.Accepted:
                    # Store calibration in result
                    ctrl["calibration"] = cal_state
                    print(f"[assign_dialog] Calibration completed for {slot}")
                else:
                    # User cancelled calibration - return empty result
                    print(f"[assign_dialog] Calibration cancelled for {slot}")
                    return {"A": None, "B": None}
            
            print(f"[assign_dialog] Returning result with calibrations")
            return result
        
        print(f"[assign_dialog] Dialog cancelled")
        return {"A": None, "B": None}