# hsparc/ui/widgets/controller_calibration_dialog.py
"""
Controller Calibration Dialog

Allows users to:
1. Calibrate axis ranges (move joystick to extremes)
2. Detect and assign buttons
3. Assign construct labels to each input
4. Preview configured inputs

This creates a filtered, normalized input set for recording.
"""
from __future__ import annotations

import time
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QInputDialog, QMessageBox,
    QGroupBox, QProgressBar, QAbstractItemView
)

try:
    from evdev import InputDevice, ecodes
except ImportError:
    InputDevice = None
    ecodes = None


@dataclass
class AxisCalibration:
    """Calibration data for a single axis."""
    code: str  # e.g., "ABS_X"
    min_value: int = 999999
    max_value: int = -999999
    center_value: int = 0
    label: str = ""
    
    def normalize(self, raw_value: int) -> float:
        """Normalize raw value to -1.0 to 1.0 range."""
        if self.min_value == self.max_value:
            return 0.0
        
        # Map to 0-1 range
        normalized = (raw_value - self.min_value) / (self.max_value - self.min_value)
        
        # Map to -1 to 1 range
        return (normalized * 2.0) - 1.0


@dataclass
class ButtonCalibration:
    """Calibration data for a single button."""
    code: str  # e.g., "BTN_TRIGGER"
    label: str = ""


@dataclass
class CalibrationState:
    """Complete calibration state for a controller."""
    axes: Dict[str, AxisCalibration] = field(default_factory=dict)
    buttons: Dict[str, ButtonCalibration] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "axes": {
                code: {
                    "min": axis.min_value,
                    "max": axis.max_value,
                    "center": axis.center_value,
                    "label": axis.label
                }
                for code, axis in self.axes.items()
            },
            "buttons": {
                code: {"label": btn.label}
                for code, btn in self.buttons.items()
            }
        }
    
    def get_allowed_inputs(self) -> List[str]:
        """Get list of all configured input codes."""
        return list(self.axes.keys()) + list(self.buttons.keys())
    
    def get_construct_mapping(self) -> Dict[str, str]:
        """Get mapping of codes to labels for compatibility."""
        mapping = {}
        for code, axis in self.axes.items():
            if axis.label:
                mapping[code] = axis.label
        for code, btn in self.buttons.items():
            if btn.label:
                mapping[code] = btn.label
        return mapping


