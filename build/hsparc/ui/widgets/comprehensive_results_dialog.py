# hsparc/ui/widgets/comprehensive_results_dialog.py
"""
Comprehensive analysis results dialog.
Shows different tabs based on analysis type (single, pairwise, multi).
"""
from __future__ import annotations

from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTextEdit, QWidget, QPushButton, QLabel, QDialogButtonBox, QGroupBox,
    QListWidget, QListWidgetItem
)
from PySide6.QtGui import QFont

import pyqtgraph as pg
import numpy as np

try:
    from hsparc.analysis.comprehensive_analyzer import (
        ComprehensiveResults, SingleTraceResults,
        PairwiseResults, MultiTraceResults
    )
except ImportError:
    try:
        from comprehensive_analyzer import (
            ComprehensiveResults, SingleTraceResults,
            PairwiseResults, MultiTraceResults
        )
    except ImportError:
        ComprehensiveResults = None
        print("[results_dialog] Could not import analysis results classes")


class ComprehensiveResultsDialog(QDialog):
    """Dialog showing comprehensive analysis results"""

    def __init__(
            self,
            parent=None,
            results: Optional[ComprehensiveResults] = None,
            seek_callback=None
    ):
        super().__init__(parent)

        self.results = results
        self.seek_callback = seek_callback  # Callback to seek video: seek_callback(ms)

        self.setWindowTitle("Comprehensive Analysis Results")
        self.setModal(False)
        self.resize(1200, 800)

        self._setup_ui()

        if results:
            self._populate_results()

    def _setup_ui(self):
        """Build the UI"""
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Trace Analysis Results")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.accept)
        layout.addWidget(button_box)

    def _populate_results(self):
        """Populate tabs based on analysis type"""
        if not self.results:
            return

        analysis_type = self.results.analysis_type

        # Always show summary first
        summary_tab = self._create_summary_tab()
        self.tabs.addTab(summary_tab, "📊 Summary")

        if analysis_type == "single" and self.results.single:
            self._add_single_trace_tabs(self.results.single)
        elif analysis_type == "pairwise" and self.results.pairwise:
            self._add_pairwise_tabs(self.results.pairwise)
        elif analysis_type == "multi" and self.results.multi:
            self._add_multi_trace_tabs(self.results.multi)

    def _create_summary_tab(self) -> QWidget:
        """Create summary text tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Courier", 10))
        text_edit.setPlainText(self.results.summary_text if self.results else "No results")
        layout.addWidget(text_edit)

        return widget

    # ========================================================================
    # SINGLE TRACE TABS
    # ========================================================================

    def _add_single_trace_tabs(self, results: SingleTraceResults):
        """Add tabs for single trace analysis"""
        # Time series plot
        ts_tab = self._create_single_timeseries_tab(results)
        self.tabs.addTab(ts_tab, "📈 Time Series")

        # Distribution
        dist_tab = self._create_distribution_tab(results)
        self.tabs.addTab(dist_tab, "📊 Distribution")

        # Change detection
        change_tab = self._create_change_detection_tab(results)
        self.tabs.addTab(change_tab, "🎯 Change Points")

    def _create_single_timeseries_tab(self, results: SingleTraceResults) -> QWidget:
        """Create time series plot with annotations"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        plot_widget = pg.PlotWidget(title=f"Time Series: {results.trace_name}")
        plot_widget.setLabel('left', 'Value')
        plot_widget.setLabel('bottom', 'Time', units='ms')

        # Plot main trace
        plot_widget.plot(
            results.times_ms, results.values,
            pen=pg.mkPen('c', width=2),
            name=results.trace_name
        )

        # Mark change points
        if results.change_points:
            change_y = np.interp(results.change_points, results.times_ms, results.values)
            plot_widget.plot(
                results.change_points, change_y,
                pen=None, symbol='o', symbolBrush='r', symbolSize=8,
                name='Change Points'
            )

        # Mark peaks
        if results.peaks:
            peak_y = np.interp(results.peaks, results.times_ms, results.values)
            plot_widget.plot(
                results.peaks, peak_y,
                pen=None, symbol='t', symbolBrush='g', symbolSize=10,
                name='Peaks'
            )

        # Mark valleys
        if results.valleys:
            valley_y = np.interp(results.valleys, results.times_ms, results.values)
            plot_widget.plot(
                results.valleys, valley_y,
                pen=None, symbol='t1', symbolBrush='b', symbolSize=10,
                name='Valleys'
            )

        plot_widget.addLegend()
        layout.addWidget(plot_widget)

        return widget

    def _create_distribution_tab(self, results: SingleTraceResults) -> QWidget:
        """Create distribution histogram"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        plot_widget = pg.PlotWidget(title=f"Value Distribution: {results.trace_name}")
        plot_widget.setLabel('left', 'Frequency')
        plot_widget.setLabel('bottom', 'Value')

        # Compute histogram
        y, x = np.histogram(results.values, bins=50)
        plot_widget.plot(x, y, stepMode=True, fillLevel=0, brush=(0, 0, 255, 150))

        # Add mean line
        mean_line = pg.InfiniteLine(
            pos=results.mean, angle=90,
            pen=pg.mkPen('r', width=2, style=Qt.DashLine),
            label='Mean'
        )
        plot_widget.addItem(mean_line)

        # Add median line
        median_line = pg.InfiniteLine(
            pos=results.median, angle=90,
            pen=pg.mkPen('g', width=2, style=Qt.DashLine),
            label='Median'
        )
        plot_widget.addItem(median_line)

        layout.addWidget(plot_widget)

        # Stats box
        stats_box = QGroupBox("Statistics")
        stats_layout = QVBoxLayout(stats_box)
        stats_text = QLabel(
            f"Mean: {results.mean:.3f}\n"
            f"Median: {results.median:.3f}\n"
            f"Std Dev: {results.std:.3f}\n"
            f"Range: [{results.min_val:.3f}, {results.max_val:.3f}]\n"
            f"Skewness: {results.skewness:.3f}\n"
            f"Kurtosis: {results.kurtosis:.3f}"
        )
        stats_layout.addWidget(stats_text)
        layout.addWidget(stats_box)

        return widget

    def _create_change_detection_tab(self, results: SingleTraceResults) -> QWidget:
        """Create change detection visualization"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Info text
        info = QLabel(
            f"Detected {len(results.change_points)} change points, "
            f"{len(results.peaks)} peaks, {len(results.valleys)} valleys, "
            f"and {len(results.high_volatility_periods)} high volatility periods."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Critical moments list (clickable)
        if results.change_points or results.peaks or results.valleys:
            moments_box = QGroupBox("Critical Moments (Click to seek video)")
            moments_layout = QVBoxLayout(moments_box)

            moments_list = QListWidget()
            moments_list.setMaximumHeight(150)

            # Add change points
            for ms in sorted(results.change_points)[:20]:  # Limit to first 20
                item = QListWidgetItem(f"⚡ Change Point at {ms / 1000:.2f}s")
                item.setData(Qt.UserRole, ms)
                moments_list.addItem(item)

            # Add peaks
            for ms in sorted(results.peaks)[:10]:  # Limit to first 10
                item = QListWidgetItem(f"🔺 Peak at {ms / 1000:.2f}s")
                item.setData(Qt.UserRole, ms)
                moments_list.addItem(item)

            # Add valleys
            for ms in sorted(results.valleys)[:10]:  # Limit to first 10
                item = QListWidgetItem(f"🔻 Valley at {ms / 1000:.2f}s")
                item.setData(Qt.UserRole, ms)
                moments_list.addItem(item)

            # Wire up click handler
            moments_list.itemClicked.connect(self._on_moment_clicked)

            moments_layout.addWidget(moments_list)
            layout.addWidget(moments_box)

        # Velocity plot (rate of change)
        if len(results.values) > 1:
            velocity_widget = pg.PlotWidget(title="Rate of Change (Velocity)")
            velocity_widget.setLabel('left', 'Change per sample')
            velocity_widget.setLabel('bottom', 'Time', units='ms')

            velocity = np.diff(results.values)
            velocity_times = results.times_ms[:-1]

            velocity_widget.plot(
                velocity_times, velocity,
                pen=pg.mkPen('m', width=1)
            )

            # Zero line
            zero_line = pg.InfiniteLine(
                pos=0, angle=0,
                pen=pg.mkPen('w', width=1, style=Qt.DashLine)
            )
            velocity_widget.addItem(zero_line)

            layout.addWidget(velocity_widget)

        return widget

    # ========================================================================
    # PAIRWISE TABS
    # ========================================================================

    def _add_pairwise_tabs(self, results: PairwiseResults):
        """Add tabs for pairwise analysis"""
        # Dual time series
        dual_tab = self._create_dual_timeseries_tab(results)
        self.tabs.addTab(dual_tab, "📈 Time Series")

        # Distance plot
        dist_tab = self._create_distance_tab(results)
        self.tabs.addTab(dist_tab, "📏 Distance")

        # Scatter plot
        scatter_tab = self._create_scatter_tab(results)
        self.tabs.addTab(scatter_tab, "⚫ Scatter Plot")

        # Correlation
        corr_tab = self._create_correlation_tab(results)
        self.tabs.addTab(corr_tab, "🔗 Correlation")

    def _create_dual_timeseries_tab(self, results: PairwiseResults) -> QWidget:
        """Create dual time series plot"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        plot_widget = pg.PlotWidget(title="Dual Time Series Comparison")
        plot_widget.setLabel('left', 'Value')
        plot_widget.setLabel('bottom', 'Time', units='ms')

        # Plot both traces
        plot_widget.plot(
            results.times_ms, results.trace1_values,
            pen=pg.mkPen('c', width=2),
            name=results.trace1_name
        )
        plot_widget.plot(
            results.times_ms, results.trace2_values,
            pen=pg.mkPen('y', width=2),
            name=results.trace2_name
        )

        # Highlight convergence periods
        for start, end, strength in results.convergence_events:
            region = pg.LinearRegionItem([start, end], brush=(0, 255, 0, 30), movable=False)
            plot_widget.addItem(region)

        # Highlight divergence periods
        for start, end, strength in results.divergence_events:
            region = pg.LinearRegionItem([start, end], brush=(255, 0, 0, 30), movable=False)
            plot_widget.addItem(region)

        plot_widget.addLegend()
        layout.addWidget(plot_widget)

        return widget

    def _create_distance_tab(self, results: PairwiseResults) -> QWidget:
        """Create distance over time plot"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        plot_widget = pg.PlotWidget(title="Distance Over Time")
        plot_widget.setLabel('left', 'Euclidean Distance')
        plot_widget.setLabel('bottom', 'Time', units='ms')

        # Plot distance
        plot_widget.plot(
            results.times_ms, results.distance_over_time,
            pen=pg.mkPen('w', width=2)
        )

        # Mean distance line
        mean_line = pg.InfiniteLine(
            pos=results.mean_distance, angle=0,
            pen=pg.mkPen('g', width=2, style=Qt.DashLine),
            label=f'Mean: {results.mean_distance:.3f}'
        )
        plot_widget.addItem(mean_line)

        layout.addWidget(plot_widget)

        # Stats
        stats_box = QGroupBox("Distance Statistics")
        stats_layout = QVBoxLayout(stats_box)
        stats_text = QLabel(
            f"Mean Distance: {results.mean_distance:.3f}\n"
            f"Min Distance: {results.min_distance:.3f}\n"
            f"Max Distance: {results.max_distance:.3f}\n"
            f"Convergence Events: {len(results.convergence_events)}\n"
            f"Divergence Events: {len(results.divergence_events)}"
        )
        stats_layout.addWidget(stats_text)
        layout.addWidget(stats_box)

        return widget

    def _create_scatter_tab(self, results: PairwiseResults) -> QWidget:
        """Create scatter plot"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        plot_widget = pg.PlotWidget(title=f"{results.trace1_name} vs {results.trace2_name}")
        plot_widget.setLabel('left', results.trace2_name)
        plot_widget.setLabel('bottom', results.trace1_name)

        # Scatter plot
        plot_widget.plot(
            results.trace1_values, results.trace2_values,
            pen=None, symbol='o', symbolSize=3, symbolBrush=(100, 100, 255, 100)
        )

        # Diagonal line (perfect correlation)
        min_val = min(np.min(results.trace1_values), np.min(results.trace2_values))
        max_val = max(np.max(results.trace1_values), np.max(results.trace2_values))
        plot_widget.plot([min_val, max_val], [min_val, max_val], pen=pg.mkPen('r', width=1, style=Qt.DashLine))

        layout.addWidget(plot_widget)

        return widget

    def _create_correlation_tab(self, results: PairwiseResults) -> QWidget:
        """Create correlation information tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Correlation stats
        corr_box = QGroupBox("Correlation Metrics")
        corr_layout = QVBoxLayout(corr_box)

        # Pearson
        pearson_text = QLabel(
            f"<b>Pearson Correlation:</b><br>"
            f"r = {results.pearson_r:.4f}<br>"
            f"p-value = {results.pearson_p:.6f}<br>"
            f"Interpretation: {'Significant' if results.pearson_p < 0.05 else 'Not significant'} linear relationship"
        )
        pearson_text.setWordWrap(True)
        corr_layout.addWidget(pearson_text)

        # Spearman
        spearman_text = QLabel(
            f"<b>Spearman Correlation:</b><br>"
            f"ρ = {results.spearman_r:.4f}<br>"
            f"p-value = {results.spearman_p:.6f}<br>"
            f"Interpretation: {'Significant' if results.spearman_p < 0.05 else 'Not significant'} monotonic relationship"
        )
        spearman_text.setWordWrap(True)
        corr_layout.addWidget(spearman_text)

        layout.addWidget(corr_box)

        # Lead-lag
        lag_box = QGroupBox("Lead-Lag Analysis")
        lag_layout = QVBoxLayout(lag_box)

        lag_text = QLabel(
            f"<b>Optimal Lag:</b> {results.optimal_lag_ms}ms<br>"
            f"<b>Max Cross-Correlation:</b> {results.max_cross_correlation:.4f}<br><br>"
            f"Interpretation: "
            f"{'No clear lead-lag relationship' if abs(results.optimal_lag_ms) < 100 else f'{results.trace1_name} leads by {abs(results.optimal_lag_ms)}ms' if results.optimal_lag_ms > 0 else f'{results.trace2_name} leads by {abs(results.optimal_lag_ms)}ms'}"
        )
        lag_text.setWordWrap(True)
        lag_layout.addWidget(lag_text)

        layout.addWidget(lag_box)

        # Synchronization
        sync_box = QGroupBox("Synchronization")
        sync_layout = QVBoxLayout(sync_box)

        sync_text = QLabel(
            f"<b>Coherence Score:</b> {results.coherence_score:.4f}<br>"
            f"Interpretation: {'High synchronization' if results.coherence_score > 0.7 else 'Moderate synchronization' if results.coherence_score > 0.4 else 'Low synchronization'}"
        )
        sync_text.setWordWrap(True)
        sync_layout.addWidget(sync_text)

        layout.addWidget(sync_box)

        # Critical moments (clickable)
        moments_box = QGroupBox("Critical Moments (Click to seek video)")
        moments_layout = QVBoxLayout(moments_box)

        moments_list = QListWidget()
        moments_list.setMaximumHeight(150)

        # Add convergence events
        for start_ms, end_ms, strength in results.convergence_events[:10]:  # Limit to first 10
            item = QListWidgetItem(f"🟢 Convergence at {start_ms / 1000:.2f}s (strength: {strength:.2f})")
            item.setData(Qt.UserRole, start_ms)
            moments_list.addItem(item)

        # Add divergence events
        for start_ms, end_ms, strength in results.divergence_events[:10]:
            item = QListWidgetItem(f"🔴 Divergence at {start_ms / 1000:.2f}s (strength: {strength:.2f})")
            item.setData(Qt.UserRole, start_ms)
            moments_list.addItem(item)

        # Add simultaneous peaks
        for ms in results.simultaneous_peaks[:10]:
            item = QListWidgetItem(f"⚡ Simultaneous Peak at {ms / 1000:.2f}s")
            item.setData(Qt.UserRole, ms)
            moments_list.addItem(item)

        # Add opposite movements
        for ms in results.opposite_movements[:10]:
            item = QListWidgetItem(f"↔️ Opposite Movement at {ms / 1000:.2f}s")
            item.setData(Qt.UserRole, ms)
            moments_list.addItem(item)

        # Wire up click handler
        moments_list.itemClicked.connect(self._on_moment_clicked)

        moments_layout.addWidget(moments_list)
        layout.addWidget(moments_box)

        layout.addStretch()

        return widget

    # ========================================================================
    # MULTI-TRACE TABS
    # ========================================================================

    def _add_multi_trace_tabs(self, results: MultiTraceResults):
        """Add tabs for multi-trace analysis"""
        # Correlation matrix
        corr_tab = self._create_correlation_matrix_tab(results)
        self.tabs.addTab(corr_tab, "🔗 Correlation Matrix")

        # Time series
        ts_tab = self._create_multi_timeseries_tab(results)
        self.tabs.addTab(ts_tab, "📈 All Traces")

        # PCA (if available)
        if results.pca_available:
            pca_tab = self._create_pca_tab(results)
            self.tabs.addTab(pca_tab, "🎯 PCA")

        # Critical moments
        moments_tab = self._create_critical_moments_tab(results)
        self.tabs.addTab(moments_tab, "⚡ Critical Moments")

    def _create_correlation_matrix_tab(self, results: MultiTraceResults) -> QWidget:
        """Create correlation matrix heatmap"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Create heatmap using ImageItem
        img_widget = pg.ImageView()
        img_widget.setImage(results.correlation_matrix)
        img_widget.view.invertY(False)  # Don't invert Y axis

        layout.addWidget(img_widget)

        # Add trace names
        names_text = "Trace order:\n" + "\n".join([f"{i}: {name}" for i, name in enumerate(results.trace_names)])
        names_label = QLabel(names_text)
        names_label.setWordWrap(True)
        layout.addWidget(names_label)

        return widget

    def _create_multi_timeseries_tab(self, results: MultiTraceResults) -> QWidget:
        """Create multi-trace time series plot"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        plot_widget = pg.PlotWidget(title="All Traces")
        plot_widget.setLabel('left', 'Value')
        plot_widget.setLabel('bottom', 'Time', units='ms')

        # Plot all traces with different colors
        colors = ['c', 'y', 'g', 'm', 'r', 'b', 'w']
        for i, (name, values) in enumerate(results.trace_values.items()):
            color = colors[i % len(colors)]
            plot_widget.plot(
                results.times_ms, values,
                pen=pg.mkPen(color, width=2),
                name=name
            )

        plot_widget.addLegend()
        layout.addWidget(plot_widget)

        return widget

    def _create_pca_tab(self, results: MultiTraceResults) -> QWidget:
        """Create PCA visualization"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Variance explained
        variance_box = QGroupBox("Principal Components")
        variance_layout = QVBoxLayout(variance_box)

        variance_text = "Variance Explained:\n"
        cumulative = 0
        for i, var in enumerate(results.pca_variance_explained[:5]):
            cumulative += var
            variance_text += f"PC{i + 1}: {var * 100:.2f}% (Cumulative: {cumulative * 100:.2f}%)\n"

        variance_label = QLabel(variance_text)
        variance_layout.addWidget(variance_label)
        layout.addWidget(variance_box)

        # Scree plot
        if len(results.pca_variance_explained) > 1:
            scree_widget = pg.PlotWidget(title="Scree Plot")
            scree_widget.setLabel('left', 'Variance Explained')
            scree_widget.setLabel('bottom', 'Principal Component')

            pcs = list(range(1, len(results.pca_variance_explained) + 1))
            scree_widget.plot(
                pcs, results.pca_variance_explained,
                pen=None, symbol='o', symbolBrush='c', symbolSize=10
            )

            layout.addWidget(scree_widget)

        return widget

    def _create_critical_moments_tab(self, results: MultiTraceResults) -> QWidget:
        """Create critical moments visualization"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info_box = QGroupBox("Critical Moments Detected")
        info_layout = QVBoxLayout(info_box)

        info_text = QLabel(
            f"<b>Convergence Moments:</b> {len(results.convergence_moments)}<br>"
            f"Times when all traces move close together<br><br>"
            f"<b>Divergence Moments:</b> {len(results.divergence_moments)}<br>"
            f"Times when traces spread maximally apart<br><br>"
            f"<b>Regime Changes:</b> {len(results.regime_changes)}<br>"
            f"Significant pattern shifts across all traces"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)

        layout.addWidget(info_box)

        # Clickable moments list
        moments_box = QGroupBox("Critical Moments (Click to seek video)")
        moments_layout = QVBoxLayout(moments_box)

        moments_list = QListWidget()

        # Add convergence moments
        for ms in sorted(results.convergence_moments)[:20]:  # Limit to first 20
            item = QListWidgetItem(f"🟢 All-Trace Convergence at {ms / 1000:.2f}s")
            item.setData(Qt.UserRole, ms)
            moments_list.addItem(item)

        # Add divergence moments
        for ms in sorted(results.divergence_moments)[:20]:
            item = QListWidgetItem(f"🔴 Maximum Divergence at {ms / 1000:.2f}s")
            item.setData(Qt.UserRole, ms)
            moments_list.addItem(item)

        # Add regime changes
        for ms in sorted(results.regime_changes)[:20]:
            item = QListWidgetItem(f"⚡ Regime Change at {ms / 1000:.2f}s")
            item.setData(Qt.UserRole, ms)
            moments_list.addItem(item)

        # Wire up click handler
        moments_list.itemClicked.connect(self._on_moment_clicked)

        moments_layout.addWidget(moments_list)
        layout.addWidget(moments_box)

        # Timeline visualization
        if results.convergence_moments or results.divergence_moments:
            timeline_widget = pg.PlotWidget(title="Critical Moments Timeline")
            timeline_widget.setLabel('bottom', 'Time', units='ms')

            # Plot convergence moments
            if results.convergence_moments:
                conv_y = [1] * len(results.convergence_moments)
                timeline_widget.plot(
                    results.convergence_moments, conv_y,
                    pen=None, symbol='o', symbolBrush='g', symbolSize=8,
                    name='Convergence'
                )

            # Plot divergence moments
            if results.divergence_moments:
                div_y = [2] * len(results.divergence_moments)
                timeline_widget.plot(
                    results.divergence_moments, div_y,
                    pen=None, symbol='o', symbolBrush='r', symbolSize=8,
                    name='Divergence'
                )

            # Plot regime changes
            if results.regime_changes:
                regime_y = [3] * len(results.regime_changes)
                timeline_widget.plot(
                    results.regime_changes, regime_y,
                    pen=None, symbol='s', symbolBrush='y', symbolSize=8,
                    name='Regime Changes'
                )

            timeline_widget.addLegend()
            layout.addWidget(timeline_widget)

        layout.addStretch()

        return widget

    def _on_moment_clicked(self, item: QListWidgetItem):
        """Handle click on a critical moment - seek video and close dialog"""
        ms = item.data(Qt.UserRole)

        if ms is not None and self.seek_callback:
            # Close the dialog
            self.close()

            # Seek to the moment
            self.seek_callback(int(ms))


# Standalone test
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)

    # Create mock results for testing
    dialog = ComprehensiveResultsDialog()
    dialog.show()

    sys.exit(app.exec())