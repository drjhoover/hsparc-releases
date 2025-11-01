# hsparc/ui/widgets/analysis_results.py
"""
Dialog for displaying convergence/divergence analysis results with clickable timeline.
Includes correlation matrix, scatterplots, and adjustable thresholds.
"""
from __future__ import annotations

from typing import Optional, Callable, Dict, Tuple
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QGroupBox, QTextEdit,
    QHeaderView, QAbstractItemView, QSplitter, QWidget, QSlider,
    QSpinBox, QGridLayout, QComboBox, QTabWidget, QMessageBox
)
from PySide6.QtGui import QColor
import pyqtgraph as pg
import numpy as np
from scipy import stats

try:
    from hsparc.analysis.convergence import AnalysisResults, ConvergenceEvent
except:
    from analysis.convergence import AnalysisResults, ConvergenceEvent


class AnalysisResultsDialog(QDialog):
    """
    Dialog showing convergence/divergence analysis results.
    Features:
    - Adjustable thresholds with live rerun
    - Correlation matrix for all control signals
    - Scatterplot viewer for any two signals
    - Clickable events to seek video
    """

    seek_requested = Signal(int)

    def __init__(
            self,
            parent=None,
            results: Optional[AnalysisResults] = None,
            seek_callback: Optional[Callable[[int], None]] = None,
            rerun_callback: Optional[Callable[[float, float], AnalysisResults]] = None
    ):
        super().__init__(parent)
        self.setWindowTitle("Convergence/Divergence Analysis")
        self.resize(1100, 900)

        self.results = results
        self.seek_callback = seek_callback
        self.rerun_callback = rerun_callback
        self.participant_data = {}

        if results and hasattr(results, '_participant_data'):
            self.participant_data = results._participant_data

        layout = QVBoxLayout(self)

        title = QLabel("Participant Convergence/Divergence Analysis")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        if rerun_callback:
            threshold_widget = self._create_threshold_controls()
            layout.addWidget(threshold_widget)

        self.tabs = QTabWidget()

        # Tab 0: Signal Selection (for convergence/divergence)
        signal_select_tab = self._create_signal_selection_tab()
        self.tabs.addTab(signal_select_tab, "Signal Selection")

        # Tab 1: Events and Summary
        events_tab = self._create_events_tab()
        self.tabs.addTab(events_tab, "Events & Summary")

        # Tab 2: Correlation Matrix
        correlation_tab = self._create_correlation_tab()
        self.tabs.addTab(correlation_tab, "Correlation Matrix")

        # Tab 3: Scatterplot Viewer
        scatterplot_tab = self._create_scatterplot_tab()
        self.tabs.addTab(scatterplot_tab, "Scatterplot Viewer")

        layout.addWidget(self.tabs)

        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton("Export Results...")
        self.btn_close = QPushButton("Close")
        btn_layout.addWidget(self.btn_export)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self.btn_close.clicked.connect(self.accept)
        self.btn_export.clicked.connect(self._export_results)
        if seek_callback:
            self.seek_requested.connect(seek_callback)

        if results:
            self._populate_data(results)

    def _create_threshold_controls(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 10)

        group = QGroupBox("Adjust Thresholds (move sliders to rerun analysis)")
        group_layout = QGridLayout(group)

        conv_label = QLabel("Convergence Threshold:")
        conv_label.setToolTip("Lower values = stricter convergence detection")
        self.conv_slider = QSlider(Qt.Horizontal)
        self.conv_slider.setRange(10, 50)
        self.conv_slider.setValue(30)
        self.conv_value_label = QLabel("0.30")

        group_layout.addWidget(conv_label, 0, 0)
        group_layout.addWidget(self.conv_slider, 0, 1)
        group_layout.addWidget(self.conv_value_label, 0, 2)

        div_label = QLabel("Divergence Threshold:")
        div_label.setToolTip("Higher values = stricter divergence detection")
        self.div_slider = QSlider(Qt.Horizontal)
        self.div_slider.setRange(50, 90)
        self.div_slider.setValue(70)
        self.div_value_label = QLabel("0.70")

        group_layout.addWidget(div_label, 1, 0)
        group_layout.addWidget(self.div_slider, 1, 1)
        group_layout.addWidget(self.div_value_label, 1, 2)

        self.btn_rerun = QPushButton("Rerun Analysis with New Thresholds")
        group_layout.addWidget(self.btn_rerun, 2, 0, 1, 3)

        self.conv_slider.valueChanged.connect(lambda v: self.conv_value_label.setText(f"{v / 100:.2f}"))
        self.div_slider.valueChanged.connect(lambda v: self.div_value_label.setText(f"{v / 100:.2f}"))
        self.btn_rerun.clicked.connect(self._rerun_analysis)

        layout.addWidget(group)
        return widget

    def _rerun_analysis(self):
        if not self.rerun_callback:
            return

        conv_threshold = self.conv_slider.value() / 100.0
        div_threshold = self.div_slider.value() / 100.0

        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            new_results = self.rerun_callback(conv_threshold, div_threshold)
            self.results = new_results
            self._populate_data(new_results)
        finally:
            QApplication.restoreOverrideCursor()

    def _create_signal_selection_tab(self) -> QWidget:
        """Create tab for selecting which two signals to use for convergence/divergence analysis."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel("Select Two Input Traces for Convergence/Divergence Analysis")
        info.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(info)

        explanation = QLabel(
            "Convergence/divergence detection compares two input traces over time to find moments "
            "when they move together (convergence) or apart (divergence).\n\n"
            "Current analysis uses the primary axis from selected participants. To analyze different traces, "
            "select them below and click 'Recompute':"
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #666;")
        layout.addWidget(explanation)

        # Signal selection
        select_layout = QGridLayout()

        select_layout.addWidget(QLabel("Trace 1:"), 0, 0)
        self.conv_signal1_combo = QComboBox()
        self.conv_signal1_combo.currentIndexChanged.connect(self._on_conv_signal1_changed)
        select_layout.addWidget(self.conv_signal1_combo, 0, 1)

        select_layout.addWidget(QLabel("Trace 2:"), 1, 0)
        self.conv_signal2_combo = QComboBox()
        select_layout.addWidget(self.conv_signal2_combo, 1, 1)

        self.btn_recompute_convergence = QPushButton("Recompute Convergence/Divergence with Selected Traces")
        self.btn_recompute_convergence.setToolTip(
            "Note: This feature requires additional implementation to recompute with specific traces")
        self.btn_recompute_convergence.clicked.connect(self._recompute_with_selected_signals)
        select_layout.addWidget(self.btn_recompute_convergence, 2, 0, 1, 2)

        layout.addLayout(select_layout)

        # Current analysis info
        info_label = QLabel("Current Analysis:")
        info_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(info_label)

        self.conv_analysis_info = QLabel("")
        self.conv_analysis_info.setStyleSheet(
            "background: #f0f0f0; padding: 10px; font-family: monospace; border: 1px solid #ddd;")
        self.conv_analysis_info.setWordWrap(True)
        layout.addWidget(self.conv_analysis_info)

        layout.addStretch()
        return widget

    def _on_conv_signal1_changed(self):
        """When signal 1 changes, update signal 2 dropdown to exclude it."""
        if not self.results or not hasattr(self.results, 'signal_labels'):
            return

        sig1 = self.conv_signal1_combo.currentText()
        signals = self.results.signal_labels

        # Remember current selection
        current_sig2 = self.conv_signal2_combo.currentText()

        # Rebuild signal 2 combo without signal 1
        self.conv_signal2_combo.blockSignals(True)
        self.conv_signal2_combo.clear()

        for sig in signals:
            if sig != sig1:
                self.conv_signal2_combo.addItem(sig)

        # Restore selection if valid
        idx = self.conv_signal2_combo.findText(current_sig2)
        if idx >= 0:
            self.conv_signal2_combo.setCurrentIndex(idx)

        self.conv_signal2_combo.blockSignals(False)

    def _populate_signal_selection_tab(self, results: AnalysisResults):
        """Populate signal selection dropdowns."""
        signals = results.signal_labels if hasattr(results, 'signal_labels') else []

        if len(signals) < 2:
            self.conv_analysis_info.setText("Need at least 2 input traces for convergence/divergence analysis.")
            return

        # Populate signal 1 with ALL signals
        self.conv_signal1_combo.blockSignals(True)
        self.conv_signal1_combo.clear()
        for sig in signals:
            self.conv_signal1_combo.addItem(sig)
        self.conv_signal1_combo.setCurrentIndex(0)
        self.conv_signal1_combo.blockSignals(False)

        # Populate signal 2 with all EXCEPT first
        self.conv_signal2_combo.clear()
        for sig in signals:
            if sig != signals[0]:
                self.conv_signal2_combo.addItem(sig)

        # Show current analysis info
        if results.events:
            participants = results.events[0].participants if results.events else []
            info_text = f"Current Analysis:\n"
            info_text += f"  Comparing: {', '.join(participants) if participants else 'N/A'}\n"
            info_text += f"  Convergence Events: {results.summary_stats.get('num_convergence_events', 0)}\n"
            info_text += f"  Divergence Events: {results.summary_stats.get('num_divergence_events', 0)}\n"
            info_text += f"  Overall Correlation: {results.overall_correlation:.3f}\n\n"
            info_text += f"Total Available Traces: {len(signals)}"
        else:
            info_text = f"No convergence/divergence events detected with current thresholds.\n\n"
            info_text += f"Total Available Traces: {len(signals)}\n"
            info_text += f"Adjust thresholds above or select different traces."

        self.conv_analysis_info.setText(info_text)

    def _recompute_with_selected_signals(self):
        """Recompute convergence/divergence using user-selected signals."""
        sig1 = self.conv_signal1_combo.currentText()
        sig2 = self.conv_signal2_combo.currentText()

        if not sig1 or not sig2:
            QMessageBox.warning(self, "Select Signals", "Please select both traces.")
            return

        if sig1 == sig2:
            QMessageBox.warning(self, "Different Signals", "Please select two different traces.")
            return

        # Extract participant names from signal labels
        # Format: "Participant A: ABS_X" -> "Participant A"
        try:
            participant1 = sig1.split(":")[0].strip()
            participant2 = sig2.split(":")[0].strip()
        except:
            QMessageBox.warning(self, "Invalid Format", "Could not parse signal names.")
            return

        # Get the raw signal data
        if not hasattr(self.results, '_raw_signals') or not self.results._raw_signals:
            QMessageBox.warning(self, "No Data", "Signal data not available for recomputation.")
            return

        data1 = self.results._raw_signals.get(sig1)
        data2 = self.results._raw_signals.get(sig2)

        if data1 is None or data2 is None:
            QMessageBox.warning(self, "Missing Data", f"Could not find data for selected signals.")
            return

        # Build participant_data structure for the analyzer
        # The analyzer expects: {"Participant Name": {"times_ms": array, "values": array}}
        # We'll create synthetic time arrays (since signals are already aligned)
        min_len = min(len(data1), len(data2))
        times_ms = np.arange(0, min_len, dtype=float)  # Aligned data uses sequential time

        participant_data = {
            participant1: {
                "times_ms": times_ms,
                "values": data1[:min_len]
            },
            participant2: {
                "times_ms": times_ms,
                "values": data2[:min_len]
            }
        }

        # Show progress
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            # Get current thresholds
            conv_threshold = self.conv_slider.value() / 100.0 if hasattr(self, 'conv_slider') else 0.3
            div_threshold = self.div_slider.value() / 100.0 if hasattr(self, 'div_slider') else 0.7

            # Run analysis with selected signals
            from hsparc.analysis.convergence import ConvergenceAnalyzer
            analyzer = ConvergenceAnalyzer(
                window_ms=2000,
                convergence_threshold=conv_threshold,
                divergence_threshold=div_threshold,
                min_event_duration_ms=500
            )

            # Pass only the two selected signals (no all_control_signals)
            new_results = analyzer.analyze(participant_data, all_control_signals=None)

            # Keep the correlation matrix and scatterplot data from original results
            new_results.correlation_matrix = self.results.correlation_matrix
            new_results.signal_labels = self.results.signal_labels
            new_results._raw_signals = self.results._raw_signals
            new_results._participant_data = self.results._participant_data

            # Update the results
            self.results = new_results

            # Refresh the UI
            self._populate_data(new_results)

            QMessageBox.information(
                self,
                "Recomputed",
                f"Convergence/divergence analysis updated for:\n\n"
                f"Trace 1: {sig1}\n"
                f"Trace 2: {sig2}\n\n"
                f"Found {new_results.summary_stats.get('num_convergence_events', 0)} convergence events "
                f"and {new_results.summary_stats.get('num_divergence_events', 0)} divergence events."
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Recomputation Failed",
                f"Could not recompute convergence analysis:\n{e}\n\n"
                "This may be due to incompatible signal data."
            )
            import traceback
            traceback.print_exc()
        finally:
            QApplication.restoreOverrideCursor()

    def _create_events_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        splitter = QSplitter(Qt.Vertical)

        summary_group = QGroupBox("Overall Statistics")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumHeight(200)
        summary_layout.addWidget(self.summary_text)
        splitter.addWidget(summary_group)

        events_group = QGroupBox("Detected Events (double-click to seek video)")
        events_layout = QVBoxLayout(events_group)

        info = QLabel("💡 Double-click any row to jump to that moment in the video")
        info.setStyleSheet("color: #666; font-style: italic;")
        events_layout.addWidget(info)

        self.events_table = QTableWidget()
        self.events_table.setColumnCount(6)
        self.events_table.setHorizontalHeaderLabels([
            "Type", "Start Time", "Duration", "Strength", "Participants", "Description"
        ])
        self.events_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.events_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.events_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.events_table.setSortingEnabled(True)

        header = self.events_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)

        self.events_table.cellDoubleClicked.connect(self._on_event_clicked)
        events_layout.addWidget(self.events_table)

        splitter.addWidget(events_group)
        splitter.setSizes([250, 400])

        layout.addWidget(splitter)
        return widget

    def _create_correlation_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel("Bivariate Correlation Analysis (Pearson r)")
        info.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(info)

        self.correlation_text = QTextEdit()
        self.correlation_text.setReadOnly(True)
        layout.addWidget(self.correlation_text)

        return widget

    def _create_scatterplot_tab(self) -> QWidget:
        """Create the scatterplot viewer tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Instructions
        info = QLabel("Select Any Two Input Traces for Correlation/Regression Analysis")
        info.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(info)

        explanation = QLabel(
            "Choose any two continuous input traces (joystick axes, triggers, etc.) from any participants.\n"
            "Each trace shown on the timeline is available for analysis."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(explanation)

        # Controls
        controls = QGridLayout()

        controls.addWidget(QLabel("Variable 1 (X-Axis):"), 0, 0)
        self.scatter_x_combo = QComboBox()
        self.scatter_x_combo.currentIndexChanged.connect(self._on_scatter_selection_changed)
        controls.addWidget(self.scatter_x_combo, 0, 1)

        controls.addWidget(QLabel("Variable 2 (Y-Axis):"), 1, 0)
        self.scatter_y_combo = QComboBox()
        controls.addWidget(self.scatter_y_combo, 1, 1)

        self.btn_update_scatter = QPushButton("Update Scatterplot")
        self.btn_update_scatter.clicked.connect(self._update_scatterplot)
        controls.addWidget(self.btn_update_scatter, 2, 0, 1, 2)

        layout.addLayout(controls)

        # Statistics display
        self.scatter_stats = QLabel("")
        self.scatter_stats.setStyleSheet(
            "font-family: monospace; padding: 10px; background: #f0f0f0; border: 1px solid #ddd;")
        self.scatter_stats.setWordWrap(True)
        layout.addWidget(self.scatter_stats)

        # Plot widget
        self.scatter_plot = pg.PlotWidget()
        self.scatter_plot.setBackground('w')
        self.scatter_plot.showGrid(x=True, y=True, alpha=0.3)
        layout.addWidget(self.scatter_plot, 1)

        return widget

    def _on_scatter_selection_changed(self):
        """When X variable changes, update Y dropdown to exclude the selected X variable."""
        if not self.results or not hasattr(self.results, 'signal_labels'):
            return

        x_signal = self.scatter_x_combo.currentText()
        signals = self.results.signal_labels

        # Remember current Y selection
        current_y = self.scatter_y_combo.currentText()

        # Rebuild Y combo without the selected X variable
        self.scatter_y_combo.blockSignals(True)
        self.scatter_y_combo.clear()

        for sig in signals:
            if sig != x_signal:  # Exclude the X variable
                self.scatter_y_combo.addItem(sig)

        # Restore Y selection if still valid
        y_index = self.scatter_y_combo.findText(current_y)
        if y_index >= 0:
            self.scatter_y_combo.setCurrentIndex(y_index)

        self.scatter_y_combo.blockSignals(False)

    def _populate_data(self, results: AnalysisResults):
        """Populate all tabs with analysis results."""
        print(f"[analysis_results] Populating data...")
        print(f"[analysis_results] Has signal_labels: {hasattr(results, 'signal_labels')}")
        if hasattr(results, 'signal_labels'):
            print(f"[analysis_results] Number of signals: {len(results.signal_labels)}")
            print(f"[analysis_results] Signals: {results.signal_labels[:5]}")  # First 5

        # Tab 0: Signal Selection
        self._populate_signal_selection_tab(results)

        # Tab 1: Events and Summary
        self._populate_events_tab(results)

        # Tab 2: Correlation Matrix
        self._populate_correlation_tab(results)

        # Tab 3: Scatterplot
        self._populate_scatterplot_tab(results)

    def _populate_events_tab(self, results: AnalysisResults):
        summary_html = f"""
        <h3>Summary Statistics</h3>

        <h4>Overall Correlation</h4>
        <p><b>Pearson r:</b> {results.overall_correlation:.3f}</p>

        <h4>Distance Metrics</h4>
        <table style="width: 100%; border-collapse: collapse;">
        <tr>
            <td><b>Mean Distance:</b></td>
            <td>{results.mean_distance:.3f}</td>
            <td><b>Median Distance:</b></td>
            <td>{results.summary_stats.get('median_distance', 0):.3f}</td>
        </tr>
        <tr>
            <td><b>Min Distance:</b></td>
            <td>{results.summary_stats.get('min_distance', 0):.3f}</td>
            <td><b>Max Distance:</b></td>
            <td>{results.summary_stats.get('max_distance', 0):.3f}</td>
        </tr>
        </table>

        <h4>Event Summary</h4>
        <table style="width: 100%; border-collapse: collapse;">
        <tr>
            <td><b>Convergence Time:</b></td>
            <td>{results.convergence_percentage:.1f}%</td>
            <td><b>Divergence Time:</b></td>
            <td>{results.divergence_percentage:.1f}%</td>
        </tr>
        <tr>
            <td><b>Convergence Events:</b></td>
            <td>{results.summary_stats.get('num_convergence_events', 0)}</td>
            <td><b>Divergence Events:</b></td>
            <td>{results.summary_stats.get('num_divergence_events', 0)}</td>
        </tr>
        </table>

        <p style="margin-top: 10px; font-size: 11px;">
        <b>Interpretation:</b><br>
        • Correlation close to +1 indicates signals move together<br>
        • Correlation close to -1 indicates signals move in opposite directions<br>
        • Lower distance values indicate more similar inputs
        </p>
        """
        self.summary_text.setHtml(summary_html)

        self.events_table.setRowCount(len(results.events))
        self.events_table.setSortingEnabled(False)

        for row, event in enumerate(results.events):
            type_item = QTableWidgetItem(event.event_type.capitalize())
            if event.event_type == "convergence":
                type_item.setBackground(QColor(200, 255, 200))
            else:
                type_item.setBackground(QColor(255, 200, 200))
            type_item.setData(Qt.UserRole, event.start_ms)
            self.events_table.setItem(row, 0, type_item)

            start_item = QTableWidgetItem(self._format_time(event.start_ms))
            start_item.setData(Qt.UserRole, event.start_ms)
            self.events_table.setItem(row, 1, start_item)

            duration_ms = event.end_ms - event.start_ms
            duration_item = QTableWidgetItem(f"{duration_ms / 1000:.1f}s")
            duration_item.setData(Qt.UserRole, duration_ms)
            self.events_table.setItem(row, 2, duration_item)

            strength_item = QTableWidgetItem(f"{event.strength:.3f}")
            strength_item.setData(Qt.UserRole, event.strength)
            self.events_table.setItem(row, 3, strength_item)

            participants_item = QTableWidgetItem(", ".join(event.participants))
            self.events_table.setItem(row, 4, participants_item)

            desc_item = QTableWidgetItem(event.description)
            self.events_table.setItem(row, 5, desc_item)

        self.events_table.setSortingEnabled(True)
        self.events_table.sortByColumn(1, Qt.AscendingOrder)

    def _populate_correlation_tab(self, results: AnalysisResults):
        if not hasattr(results, 'correlation_matrix') or not results.correlation_matrix:
            self.correlation_text.setHtml("<p><i>No correlation data available</i></p>")
            return

        signals = results.signal_labels if hasattr(results, 'signal_labels') else []
        if len(signals) < 2:
            self.correlation_text.setHtml("<p><i>Need at least 2 control signals for correlation analysis</i></p>")
            return

        html = '<h3>Bivariate Correlation Matrix (Pearson r)</h3>'
        html += f'<p style="font-size: 11px; margin-bottom: 10px;"><i>{len(signals)} control signals, {len(results.correlation_matrix)} pairwise correlations</i></p>'
        html += '<div style="max-height: 600px; overflow-y: auto;">'
        html += '<table style="border-collapse: collapse; margin: 10px 0; font-size: 11px;">'

        html += '<tr><th style="border: 1px solid #ddd; padding: 4px; position: sticky; top: 0; background: white;"></th>'
        for sig in signals:
            display_name = sig if len(sig) < 25 else sig[:22] + "..."
            html += f'<th style="border: 1px solid #ddd; padding: 4px; background: #f0f0f0; position: sticky; top: 0;" title="{sig}">{display_name}</th>'
        html += '</tr>'

        for i, sig1 in enumerate(signals):
            display_name1 = sig1 if len(sig1) < 25 else sig1[:22] + "..."
            html += f'<tr><th style="border: 1px solid #ddd; padding: 4px; background: #f0f0f0;" title="{sig1}">{display_name1}</th>'
            for j, sig2 in enumerate(signals):
                if i == j:
                    html += '<td style="border: 1px solid #ddd; padding: 4px; text-align: center; background: #e8e8e8;">—</td>'
                elif i > j:
                    key = (sig2, sig1)
                    if key in results.correlation_matrix:
                        corr, p_val = results.correlation_matrix[key]
                        stars = self._get_significance_stars(p_val)
                        color = self._get_correlation_color(corr)
                        html += f'<td style="border: 1px solid #ddd; padding: 4px; text-align: center; background: {color};" title="r={corr:.4f}, p={p_val:.4f}">{corr:.2f}{stars}</td>'
                    else:
                        html += '<td style="border: 1px solid #ddd; padding: 4px; text-align: center;">—</td>'
                else:
                    key = (sig1, sig2)
                    if key in results.correlation_matrix:
                        corr, p_val = results.correlation_matrix[key]
                        stars = self._get_significance_stars(p_val)
                        color = self._get_correlation_color(corr)
                        html += f'<td style="border: 1px solid #ddd; padding: 4px; text-align: center; background: {color};" title="r={corr:.4f}, p={p_val:.4f}">{corr:.2f}{stars}</td>'
                    else:
                        html += '<td style="border: 1px solid #ddd; padding: 4px; text-align: center;">—</td>'
            html += '</tr>'

        html += '</table></div>'
        html += '<p style="font-size: 10px; margin: 5px 0;"><i>* p < .05, ** p < .01, *** p < .001</i></p>'

        self.correlation_text.setHtml(html)

    def _populate_scatterplot_tab(self, results: AnalysisResults):
        """Populate the scatterplot controls."""
        print(f"[analysis_results] Populating scatterplot tab...")

        # Get signal labels (all plotted traces)
        signals = results.signal_labels if hasattr(results, 'signal_labels') else []

        print(f"[analysis_results] Scatterplot signals: {len(signals)}")
        if signals:
            print(f"[analysis_results] First signal: {signals[0]}")

        if len(signals) < 2:
            self.scatter_stats.setText("Need at least 2 input traces for scatterplot analysis.")
            return

        # Populate X combo with ALL signals
        self.scatter_x_combo.blockSignals(True)
        self.scatter_x_combo.clear()
        for sig in signals:
            self.scatter_x_combo.addItem(sig)
            print(f"[analysis_results] Added to X combo: {sig}")
        self.scatter_x_combo.setCurrentIndex(0)
        self.scatter_x_combo.blockSignals(False)

        # Populate Y combo with all EXCEPT the first one
        self.scatter_y_combo.clear()
        for sig in signals:
            if sig != signals[0]:  # Exclude first signal (selected in X)
                self.scatter_y_combo.addItem(sig)
                print(f"[analysis_results] Added to Y combo: {sig}")

        print(f"[analysis_results] X combo count: {self.scatter_x_combo.count()}")
        print(f"[analysis_results] Y combo count: {self.scatter_y_combo.count()}")

        # Auto-update the scatterplot
        self._update_scatterplot()

    def _update_scatterplot(self):
        if not self.results or not hasattr(self.results, 'correlation_matrix'):
            return

        x_signal = self.scatter_x_combo.currentText()
        y_signal = self.scatter_y_combo.currentText()

        if not x_signal or not y_signal:
            return

        x_data = None
        y_data = None

        if hasattr(self.results, '_raw_signals'):
            x_data = self.results._raw_signals.get(x_signal)
            y_data = self.results._raw_signals.get(y_signal)

        if x_data is None or y_data is None:
            self.scatter_stats.setText("Signal data not available for scatterplot")
            return

        min_len = min(len(x_data), len(y_data))
        x_data = np.array(x_data[:min_len])
        y_data = np.array(y_data[:min_len])

        corr, p_val = stats.pearsonr(x_data, y_data)
        slope, intercept, r_value, p_value_reg, std_err = stats.linregress(x_data, y_data)

        stats_text = f"""
<b>Correlation Analysis:</b> {x_signal} vs {y_signal}
<b>Pearson r:</b> {corr:.4f} (p = {p_val:.4f}) {self._get_significance_stars(p_val)}
<b>R²:</b> {r_value ** 2:.4f}

<b>Linear Regression:</b>
<b>Equation:</b> y = {slope:.4f}x + {intercept:.4f}
<b>Slope:</b> {slope:.4f} ± {std_err:.4f}
<b>p-value:</b> {p_value_reg:.4f}

<b>Sample size:</b> {len(x_data)} points
        """
        self.scatter_stats.setText(stats_text.strip())

        self.scatter_plot.clear()

        scatter = pg.ScatterPlotItem(
            x=x_data, y=y_data,
            pen=None,
            brush=pg.mkBrush(100, 100, 200, 120),
            size=5
        )
        self.scatter_plot.addItem(scatter)

        x_line = np.array([x_data.min(), x_data.max()])
        y_line = slope * x_line + intercept
        line = pg.PlotDataItem(
            x_line, y_line,
            pen=pg.mkPen((255, 0, 0), width=2)
        )
        self.scatter_plot.addItem(line)

        self.scatter_plot.setLabel('bottom', x_signal)
        self.scatter_plot.setLabel('left', y_signal)
        self.scatter_plot.setTitle(f'r = {corr:.3f}, p = {p_val:.4f}')

    def _get_correlation_color(self, corr: float) -> str:
        abs_corr = abs(corr)
        if abs_corr >= 0.7:
            return "#d4edda"
        elif abs_corr >= 0.4:
            return "#fff3cd"
        elif abs_corr >= 0.2:
            return "#f8f9fa"
        else:
            return "#ffffff"

    def _get_significance_stars(self, p_value: float) -> str:
        if p_value < 0.001:
            return "***"
        elif p_value < 0.01:
            return "**"
        elif p_value < 0.05:
            return "*"
        else:
            return ""

    def _format_time(self, ms: int) -> str:
        total_seconds = ms / 1000
        minutes = int(total_seconds // 60)
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:06.3f}"

    def _on_event_clicked(self, row: int, column: int):
        item = self.events_table.item(row, 0)
        if item:
            timestamp_ms = item.data(Qt.UserRole)
            if timestamp_ms is not None:
                print(f"[analysis] Seeking to {timestamp_ms}ms")
                self.seek_requested.emit(timestamp_ms)
                if self.seek_callback:
                    self.seek_callback(timestamp_ms)

    def _export_results(self):
        from PySide6.QtWidgets import QFileDialog
        import csv

        if not self.results:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Analysis Results",
            "convergence_analysis.csv",
            "CSV Files (*.csv)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'w', newline='') as f:
                writer = csv.writer(f)

                writer.writerow(["Summary Statistics"])
                writer.writerow(["Overall Correlation", self.results.overall_correlation])
                writer.writerow(["Mean Distance", self.results.mean_distance])
                writer.writerow(["Convergence Percentage", self.results.convergence_percentage])
                writer.writerow(["Divergence Percentage", self.results.divergence_percentage])
                writer.writerow([])

                writer.writerow(["Events"])
                writer.writerow([
                    "Type", "Start (ms)", "End (ms)", "Duration (ms)",
                    "Strength", "Distance", "Participants", "Description"
                ])

                for event in self.results.events:
                    writer.writerow([
                        event.event_type,
                        event.start_ms,
                        event.end_ms,
                        event.end_ms - event.start_ms,
                        f"{event.strength:.3f}",
                        f"{event.distance:.3f}",
                        ", ".join(event.participants),
                        event.description
                    ])

            QMessageBox.information(
                self,
                "Export Complete",
                f"Analysis results exported to:\n{file_path}"
            )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Could not export results:\n{e}"
            )