class ControllerCalibrationDialog(QDialog):
    """
    Dialog for calibrating a single controller.
    
    Workflow:
    1. User clicks "Add Axis..." or "Add Button..."
    2. System guides through calibration/detection
    3. User assigns construct label
    4. Input appears in configured list
    5. User clicks "Done" to finish
    """
    
    calibration_complete = Signal(object)  # Emits CalibrationState or None
    
    def __init__(
            self,
            parent=None,
            controller_path: str = None,
            controller_name: str = "Controller"
    ):
        super().__init__(parent)
        
        if InputDevice is None:
            QMessageBox.critical(
                self, "Error",
                "evdev library not available.\n"
                "Controller calibration requires evdev."
            )
            self.reject()
            return
        
        self.controller_path = controller_path
        self.controller_name = controller_name
        self.calibration = CalibrationState()
        
        # Device for polling
        self._device: Optional[InputDevice] = None
        self._poll_timer: Optional[QTimer] = None
        
        # Calibration workflow state
        self._calibrating_axis: Optional[str] = None
        self._axis_samples: List[int] = []
        self._detecting_button = False
        self._last_event_time = 0
        
        self.setWindowTitle(f"Calibrate: {controller_name}")
        self.setModal(True)
        self.resize(720, 580)
        
        self._setup_ui()
        self._open_device()
        self._start_polling()
    
    def _setup_ui(self):
        """Build the UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Header
        header = QLabel(f"<b style='font-size: 15px;'>Configure Inputs: {self.controller_name}</b>")
        header.setStyleSheet("padding: 8px; background: #f0f0f0; border-radius: 4px;")
        layout.addWidget(header)
        
        info = QLabel(
            "Add the joystick axes and buttons you want to record during the session.\n"
            "Each input will be assigned a construct label (e.g., 'Arousal', 'Valence', 'Engagement')."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; padding: 4px;")
        layout.addWidget(info)
        
        # Add buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        
        self.btn_add_axis = QPushButton("➕ Add Axis...")
        self.btn_add_axis.clicked.connect(self._start_axis_calibration)
        self.btn_add_axis.setToolTip("Calibrate a joystick axis (X, Y, triggers, etc.)")
        self.btn_add_axis.setMinimumHeight(36)
        self.btn_add_axis.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #45a049;
            }
            QPushButton:disabled {
                background: #cccccc;
                color: #666666;
            }
        """)
        btn_row.addWidget(self.btn_add_axis)
        
        self.btn_add_button = QPushButton("➕ Add Button...")
        self.btn_add_button.clicked.connect(self._start_button_detection)
        self.btn_add_button.setToolTip("Detect and add a button")
        self.btn_add_button.setMinimumHeight(36)
        self.btn_add_button.setStyleSheet("""
            QPushButton {
                background: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #0b7dda;
            }
            QPushButton:disabled {
                background: #cccccc;
                color: #666666;
            }
        """)
        btn_row.addWidget(self.btn_add_button)
        
        btn_row.addStretch()
        layout.addLayout(btn_row)
        
        # Configured inputs table
        table_label = QLabel("<b>Configured Inputs:</b>")
        table_label.setStyleSheet("margin-top: 8px;")
        layout.addWidget(table_label)
        
        self.inputs_table = QTableWidget(0, 4)
        self.inputs_table.setHorizontalHeaderLabels(["Input Code", "Type", "Construct Label", "Details"])
        self.inputs_table.horizontalHeader().setStretchLastSection(True)
        self.inputs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.inputs_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.inputs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.inputs_table.setAlternatingRowColors(True)
        self.inputs_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            QTableWidget::item {
                padding: 8px;
            }
        """)
        layout.addWidget(self.inputs_table, 1)
        
        # Remove button
        remove_row = QHBoxLayout()
        remove_row.addStretch()
        self.btn_remove = QPushButton("✖ Remove Selected")
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_remove.setEnabled(False)
        self.btn_remove.setStyleSheet("""
            QPushButton {
                background: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: #da190b;
            }
            QPushButton:disabled {
                background: #cccccc;
                color: #666666;
            }
        """)
        remove_row.addWidget(self.btn_remove)
        layout.addLayout(remove_row)
        
        self.inputs_table.itemSelectionChanged.connect(
            lambda: self.btn_remove.setEnabled(len(self.inputs_table.selectedItems()) > 0)
        )
        
        # Status/progress area
        self.status_group = QGroupBox("Status")
        self.status_group.setStyleSheet("""
            QGroupBox {
                border: 2px solid #ddd;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        status_layout = QVBoxLayout(self.status_group)
        
        self.status_label = QLabel("Ready to configure inputs")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 4px;")
        status_layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #4CAF50;
            }
        """)
        status_layout.addWidget(self.progress_bar)
        
        layout.addWidget(self.status_group)
        
        # Dialog buttons
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        
        self.btn_skip = QPushButton("Skip (Use Defaults)")
        self.btn_skip.clicked.connect(self._skip_calibration)
        self.btn_skip.setToolTip("Skip calibration and record all inputs with raw values")
        self.btn_skip.setMinimumHeight(36)
        self.btn_skip.setStyleSheet("""
            QPushButton {
                background: #9E9E9E;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: #757575;
            }
        """)
        bottom_row.addWidget(self.btn_skip)
        
        self.btn_done = QPushButton("Done")
        self.btn_done.clicked.connect(self._finish_calibration)
        self.btn_done.setDefault(True)
        self.btn_done.setEnabled(False)  # Enable after at least one input configured
        self.btn_done.setMinimumHeight(36)
        self.btn_done.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #45a049;
            }
            QPushButton:disabled {
                background: #cccccc;
                color: #666666;
            }
        """)
        bottom_row.addWidget(self.btn_done)
        
        layout.addLayout(bottom_row)
    
    def _open_device(self):
        """Open the controller device."""
        if not self.controller_path:
            return
        
        try:
            self._device = InputDevice(self.controller_path)
            print(f"[calibration] Opened device: {self._device.name}")
        except Exception as e:
            QMessageBox.critical(
                self, "Device Error",
                f"Could not open controller:\n{e}"
            )
            self.reject()
    
    def _start_polling(self):
        """Start polling for controller input."""
        if not self._device:
            return
        
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(16)  # ~60 Hz
        self._poll_timer.timeout.connect(self._poll_device)
        self._poll_timer.start()
    
    def _poll_device(self):
        """Poll device for input events."""
        if not self._device:
            return
        
        current_time = time.time()
        
        try:
            # Use non-blocking read - returns empty list if no events
            events = []
            try:
                while True:
                    event = self._device.read_one()
                    if event is None:
                        break
                    events.append(event)
            except BlockingIOError:
                pass
            
            for event in events:
                # Skip sync and MSC events
                if event.type in (ecodes.EV_SYN, ecodes.EV_MSC):
                    continue
                
                # DEBUG: Print all events when detecting button
                if self._detecting_button:
                    print(f"[calibration] Event: type={event.type} code={event.code} value={event.value}")
                    if event.type == ecodes.EV_KEY:
                        print(f"[calibration] KEY EVENT DETECTED! Code: {event.code}")
                
                # No debounce during calibration - we want all samples
                # Light debounce for button detection only
                if self._detecting_button and (current_time - self._last_event_time < 0.2):
                    continue
                
                self._last_event_time = current_time
                
                # Handle based on current workflow state
                if self._calibrating_axis and event.type == ecodes.EV_ABS:
                    self._handle_axis_calibration_event(event)
                elif self._detecting_button and event.type == ecodes.EV_KEY:
                    # Any key press (value=1) triggers detection
                    if event.value == 1:  # Only on press, not release
                        print(f"[calibration] Calling button handler for code {event.code}!")
                        self._handle_button_detection_event(event)
        
        except Exception as e:
            # Only print non-trivial errors
            if "Resource temporarily unavailable" not in str(e):
                print(f"[calibration] Polling error: {e}")
    
    def _start_axis_calibration(self):
        """Start axis calibration workflow."""
        self._calibrating_axis = "waiting"
        self._axis_samples = []
        
        self.btn_add_axis.setEnabled(False)
        self.btn_add_button.setEnabled(False)
        self.btn_done.setEnabled(False)
        self.btn_skip.setEnabled(False)
        
        self.status_label.setText(
            "<b style='color: #2196F3;'>Axis Calibration Started</b><br><br>"
            "Move the joystick or trigger you want to calibrate.<br>"
            "The system will automatically detect which axis you're moving."
        )
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
    
    def _handle_axis_calibration_event(self, event):
        """Handle axis events during calibration."""
        code_name = self._get_axis_name(event.code)
        
        if self._calibrating_axis == "waiting":
            # First significant movement - identify the axis
            # Handle both standard gamepads (large values) and Wii Nunchuck (0-255)
            center_threshold = 128 if abs(event.value) < 500 else 0
            deviation = abs(event.value - center_threshold)
            
            if deviation > 20:  # Significant movement
                self._calibrating_axis = code_name
                self._axis_samples = [event.value]
                
                self.status_label.setText(
                    f"<b style='color: #4CAF50;'>Calibrating: {code_name}</b><br><br>"
                    f"<b>Instructions:</b><br>"
                    f"1. Move to <b>MAXIMUM</b> position (all the way in one direction)<br>"
                    f"2. Move to <b>MINIMUM</b> position (all the way in opposite direction)<br>"
                    f"3. Move around to cover the full range<br><br>"
                    f"<i>Collecting samples... {len(self._axis_samples)}/40</i>"
                )
                self.progress_bar.setRange(0, 40)  # Need 40 samples
                self.progress_bar.setValue(len(self._axis_samples))
        
        elif self._calibrating_axis == code_name:
            # Collecting samples for this axis
            self._axis_samples.append(event.value)
            self.progress_bar.setValue(len(self._axis_samples))
            
            min_so_far = min(self._axis_samples)
            max_so_far = max(self._axis_samples)
            
            self.status_label.setText(
                f"<b style='color: #4CAF50;'>Calibrating: {code_name}</b><br><br>"
                f"<b>Instructions:</b><br>"
                f"Move to MAXIMUM, then MINIMUM position.<br>"
                f"Cover the full range of motion.<br><br>"
                f"<b>Current Range:</b> {min_so_far} to {max_so_far}<br>"
                f"<i>Samples: {len(self._axis_samples)}/40</i>"
            )
            
            if len(self._axis_samples) >= 40:
                self._complete_axis_calibration()
    
    def _complete_axis_calibration(self):
        """Complete axis calibration and ask for label."""
        code = self._calibrating_axis
        samples = self._axis_samples
        
        # Calculate min/max/center
        min_val = min(samples)
        max_val = max(samples)
        center_val = (min_val + max_val) // 2
        
        # Show summary before asking for label
        range_info = f"Range detected: {min_val} to {max_val}"
        
        # Ask for construct label
        label, ok = QInputDialog.getText(
            self,
            "Construct Label",
            f"<b>Axis calibrated: {code}</b><br><br>"
            f"{range_info}<br><br>"
            f"Enter a construct label for this axis:<br>"
            f"<i>(Examples: 'Emotional Arousal', 'Valence', 'Engagement', 'Attention')</i>",
            text=code  # Default to axis name
        )
        
        if ok and label.strip():
            # Save calibration
            axis_cal = AxisCalibration(
                code=code,
                min_value=min_val,
                max_value=max_val,
                center_value=center_val,
                label=label.strip()
            )
            self.calibration.axes[code] = axis_cal
            
            # Add to table
            self._add_input_to_table(
                code, 
                "Axis", 
                label.strip(), 
                f"Range: {min_val} to {max_val} → -1.0 to 1.0"
            )
            
            QMessageBox.information(
                self, "✓ Axis Calibrated",
                f"<b>{code}</b> configured successfully!<br><br>"
                f"<b>Range:</b> {min_val} to {max_val}<br>"
                f"<b>Label:</b> {label.strip()}<br><br>"
                f"Values will be normalized to <b>-1.0 to 1.0</b> during recording."
            )
        
        # Reset state
        self._calibrating_axis = None
        self._axis_samples = []
        self.btn_add_axis.setEnabled(True)
        self.btn_add_button.setEnabled(True)
        self.btn_done.setEnabled(len(self.calibration.axes) > 0 or len(self.calibration.buttons) > 0)
        self.btn_skip.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(
            f"<b style='color: #4CAF50;'>✓ {code} added</b><br>"
            "Ready to configure more inputs"
        )
    
    def _start_button_detection(self):
        """Start button detection workflow."""
        self._detecting_button = True
        
        self.btn_add_axis.setEnabled(False)
        self.btn_add_button.setEnabled(False)
        self.btn_done.setEnabled(False)
        self.btn_skip.setEnabled(False)
        
        self.status_label.setText(
            "<b style='color: #2196F3;'>Button Detection Started</b><br><br>"
            "Press the button you want to add..."
        )
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
    
    def _handle_button_detection_event(self, event):
        """Handle button press during detection."""
        code_name = self._get_button_name(event.code)
        
        # Ask for construct label
        label, ok = QInputDialog.getText(
            self,
            "Construct Label",
            f"<b>Button detected: {code_name}</b><br><br>"
            f"Enter a construct label for this button:<br>"
            f"<i>(Examples: 'Positive Event', 'Negative Event', 'Marker', 'Important Moment')</i>",
            text=code_name  # Default to button name
        )
        
        if ok and label.strip():
            # Save calibration
            btn_cal = ButtonCalibration(
                code=code_name,
                label=label.strip()
            )
            self.calibration.buttons[code_name] = btn_cal
            
            # Add to table
            self._add_input_to_table(
                code_name, 
                "Button", 
                label.strip(),
                "Press = 1, Release = 0"
            )
            
            QMessageBox.information(
                self, "✓ Button Configured",
                f"<b>{code_name}</b> configured successfully!<br><br>"
                f"<b>Label:</b> {label.strip()}<br><br>"
                f"Button presses will be recorded as events."
            )
        
        # Reset state
        self._detecting_button = False
        self.btn_add_axis.setEnabled(True)
        self.btn_add_button.setEnabled(True)
        self.btn_done.setEnabled(len(self.calibration.axes) > 0 or len(self.calibration.buttons) > 0)
        self.btn_skip.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(
            f"<b style='color: #4CAF50;'>✓ {code_name} added</b><br>"
            "Ready to configure more inputs"
        )
    
    def _add_input_to_table(self, code: str, type_str: str, label: str, details: str = ""):
        """Add an input to the configured inputs table."""
        row = self.inputs_table.rowCount()
        self.inputs_table.insertRow(row)
        
        # Code
        code_item = QTableWidgetItem(code)
        code_item.setFont(self.inputs_table.font())
        self.inputs_table.setItem(row, 0, code_item)
        
        # Type
        type_item = QTableWidgetItem(type_str)
        if type_str == "Axis":
            type_item.setForeground(Qt.darkGreen)
        else:
            type_item.setForeground(Qt.darkBlue)
        self.inputs_table.setItem(row, 1, type_item)
        
        # Label
        label_item = QTableWidgetItem(label)
        label_item.setFont(self.inputs_table.font())
        self.inputs_table.setItem(row, 2, label_item)
        
        # Details
        details_item = QTableWidgetItem(details)
        details_item.setForeground(Qt.gray)
        self.inputs_table.setItem(row, 3, details_item)
        
        # Resize columns
        self.inputs_table.resizeColumnsToContents()
    
    def _remove_selected(self):
        """Remove selected input from configuration."""
        selected_rows = set(item.row() for item in self.inputs_table.selectedItems())
        if not selected_rows:
            return
        
        row = list(selected_rows)[0]
        code = self.inputs_table.item(row, 0).text()
        label = self.inputs_table.item(row, 2).text()
        
        result = QMessageBox.question(
            self, "Remove Input",
            f"Remove <b>{code}</b> (\"{label}\") from configuration?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if result == QMessageBox.Yes:
            # Remove from calibration
            if code in self.calibration.axes:
                del self.calibration.axes[code]
            if code in self.calibration.buttons:
                del self.calibration.buttons[code]
            
            # Remove from table
            self.inputs_table.removeRow(row)
            
            # Update done button
            self.btn_done.setEnabled(len(self.calibration.axes) > 0 or len(self.calibration.buttons) > 0)
            
            self.status_label.setText(f"Removed {code}")
    
    def _skip_calibration(self):
        """Skip calibration and use defaults."""
        result = QMessageBox.question(
            self, "Skip Calibration?",
            "<b>Skip calibration and record all inputs with raw values?</b><br><br>"
            "⚠️ <b>This means:</b><br>"
            "• All controller inputs will be recorded<br>"
            "• Values will NOT be normalized<br>"
            "• No construct labels will be assigned<br><br>"
            "You can still map constructs later in the researcher view.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if result == QMessageBox.Yes:
            # Emit None (means "use defaults")
            self.calibration_complete.emit(None)
            self.accept()
    
    def _finish_calibration(self):
        """Finish calibration and emit result."""
        if len(self.calibration.axes) == 0 and len(self.calibration.buttons) == 0:
            QMessageBox.warning(
                self, "No Inputs Configured",
                "You haven't configured any inputs yet.<br><br>"
                "Use <b>'Add Axis...'</b> or <b>'Add Button...'</b> to configure inputs,<br>"
                "or click <b>'Skip (Use Defaults)'</b> to record all inputs."
            )
            return
        
        # Show summary
        summary = f"<b>Configured {len(self.calibration.axes)} axes and {len(self.calibration.buttons)} buttons:</b><br><br>"
        
        if self.calibration.axes:
            summary += "<b>Axes:</b><br>"
            for code, axis in self.calibration.axes.items():
                summary += f"  • {code}: \"{axis.label}\" ({axis.min_value} to {axis.max_value})<br>"
            summary += "<br>"
        
        if self.calibration.buttons:
            summary += "<b>Buttons:</b><br>"
            for code, btn in self.calibration.buttons.items():
                summary += f"  • {code}: \"{btn.label}\"<br>"
            summary += "<br>"
        
        summary += "<b>Only these inputs will be recorded during the session.</b>"
        
        result = QMessageBox.question(
            self, "Confirm Calibration",
            summary,
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Ok
        )
        
        if result == QMessageBox.Ok:
            self.calibration_complete.emit(self.calibration)
            self.accept()
    
    def _get_axis_name(self, code: int) -> str:
        """Get axis name from code."""
        try:
            name = ecodes.ABS[code]
            if isinstance(name, (list, tuple)):
                return name[0]
            return name
        except:
            return f"ABS_{code}"
    
    def _get_button_name(self, code: int) -> str:
        """Get button name from code."""
        try:
            name = ecodes.BTN[code]
            if isinstance(name, (list, tuple)):
                return name[0]
            return name
        except:
            try:
                name = ecodes.KEY[code]
                if isinstance(name, (list, tuple)):
                    return name[0]
                return name
            except:
                return f"KEY_{code}"
    
    def closeEvent(self, event):
        """Cleanup on close."""
        if self._poll_timer:
            self._poll_timer.stop()
        
        if self._device:
            try:
                self._device.close()
            except:
                pass
        
        event.accept()
