# hsparc/analysis/convergence.py
"""
Convergence/Divergence analysis for multi-participant controller input.
Detects moments when participants' inputs align (convergence) or separate (divergence).
Enhanced with correlation matrix and signal-level analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import numpy as np
from scipy import signal, stats
from scipy.spatial.distance import euclidean


@dataclass
class ConvergenceEvent:
    """Represents a detected convergence or divergence event."""
    start_ms: int
    end_ms: int
    event_type: str  # "convergence" or "divergence"
    strength: float  # 0-1, higher = stronger event
    distance: float  # Mean distance during event
    participants: List[str]  # Participant names involved
    description: str  # Human-readable description


@dataclass
class AnalysisResults:
    """Complete results of convergence/divergence analysis."""
    events: List[ConvergenceEvent]
    overall_correlation: float  # Pearson correlation between participants
    mean_distance: float  # Average distance across entire session
    convergence_percentage: float  # % of time in convergent state
    divergence_percentage: float  # % of time in divergent state
    summary_stats: Dict[str, float]  # Additional statistics

    # NEW: Enhanced correlation data
    correlation_matrix: Dict[Tuple[str, str], Tuple[float, float]] = field(
        default_factory=dict)  # (signal1, signal2) -> (r, p_value)
    signal_labels: List[str] = field(default_factory=list)  # All signal names
    _raw_signals: Dict[str, np.ndarray] = field(default_factory=dict)  # For scatterplot access
    _participant_data: Dict[str, Dict[str, np.ndarray]] = field(default_factory=dict)  # Store original data


class ConvergenceAnalyzer:
    """
    Analyzes time-series controller data to detect convergence and divergence.
    Uses windowed distance metrics and statistical thresholds.
    Enhanced with full correlation matrix across all signals.
    """

    def __init__(
            self,
            window_ms: int = 2000,  # 2-second analysis windows
            convergence_threshold: float = 0.3,  # Distance threshold for convergence
            divergence_threshold: float = 0.7,  # Distance threshold for divergence
            min_event_duration_ms: int = 500,  # Minimum event length to report
    ):
        self.window_ms = window_ms
        self.convergence_threshold = convergence_threshold
        self.divergence_threshold = divergence_threshold
        self.min_event_duration_ms = min_event_duration_ms

    def analyze(
            self,
            participant_data: Dict[str, Dict[str, np.ndarray]],
            all_control_signals: Optional[Dict[str, np.ndarray]] = None
    ) -> AnalysisResults:
        """
        Analyze multiple participants' controller data for convergence/divergence.
        """
        print(f"[convergence] analyze() called")
        print(f"[convergence] participant_data keys: {list(participant_data.keys())}")
        print(f"[convergence] all_control_signals is None: {all_control_signals is None}")
        if all_control_signals is not None:
            print(f"[convergence] all_control_signals has {len(all_control_signals)} signals")
            print(f"[convergence] all_control_signals ALL keys: {list(all_control_signals.keys())}")

        try:
            return self._analyze_impl(participant_data, all_control_signals)
        except Exception as e:
            print(f"[convergence] EXCEPTION in analyze: {e}")
            import traceback
            traceback.print_exc()
            return self._empty_results()

    def _analyze_impl(
            self,
            participant_data: Dict[str, Dict[str, np.ndarray]],
            all_control_signals: Optional[Dict[str, np.ndarray]] = None
    ) -> AnalysisResults:
        """Internal implementation of analyze."""
        print(f"[convergence] _analyze_impl START")

        if len(participant_data) < 2:
            print(f"[convergence] Insufficient participants: {len(participant_data)}")
            return AnalysisResults(
                events=[],
                overall_correlation=0.0,
                mean_distance=0.0,
                convergence_percentage=0.0,
                divergence_percentage=0.0,
                summary_stats={},
                correlation_matrix={},
                signal_labels=[],
                _raw_signals={},
                _participant_data={}
            )

        # Get participant names
        participants = list(participant_data.keys())
        print(f"[convergence] Participants: {participants}")

        # Align time series to common time base
        aligned_data = self._align_time_series(participant_data)

        if aligned_data is None:
            print(f"[convergence] Failed to align time series")
            return self._empty_results()

        common_times, signals = aligned_data
        print(f"[convergence] Aligned {len(signals)} participant signals")

        # Calculate windowed distances (for convergence/divergence events)
        distances, distance_times = self._compute_windowed_distances(
            common_times, signals, participants
        )

        # Detect convergence/divergence events
        events = self._detect_events(
            distance_times, distances, participants
        )
        print(f"[convergence] Detected {len(events)} events")

        # Calculate overall statistics
        overall_corr = self._calculate_correlation(signals)
        mean_dist = float(np.mean(distances)) if len(distances) > 0 else 0.0

        # Calculate time percentages
        conv_pct, div_pct = self._calculate_event_percentages(
            events, common_times[-1] if len(common_times) > 0 else 0
        )

        print(f"[convergence] Calculated basic stats, now building correlation matrix")

        # FIXED: Initialize defaults BEFORE conditional block
        correlation_matrix = {}
        signal_labels = []
        raw_signals = {}
        print(f"[convergence] Initialized empty defaults")

        # NEW: Build full correlation matrix across ALL control signals
        print(
            f"[convergence] About to build correlation matrix, all_control_signals: {all_control_signals is not None}")
        if all_control_signals:
            print(f"[convergence] all_control_signals is truthy, calling _build_correlation_matrix")
            print(f"[convergence] Received {len(all_control_signals)} control signals for correlation matrix")

            # FIXED: Properly capture return values
            print(f"[convergence] BEFORE calling _build_correlation_matrix")
            result_tuple = self._build_correlation_matrix(all_control_signals)
            print(f"[convergence] AFTER calling _build_correlation_matrix")
            print(f"[convergence] Result tuple length: {len(result_tuple)}")

            correlation_matrix, signal_labels, raw_signals = result_tuple

            print(f"[convergence] After unpacking")
            print(f"[convergence] signal_labels length: {len(signal_labels)}")
            print(f"[convergence] signal_labels: {signal_labels}")
        else:
            print(f"[convergence] all_control_signals is falsy, using fallback")
            # Fallback to participant-level only
            signal_labels = list(signals.keys())
            raw_signals = signals

        print(f"[convergence] Final signal_labels length: {len(signal_labels)}")
        print(f"[convergence] Final signal_labels: {signal_labels}")

        # Additional summary statistics
        summary_stats = {
            "median_distance": float(np.median(distances)) if len(distances) > 0 else 0.0,
            "std_distance": float(np.std(distances)) if len(distances) > 0 else 0.0,
            "max_distance": float(np.max(distances)) if len(distances) > 0 else 0.0,
            "min_distance": float(np.min(distances)) if len(distances) > 0 else 0.0,
            "num_convergence_events": sum(1 for e in events if e.event_type == "convergence"),
            "num_divergence_events": sum(1 for e in events if e.event_type == "divergence"),
        }

        print(f"[convergence] Creating AnalysisResults")

        result = AnalysisResults(
            events=events,
            overall_correlation=overall_corr,
            mean_distance=mean_dist,
            convergence_percentage=conv_pct,
            divergence_percentage=div_pct,
            summary_stats=summary_stats,
            correlation_matrix=correlation_matrix,
            signal_labels=signal_labels,
            _raw_signals=raw_signals,
            _participant_data=participant_data
        )

        print(f"[convergence] Created result, signal_labels length: {len(result.signal_labels)}")
        print(f"[convergence] Returning result")

        return result

    def _build_correlation_matrix(
            self,
            all_control_signals: Dict[str, np.ndarray]
    ) -> Tuple[Dict[Tuple[str, str], Tuple[float, float]], List[str], Dict[str, np.ndarray]]:
        """
        Build full correlation matrix across ALL control signals (individual traces).

        Args:
            all_control_signals: {"Participant A: ABS_X": aligned_array, "Participant B: BTN_SOUTH": aligned_array, ...}

        Returns:
            (correlation_matrix, signal_labels, raw_signals)
            - correlation_matrix: {(signal1, signal2): (r, p_value)}
            - signal_labels: List of all signal names (e.g., "Participant A: Left Stick X")
            - raw_signals: {signal_name: aligned_data_array}
        """
        correlation_matrix = {}

        # Signal labels are the KEYS of all_control_signals (individual traces)
        signal_labels = sorted(all_control_signals.keys())
        raw_signals = all_control_signals.copy()

        print(f"[convergence] Building correlation matrix for {len(signal_labels)} signals:")
        for label in signal_labels[:10]:  # Show first 10
            print(f"  - {label}")
        if len(signal_labels) > 10:
            print(f"  ... and {len(signal_labels) - 10} more")

        # Calculate all pairwise correlations
        for i, sig1 in enumerate(signal_labels):
            for j, sig2 in enumerate(signal_labels):
                if i >= j:  # Skip diagonal and lower triangle
                    continue

                data1 = raw_signals[sig1]
                data2 = raw_signals[sig2]

                if len(data1) < 2 or len(data2) < 2:
                    continue

                # Ensure same length
                min_len = min(len(data1), len(data2))
                data1 = data1[:min_len]
                data2 = data2[:min_len]

                try:
                    # Calculate Pearson correlation
                    r, p_val = stats.pearsonr(data1, data2)

                    if np.isfinite(r) and np.isfinite(p_val):
                        correlation_matrix[(sig1, sig2)] = (float(r), float(p_val))
                except Exception as e:
                    print(f"[convergence] Correlation failed for {sig1} vs {sig2}: {e}")
                    continue

        print(f"[convergence] Computed {len(correlation_matrix)} pairwise correlations")

        return correlation_matrix, signal_labels, raw_signals

    def _align_time_series(
            self,
            participant_data: Dict[str, Dict[str, np.ndarray]]
    ) -> Optional[Tuple[np.ndarray, Dict[str, np.ndarray]]]:
        """
        Align all participants to a common time base via interpolation.

        Returns:
            (common_times, {participant: interpolated_values})
        """
        if not participant_data:
            return None

        # Find common time range
        min_time = max(data["times_ms"][0] for data in participant_data.values() if len(data["times_ms"]) > 0)
        max_time = min(data["times_ms"][-1] for data in participant_data.values() if len(data["times_ms"]) > 0)

        # FIXED: Use broadest range if no overlap (same as researcher.py)
        if min_time >= max_time:
            print(f"[convergence] No time overlap in participant data, using broadest range")
            min_time = min(data["times_ms"][0] for data in participant_data.values() if len(data["times_ms"]) > 0)
            max_time = max(data["times_ms"][-1] for data in participant_data.values() if len(data["times_ms"]) > 0)
            print(f"[convergence] Broadest range: {min_time:.0f}ms to {max_time:.0f}ms")

        if min_time >= max_time:
            return None

        # Create common time base (1ms resolution)
        common_times = np.arange(min_time, max_time, 1, dtype=float)

        # Interpolate each participant's data to common time base
        aligned_signals = {}
        for participant, data in participant_data.items():
            times = data["times_ms"]
            values = data["values"]

            if len(times) < 2:
                continue

            # Interpolate to common time base
            interpolated = np.interp(common_times, times, values)
            aligned_signals[participant] = interpolated

        if len(aligned_signals) < 2:
            return None

        return common_times, aligned_signals

    def _compute_windowed_distances(
            self,
            times: np.ndarray,
            signals: Dict[str, np.ndarray],
            participants: List[str]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute Euclidean distance between participants over sliding windows.

        Returns:
            (distances, window_center_times)
        """
        if len(participants) < 2:
            return np.array([]), np.array([])

        # Use first two participants for pairwise analysis
        p1, p2 = participants[0], participants[1]
        signal1 = signals[p1]
        signal2 = signals[p2]

        window_samples = self.window_ms
        hop_samples = window_samples // 4  # 75% overlap

        distances = []
        window_times = []

        for start_idx in range(0, len(times) - window_samples, hop_samples):
            end_idx = start_idx + window_samples

            if end_idx > len(times):
                break

            # Extract window
            window1 = signal1[start_idx:end_idx]
            window2 = signal2[start_idx:end_idx]

            # Calculate normalized Euclidean distance
            dist = np.sqrt(np.mean((window1 - window2) ** 2))

            # Normalize by signal range (0-1 scale)
            signal_range = max(
                np.std(signal1[start_idx:end_idx]),
                np.std(signal2[start_idx:end_idx]),
                0.01  # Avoid division by zero
            )
            normalized_dist = min(dist / signal_range, 1.0)

            distances.append(normalized_dist)
            window_times.append(times[start_idx + window_samples // 2])

        return np.array(distances), np.array(window_times)

    def _detect_events(
            self,
            times: np.ndarray,
            distances: np.ndarray,
            participants: List[str]
    ) -> List[ConvergenceEvent]:
        """
        Detect convergence and divergence events based on distance thresholds.
        """
        events = []

        if len(distances) == 0:
            return events

        # Identify convergence regions (distance < threshold)
        convergent = distances < self.convergence_threshold

        # Identify divergence regions (distance > threshold)
        divergent = distances > self.divergence_threshold

        # Find contiguous regions
        conv_events = self._extract_regions(times, distances, convergent, "convergence", participants)
        div_events = self._extract_regions(times, distances, divergent, "divergence", participants)

        events.extend(conv_events)
        events.extend(div_events)

        # Sort by time
        events.sort(key=lambda e: e.start_ms)

        return events

    def _extract_regions(
            self,
            times: np.ndarray,
            distances: np.ndarray,
            mask: np.ndarray,
            event_type: str,
            participants: List[str]
    ) -> List[ConvergenceEvent]:
        """Extract contiguous regions where mask is True."""
        events = []

        # Find starts and ends of True regions
        padded = np.concatenate([[False], mask, [False]])
        diff = np.diff(padded.astype(int))
        starts = np.where(diff == 1)[0]
        ends = np.where(diff == -1)[0]

        for start_idx, end_idx in zip(starts, ends):
            if end_idx <= start_idx:
                continue

            start_ms = int(times[start_idx])
            end_ms = int(times[end_idx - 1])
            duration = end_ms - start_ms

            # Filter out short events
            if duration < self.min_event_duration_ms:
                continue

            # Calculate event strength (inverse of distance for convergence)
            region_distances = distances[start_idx:end_idx]
            mean_distance = float(np.mean(region_distances))

            if event_type == "convergence":
                strength = 1.0 - mean_distance
                desc = f"Participants moving in sync (distance: {mean_distance:.3f})"
            else:
                strength = mean_distance
                desc = f"Participants diverging (distance: {mean_distance:.3f})"

            events.append(ConvergenceEvent(
                start_ms=start_ms,
                end_ms=end_ms,
                event_type=event_type,
                strength=strength,
                distance=mean_distance,
                participants=participants[:2],
                description=desc
            ))

        return events

    def _calculate_correlation(self, signals: Dict[str, np.ndarray]) -> float:
        """Calculate overall Pearson correlation between participants."""
        if len(signals) < 2:
            return 0.0

        participants = list(signals.keys())
        s1 = signals[participants[0]]
        s2 = signals[participants[1]]

        if len(s1) < 2 or len(s2) < 2:
            return 0.0

        try:
            corr, _ = stats.pearsonr(s1, s2)
            return float(corr) if np.isfinite(corr) else 0.0
        except Exception:
            return 0.0

    def _calculate_event_percentages(
            self,
            events: List[ConvergenceEvent],
            total_duration_ms: float
    ) -> Tuple[float, float]:
        """Calculate percentage of time in convergent/divergent states."""
        if total_duration_ms <= 0:
            return 0.0, 0.0

        conv_time = sum(
            e.end_ms - e.start_ms
            for e in events
            if e.event_type == "convergence"
        )

        div_time = sum(
            e.end_ms - e.start_ms
            for e in events
            if e.event_type == "divergence"
        )

        conv_pct = (conv_time / total_duration_ms) * 100
        div_pct = (div_time / total_duration_ms) * 100

        return conv_pct, div_pct

    def _empty_results(self) -> AnalysisResults:
        """Return empty results structure."""
        return AnalysisResults(
            events=[],
            overall_correlation=0.0,
            mean_distance=0.0,
            convergence_percentage=0.0,
            divergence_percentage=0.0,
            summary_stats={},
            correlation_matrix={},
            signal_labels=[],
            _raw_signals={},
            _participant_data={}
        )