# hsparc/analysis/comprehensive_analyzer.py
"""
Comprehensive analysis for video-synchronized input traces.
Adapts analysis type based on number of selected traces (1, 2, or n>2).
Implements the full analysis strategy from analysis_strategy.txt
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
import numpy as np
from scipy import signal, stats
from scipy.spatial.distance import euclidean, pdist, squareform
from scipy.signal import find_peaks
import warnings

# Suppress scipy warnings for cleaner output
warnings.filterwarnings('ignore', category=RuntimeWarning)

try:
    from sklearn.decomposition import PCA
    from sklearn.cluster import KMeans

    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    print("[analyzer] sklearn not available - PCA and clustering disabled")


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class SingleTraceResults:
    """Results from single trace analysis (n=1)"""
    trace_name: str

    # Descriptive statistics
    mean: float
    median: float
    std: float
    min_val: float
    max_val: float
    range_val: float
    skewness: float
    kurtosis: float
    q25: float
    q75: float
    iqr: float

    # Temporal characteristics
    duration_ms: int
    num_samples: int
    activity_rate: float  # Events or samples per second
    percent_active: float  # Percentage of time with significant change

    # Change detection
    change_points: List[int] = field(default_factory=list)  # Timestamps of significant changes
    peaks: List[int] = field(default_factory=list)  # Timestamps of peaks
    valleys: List[int] = field(default_factory=list)  # Timestamps of valleys
    high_volatility_periods: List[Tuple[int, int]] = field(default_factory=list)  # (start_ms, end_ms)

    # Raw data for plotting
    times_ms: np.ndarray = field(default_factory=lambda: np.array([]))
    values: np.ndarray = field(default_factory=lambda: np.array([]))


@dataclass
class PairwiseResults:
    """Results from two-trace analysis (n=2)"""
    trace1_name: str
    trace2_name: str

    # Relationship metrics
    pearson_r: float
    pearson_p: float
    spearman_r: float
    spearman_p: float

    # Convergence/divergence
    mean_distance: float
    min_distance: float
    max_distance: float
    convergence_events: List[Tuple[int, int, float]] = field(default_factory=list)  # (start, end, strength)
    divergence_events: List[Tuple[int, int, float]] = field(default_factory=list)

    # Lead-lag
    optimal_lag_ms: int = 0
    max_cross_correlation: float = 0.0

    # Synchronization
    coherence_score: float = 0.0

    # Critical moments
    simultaneous_peaks: List[int] = field(default_factory=list)
    opposite_movements: List[int] = field(default_factory=list)

    # Raw data for plotting
    times_ms: np.ndarray = field(default_factory=lambda: np.array([]))
    trace1_values: np.ndarray = field(default_factory=lambda: np.array([]))
    trace2_values: np.ndarray = field(default_factory=lambda: np.array([]))
    distance_over_time: np.ndarray = field(default_factory=lambda: np.array([]))


@dataclass
class MultiTraceResults:
    """Results from multi-trace analysis (n>2)"""
    trace_names: List[str]
    num_traces: int

    # Correlation structure
    correlation_matrix: np.ndarray = field(default_factory=lambda: np.array([]))
    p_value_matrix: np.ndarray = field(default_factory=lambda: np.array([]))

    # PCA (if sklearn available)
    pca_variance_explained: List[float] = field(default_factory=list)
    pca_components: np.ndarray = field(default_factory=lambda: np.array([]))
    pca_available: bool = False

    # Clustering (if sklearn available)
    cluster_labels: np.ndarray = field(default_factory=lambda: np.array([]))
    n_clusters: int = 0
    clustering_available: bool = False

    # Critical moments
    convergence_moments: List[int] = field(default_factory=list)  # When all traces converge
    divergence_moments: List[int] = field(default_factory=list)  # Maximum spread
    regime_changes: List[int] = field(default_factory=list)  # Significant pattern shifts

    # Raw data
    times_ms: np.ndarray = field(default_factory=lambda: np.array([]))
    trace_values: Dict[str, np.ndarray] = field(default_factory=dict)  # {trace_name: values_array}


@dataclass
class ComprehensiveResults:
    """Top-level results container that holds the appropriate analysis type"""
    analysis_type: str  # "single", "pairwise", "multi"

    single: Optional[SingleTraceResults] = None
    pairwise: Optional[PairwiseResults] = None
    multi: Optional[MultiTraceResults] = None

    # Summary
    summary_text: str = ""


# ============================================================================
# MAIN ANALYZER CLASS
# ============================================================================

class ComprehensiveTraceAnalyzer:
    """
    Comprehensive analyzer that adapts to trace count.
    - n=1: Descriptive statistics, change detection, segmentation
    - n=2: Correlation, convergence/divergence, lead-lag, synchronization
    - n>2: Correlation matrix, PCA, clustering, network analysis
    """

    def __init__(
            self,
            convergence_threshold: float = 0.3,
            divergence_threshold: float = 0.7,
            change_sensitivity: float = 2.0,  # Std devs for change point detection
            window_ms: int = 2000
    ):
        self.convergence_threshold = convergence_threshold
        self.divergence_threshold = divergence_threshold
        self.change_sensitivity = change_sensitivity
        self.window_ms = window_ms

    def analyze(
            self,
            trace_data: Dict[str, Dict[str, np.ndarray]]
    ) -> ComprehensiveResults:
        """
        Main analysis entry point.

        Args:
            trace_data: Dict of {trace_name: {"times_ms": array, "values": array}}

        Returns:
            ComprehensiveResults with appropriate analysis type
        """
        n_traces = len(trace_data)

        print(f"[analyzer] Starting analysis with {n_traces} trace(s)")

        if n_traces == 0:
            return self._empty_results()
        elif n_traces == 1:
            return self._analyze_single(trace_data)
        elif n_traces == 2:
            return self._analyze_pairwise(trace_data)
        else:
            return self._analyze_multi(trace_data)

    # ========================================================================
    # SINGLE TRACE ANALYSIS (n=1)
    # ========================================================================

    def _analyze_single(self, trace_data: Dict[str, Dict[str, np.ndarray]]) -> ComprehensiveResults:
        """Analyze a single trace"""
        trace_name = list(trace_data.keys())[0]
        data = trace_data[trace_name]
        times_ms = data["times_ms"]
        values = data["values"]

        print(f"[analyzer] Single trace analysis: {trace_name}")
        print(f"[analyzer]   {len(times_ms)} samples, duration {times_ms[-1] if len(times_ms) > 0 else 0}ms")

        # Descriptive statistics
        mean_val = float(np.mean(values))
        median_val = float(np.median(values))
        std_val = float(np.std(values))
        min_val = float(np.min(values))
        max_val = float(np.max(values))
        range_val = max_val - min_val

        skew = float(stats.skew(values)) if len(values) > 2 else 0.0
        kurt = float(stats.kurtosis(values)) if len(values) > 2 else 0.0

        q25 = float(np.percentile(values, 25))
        q75 = float(np.percentile(values, 75))
        iqr = q75 - q25

        # Temporal characteristics
        duration_ms = int(times_ms[-1] - times_ms[0]) if len(times_ms) > 1 else 0
        num_samples = len(values)
        activity_rate = (num_samples / (duration_ms / 1000.0)) if duration_ms > 0 else 0.0

        # Percent active (significant changes)
        if len(values) > 1:
            diffs = np.abs(np.diff(values))
            threshold = std_val * 0.1  # 10% of std dev
            active_samples = np.sum(diffs > threshold)
            percent_active = (active_samples / len(diffs)) * 100
        else:
            percent_active = 0.0

        # Change point detection
        change_points = self._detect_change_points(times_ms, values)

        # Peak detection
        peaks, valleys = self._detect_peaks_valleys(times_ms, values)

        # Volatility periods
        volatility_periods = self._detect_volatility_periods(times_ms, values)

        results = SingleTraceResults(
            trace_name=trace_name,
            mean=mean_val,
            median=median_val,
            std=std_val,
            min_val=min_val,
            max_val=max_val,
            range_val=range_val,
            skewness=skew,
            kurtosis=kurt,
            q25=q25,
            q75=q75,
            iqr=iqr,
            duration_ms=duration_ms,
            num_samples=num_samples,
            activity_rate=activity_rate,
            percent_active=percent_active,
            change_points=change_points,
            peaks=peaks,
            valleys=valleys,
            high_volatility_periods=volatility_periods,
            times_ms=times_ms,
            values=values
        )

        summary = self._generate_single_summary(results)

        return ComprehensiveResults(
            analysis_type="single",
            single=results,
            summary_text=summary
        )

    # ========================================================================
    # PAIRWISE ANALYSIS (n=2)
    # ========================================================================

    def _analyze_pairwise(self, trace_data: Dict[str, Dict[str, np.ndarray]]) -> ComprehensiveResults:
        """Analyze two traces"""
        names = list(trace_data.keys())
        trace1_name, trace2_name = names[0], names[1]

        data1 = trace_data[trace1_name]
        data2 = trace_data[trace2_name]

        print(f"[analyzer] Pairwise analysis: {trace1_name} vs {trace2_name}")

        # Align traces to common timeline
        times_ms, values1, values2 = self._align_traces(data1, data2)

        if len(times_ms) < 2:
            return self._empty_results()

        # Correlation metrics
        pearson_r, pearson_p = stats.pearsonr(values1, values2)
        spearman_r, spearman_p = stats.spearmanr(values1, values2)

        # Distance metrics
        distances = np.array([euclidean([v1], [v2]) for v1, v2 in zip(values1, values2)])
        mean_dist = float(np.mean(distances))
        min_dist = float(np.min(distances))
        max_dist = float(np.max(distances))

        # Convergence/divergence events
        conv_events, div_events = self._detect_convergence_divergence(times_ms, distances)

        # Lead-lag analysis
        optimal_lag, max_cc = self._compute_lead_lag(values1, values2, times_ms)

        # Synchronization
        coherence = self._compute_coherence(values1, values2)

        # Critical moments
        sim_peaks = self._detect_simultaneous_peaks(times_ms, values1, values2)
        opp_movements = self._detect_opposite_movements(times_ms, values1, values2)

        results = PairwiseResults(
            trace1_name=trace1_name,
            trace2_name=trace2_name,
            pearson_r=float(pearson_r),
            pearson_p=float(pearson_p),
            spearman_r=float(spearman_r),
            spearman_p=float(spearman_p),
            mean_distance=mean_dist,
            min_distance=min_dist,
            max_distance=max_dist,
            convergence_events=conv_events,
            divergence_events=div_events,
            optimal_lag_ms=optimal_lag,
            max_cross_correlation=max_cc,
            coherence_score=coherence,
            simultaneous_peaks=sim_peaks,
            opposite_movements=opp_movements,
            times_ms=times_ms,
            trace1_values=values1,
            trace2_values=values2,
            distance_over_time=distances
        )

        summary = self._generate_pairwise_summary(results)

        return ComprehensiveResults(
            analysis_type="pairwise",
            pairwise=results,
            summary_text=summary
        )

    # ========================================================================
    # MULTI-TRACE ANALYSIS (n>2)
    # ========================================================================

    def _analyze_multi(self, trace_data: Dict[str, Dict[str, np.ndarray]]) -> ComprehensiveResults:
        """Analyze multiple traces"""
        trace_names = list(trace_data.keys())
        n_traces = len(trace_names)

        print(f"[analyzer] Multi-trace analysis: {n_traces} traces")

        # Align all traces to common timeline
        aligned_data = self._align_multiple_traces(trace_data)
        times_ms = aligned_data["times_ms"]
        trace_values = aligned_data["values"]

        if len(times_ms) < 2:
            return self._empty_results()

        # Build data matrix (samples x traces)
        data_matrix = np.column_stack([trace_values[name] for name in trace_names])

        # Correlation matrix
        corr_matrix, p_matrix = self._compute_correlation_matrix(data_matrix)

        # PCA (if available)
        pca_results = self._compute_pca(data_matrix) if HAS_SKLEARN else None

        # Clustering (if available)
        cluster_results = self._compute_clustering(data_matrix) if HAS_SKLEARN else None

        # Critical moments
        conv_moments = self._detect_multi_convergence(times_ms, data_matrix)
        div_moments = self._detect_multi_divergence(times_ms, data_matrix)
        regime_changes = self._detect_regime_changes(times_ms, data_matrix)

        results = MultiTraceResults(
            trace_names=trace_names,
            num_traces=n_traces,
            correlation_matrix=corr_matrix,
            p_value_matrix=p_matrix,
            pca_variance_explained=pca_results["variance"] if pca_results else [],
            pca_components=pca_results["components"] if pca_results else np.array([]),
            pca_available=pca_results is not None,
            cluster_labels=cluster_results["labels"] if cluster_results else np.array([]),
            n_clusters=cluster_results["n_clusters"] if cluster_results else 0,
            clustering_available=cluster_results is not None,
            convergence_moments=conv_moments,
            divergence_moments=div_moments,
            regime_changes=regime_changes,
            times_ms=times_ms,
            trace_values=trace_values
        )

        summary = self._generate_multi_summary(results)

        return ComprehensiveResults(
            analysis_type="multi",
            multi=results,
            summary_text=summary
        )

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _detect_change_points(self, times_ms: np.ndarray, values: np.ndarray) -> List[int]:
        """Detect significant change points in a trace"""
        if len(values) < 3:
            return []

        # Compute rolling std deviation
        window_size = min(20, len(values) // 4)
        if window_size < 2:
            return []

        # Use absolute differences
        diffs = np.abs(np.diff(values))
        threshold = np.mean(diffs) + self.change_sensitivity * np.std(diffs)

        change_indices = np.where(diffs > threshold)[0]
        change_times = [int(times_ms[i]) for i in change_indices if i < len(times_ms)]

        return change_times

    def _detect_peaks_valleys(self, times_ms: np.ndarray, values: np.ndarray) -> Tuple[List[int], List[int]]:
        """Detect peaks and valleys"""
        if len(values) < 3:
            return [], []

        # Find peaks
        peak_indices, _ = find_peaks(values, distance=10)
        valley_indices, _ = find_peaks(-values, distance=10)

        peaks = [int(times_ms[i]) for i in peak_indices if i < len(times_ms)]
        valleys = [int(times_ms[i]) for i in valley_indices if i < len(times_ms)]

        return peaks, valleys

    def _detect_volatility_periods(self, times_ms: np.ndarray, values: np.ndarray) -> List[Tuple[int, int]]:
        """Detect periods of high volatility"""
        if len(values) < self.window_ms // 10:
            return []

        # Compute rolling variance
        window = min(50, len(values) // 10)
        if window < 2:
            return []

        variances = np.array([np.var(values[max(0, i - window):i + 1]) for i in range(len(values))])
        threshold = np.mean(variances) + np.std(variances)

        # Find contiguous high-variance regions
        high_var = variances > threshold
        periods = []
        in_period = False
        start = 0

        for i, is_high in enumerate(high_var):
            if is_high and not in_period:
                start = i
                in_period = True
            elif not is_high and in_period:
                if i - start > 5:  # Minimum period length
                    periods.append((int(times_ms[start]), int(times_ms[i - 1])))
                in_period = False

        return periods

    def _align_traces(
            self,
            data1: Dict[str, np.ndarray],
            data2: Dict[str, np.ndarray]
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Align two traces to common timeline using forward-fill"""
        times1, values1 = data1["times_ms"], data1["values"]
        times2, values2 = data2["times_ms"], data2["values"]

        # Find common time range
        min_time = max(times1[0], times2[0])
        max_time = min(times1[-1], times2[-1])

        # Create common timeline
        all_times = np.unique(np.concatenate([times1, times2]))
        common_times = all_times[(all_times >= min_time) & (all_times <= max_time)]

        # Interpolate with forward-fill
        aligned_values1 = np.interp(common_times, times1, values1)
        aligned_values2 = np.interp(common_times, times2, values2)

        return common_times, aligned_values1, aligned_values2

    def _align_multiple_traces(self, trace_data: Dict[str, Dict[str, np.ndarray]]) -> Dict:
        """Align multiple traces to common timeline"""
        all_times_list = [data["times_ms"] for data in trace_data.values()]

        # Find common time range
        min_time = max(times[0] for times in all_times_list)
        max_time = min(times[-1] for times in all_times_list)

        # Create common timeline
        all_times_concat = np.concatenate(all_times_list)
        unique_times = np.unique(all_times_concat)
        common_times = unique_times[(unique_times >= min_time) & (unique_times <= max_time)]

        # Interpolate all traces
        aligned_values = {}
        for name, data in trace_data.items():
            aligned_values[name] = np.interp(common_times, data["times_ms"], data["values"])

        return {
            "times_ms": common_times,
            "values": aligned_values
        }

    def _detect_convergence_divergence(
            self,
            times_ms: np.ndarray,
            distances: np.ndarray
    ) -> Tuple[List[Tuple[int, int, float]], List[Tuple[int, int, float]]]:
        """Detect convergence and divergence events"""
        if len(distances) < 10:
            return [], []

        # Normalize distances to 0-1
        d_min, d_max = np.min(distances), np.max(distances)
        if d_max - d_min < 0.001:
            return [], []

        norm_dist = (distances - d_min) / (d_max - d_min)

        convergence_events = []
        divergence_events = []

        # Find periods of low/high distance
        in_convergence = False
        in_divergence = False
        start_idx = 0

        for i, d in enumerate(norm_dist):
            if d < self.convergence_threshold and not in_convergence:
                start_idx = i
                in_convergence = True
            elif d >= self.convergence_threshold and in_convergence:
                duration_ms = int(times_ms[i - 1] - times_ms[start_idx])
                if duration_ms > 500:  # Minimum duration
                    strength = 1.0 - np.mean(norm_dist[start_idx:i])
                    convergence_events.append((int(times_ms[start_idx]), int(times_ms[i - 1]), float(strength)))
                in_convergence = False

            if d > self.divergence_threshold and not in_divergence:
                start_idx = i
                in_divergence = True
            elif d <= self.divergence_threshold and in_divergence:
                duration_ms = int(times_ms[i - 1] - times_ms[start_idx])
                if duration_ms > 500:
                    strength = np.mean(norm_dist[start_idx:i])
                    divergence_events.append((int(times_ms[start_idx]), int(times_ms[i - 1]), float(strength)))
                in_divergence = False

        return convergence_events, divergence_events

    def _compute_lead_lag(
            self,
            values1: np.ndarray,
            values2: np.ndarray,
            times_ms: np.ndarray
    ) -> Tuple[int, float]:
        """Compute lead-lag relationship using cross-correlation"""
        if len(values1) < 10:
            return 0, 0.0

        # Compute cross-correlation
        correlation = np.correlate(values1 - np.mean(values1), values2 - np.mean(values2), mode='full')
        correlation = correlation / (np.std(values1) * np.std(values2) * len(values1))

        # Find peak
        lags = np.arange(-len(values1) + 1, len(values1))
        max_idx = np.argmax(np.abs(correlation))
        optimal_lag_samples = int(lags[max_idx])

        # Convert to milliseconds
        if len(times_ms) > 1:
            avg_interval_ms = (times_ms[-1] - times_ms[0]) / (len(times_ms) - 1)
            optimal_lag_ms = int(optimal_lag_samples * avg_interval_ms)
        else:
            optimal_lag_ms = 0

        max_cc = float(correlation[max_idx])

        return optimal_lag_ms, max_cc

    def _compute_coherence(self, values1: np.ndarray, values2: np.ndarray) -> float:
        """Compute coherence between two signals"""
        if len(values1) < 10:
            return 0.0

        try:
            # Simple coherence based on correlation of differences
            diff1 = np.diff(values1)
            diff2 = np.diff(values2)

            if len(diff1) > 0 and len(diff2) > 0:
                corr, _ = stats.pearsonr(diff1, diff2)
                return float(np.abs(corr))
            else:
                return 0.0
        except:
            return 0.0

    def _detect_simultaneous_peaks(
            self,
            times_ms: np.ndarray,
            values1: np.ndarray,
            values2: np.ndarray
    ) -> List[int]:
        """Detect moments when both traces peak simultaneously"""
        if len(values1) < 3:
            return []

        peaks1, _ = find_peaks(values1, distance=10)
        peaks2, _ = find_peaks(values2, distance=10)

        # Find peaks within 500ms of each other
        simultaneous = []
        window_ms = 500

        for p1 in peaks1:
            t1 = times_ms[p1]
            for p2 in peaks2:
                t2 = times_ms[p2]
                if abs(t1 - t2) < window_ms:
                    simultaneous.append(int((t1 + t2) / 2))
                    break

        return simultaneous

    def _detect_opposite_movements(
            self,
            times_ms: np.ndarray,
            values1: np.ndarray,
            values2: np.ndarray
    ) -> List[int]:
        """Detect moments when traces move in opposite directions"""
        if len(values1) < 2:
            return []

        diff1 = np.diff(values1)
        diff2 = np.diff(values2)

        # Find where signs differ and magnitudes are significant
        threshold = max(np.std(diff1), np.std(diff2)) * 0.5
        opposite = np.where(
            (diff1 * diff2 < 0) &  # Opposite signs
            (np.abs(diff1) > threshold) &
            (np.abs(diff2) > threshold)
        )[0]

        opposite_times = [int(times_ms[i]) for i in opposite if i < len(times_ms) - 1]

        return opposite_times

    def _compute_correlation_matrix(self, data_matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Compute correlation matrix with p-values"""
        n_traces = data_matrix.shape[1]
        corr_matrix = np.zeros((n_traces, n_traces))
        p_matrix = np.zeros((n_traces, n_traces))

        for i in range(n_traces):
            for j in range(n_traces):
                if i == j:
                    corr_matrix[i, j] = 1.0
                    p_matrix[i, j] = 0.0
                else:
                    r, p = stats.pearsonr(data_matrix[:, i], data_matrix[:, j])
                    corr_matrix[i, j] = r
                    p_matrix[i, j] = p

        return corr_matrix, p_matrix

    def _compute_pca(self, data_matrix: np.ndarray) -> Optional[Dict]:
        """Compute PCA if sklearn available"""
        if not HAS_SKLEARN:
            return None

        try:
            pca = PCA()
            pca.fit(data_matrix)

            return {
                "variance": pca.explained_variance_ratio_.tolist(),
                "components": pca.components_
            }
        except:
            return None

    def _compute_clustering(self, data_matrix: np.ndarray) -> Optional[Dict]:
        """Compute k-means clustering if sklearn available"""
        if not HAS_SKLEARN:
            return None

        try:
            # Use elbow method to find optimal k (up to 5 clusters)
            n_samples = data_matrix.shape[0]
            max_k = min(5, n_samples // 10)

            if max_k < 2:
                return None

            kmeans = KMeans(n_clusters=max_k, random_state=42, n_init=10)
            labels = kmeans.fit_predict(data_matrix)

            return {
                "labels": labels,
                "n_clusters": max_k
            }
        except:
            return None

    def _detect_multi_convergence(self, times_ms: np.ndarray, data_matrix: np.ndarray) -> List[int]:
        """Detect moments when all traces converge"""
        if data_matrix.shape[1] < 2:
            return []

        # Compute pairwise distances at each time point
        convergence_moments = []

        for i in range(len(times_ms)):
            point = data_matrix[i, :]
            distances = pdist(point.reshape(-1, 1))
            mean_distance = np.mean(distances)

            # Converged if mean distance is small
            if mean_distance < self.convergence_threshold:
                convergence_moments.append(int(times_ms[i]))

        return convergence_moments

    def _detect_multi_divergence(self, times_ms: np.ndarray, data_matrix: np.ndarray) -> List[int]:
        """Detect moments of maximum divergence across all traces"""
        if data_matrix.shape[1] < 2:
            return []

        divergence_moments = []

        for i in range(len(times_ms)):
            point = data_matrix[i, :]
            distances = pdist(point.reshape(-1, 1))
            mean_distance = np.mean(distances)

            # Diverged if mean distance is large
            if mean_distance > self.divergence_threshold:
                divergence_moments.append(int(times_ms[i]))

        return divergence_moments

    def _detect_regime_changes(self, times_ms: np.ndarray, data_matrix: np.ndarray) -> List[int]:
        """Detect significant pattern shifts across all traces"""
        if len(times_ms) < 20:
            return []

        # Compute rolling covariance
        window = min(20, len(times_ms) // 5)
        regime_changes = []

        for i in range(window, len(times_ms) - window):
            before = data_matrix[i - window:i, :]
            after = data_matrix[i:i + window, :]

            # Compare covariance structure
            try:
                cov_before = np.cov(before.T)
                cov_after = np.cov(after.T)
                diff = np.linalg.norm(cov_before - cov_after)

                # Threshold based on typical differences
                if i == window:
                    typical_diff = diff
                elif diff > 2 * typical_diff:
                    regime_changes.append(int(times_ms[i]))
            except:
                continue

        return regime_changes

    # ========================================================================
    # SUMMARY GENERATION
    # ========================================================================

    def _generate_single_summary(self, results: SingleTraceResults) -> str:
        """Generate text summary for single trace"""
        return f"""SINGLE TRACE ANALYSIS: {results.trace_name}

DESCRIPTIVE STATISTICS:
  Mean: {results.mean:.3f}
  Median: {results.median:.3f}
  Std Dev: {results.std:.3f}
  Range: [{results.min_val:.3f}, {results.max_val:.3f}]
  Skewness: {results.skewness:.3f}
  Kurtosis: {results.kurtosis:.3f}
  IQR: {results.iqr:.3f}

TEMPORAL CHARACTERISTICS:
  Duration: {results.duration_ms}ms ({results.duration_ms / 1000:.1f}s)
  Samples: {results.num_samples}
  Activity Rate: {results.activity_rate:.1f} samples/sec
  Active: {results.percent_active:.1f}% of time

CHANGE DETECTION:
  Change Points: {len(results.change_points)}
  Peaks: {len(results.peaks)}
  Valleys: {len(results.valleys)}
  High Volatility Periods: {len(results.high_volatility_periods)}
"""

    def _generate_pairwise_summary(self, results: PairwiseResults) -> str:
        """Generate text summary for pairwise analysis"""
        return f"""PAIRWISE ANALYSIS: {results.trace1_name} vs {results.trace2_name}

CORRELATION:
  Pearson r: {results.pearson_r:.3f} (p={results.pearson_p:.4f})
  Spearman r: {results.spearman_r:.3f} (p={results.spearman_p:.4f})

DISTANCE METRICS:
  Mean Distance: {results.mean_distance:.3f}
  Min Distance: {results.min_distance:.3f}
  Max Distance: {results.max_distance:.3f}

CONVERGENCE/DIVERGENCE:
  Convergence Events: {len(results.convergence_events)}
  Divergence Events: {len(results.divergence_events)}

LEAD-LAG:
  Optimal Lag: {results.optimal_lag_ms}ms
  Max Cross-Correlation: {results.max_cross_correlation:.3f}

SYNCHRONIZATION:
  Coherence Score: {results.coherence_score:.3f}

CRITICAL MOMENTS:
  Simultaneous Peaks: {len(results.simultaneous_peaks)}
  Opposite Movements: {len(results.opposite_movements)}
"""

    def _generate_multi_summary(self, results: MultiTraceResults) -> str:
        """Generate text summary for multi-trace analysis"""
        corr_values = results.correlation_matrix[np.triu_indices_from(results.correlation_matrix, k=1)]
        avg_corr = np.mean(corr_values)

        # Use absolute values to find strongest/weakest correlation magnitude
        abs_corr_values = np.abs(corr_values)
        strongest_idx = np.argmax(abs_corr_values)
        weakest_idx = np.argmin(abs_corr_values)
        strongest_corr = corr_values[strongest_idx]
        weakest_corr = corr_values[weakest_idx]

        summary = f"""MULTI-TRACE ANALYSIS: {results.num_traces} traces

CORRELATION STRUCTURE:
  Average Correlation: {avg_corr:.3f}
  Strongest Correlation: {strongest_corr:.3f} (|r|={abs(strongest_corr):.3f})
  Weakest Correlation: {weakest_corr:.3f} (|r|={abs(weakest_corr):.3f})
"""

        if results.pca_available and len(results.pca_variance_explained) > 0:
            summary += f"\nPCA RESULTS:\n"
            for i, var in enumerate(results.pca_variance_explained[:3]):
                summary += f"  PC{i + 1}: {var * 100:.1f}% variance\n"

        if results.clustering_available:
            summary += f"\nCLUSTERING:\n  {results.n_clusters} clusters identified\n"

        summary += f"""
CRITICAL MOMENTS:
  All-Trace Convergence: {len(results.convergence_moments)} moments
  Maximum Divergence: {len(results.divergence_moments)} moments
  Regime Changes: {len(results.regime_changes)}
"""

        return summary

    def _empty_results(self) -> ComprehensiveResults:
        """Return empty results"""
        return ComprehensiveResults(
            analysis_type="none",
            summary_text="No data to analyze"
        )