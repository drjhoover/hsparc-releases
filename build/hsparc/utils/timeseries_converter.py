# hsparc/utils/timeseries_converter.py
"""
Convert event-driven input data to regular time-series format.

Event-driven data records changes only (e.g., stick moved, button pressed).
Time-series data samples at regular intervals (e.g., every 16.67ms for 60 Hz).
"""
from __future__ import annotations

from typing import List, Tuple, Literal
import numpy as np


class TimeSeriesConverter:
    """
    Converts event-driven gamepad data to regular time-series samples.

    Event-driven format: Records only when values change
    Time-series format: Regular samples at fixed intervals

    Example:
        converter = TimeSeriesConverter(sampling_rate_hz=30)  # 30 Hz = 33.33ms intervals
        times, values = converter.convert_axis_events([0, 100, 500], [0, 127, 255])
        # Returns regular samples at 0ms, 33ms, 66ms, 100ms, 133ms, etc.
    """

    def __init__(self, sampling_rate_hz: int = 30):
        """
        Initialize converter.

        Args:
            sampling_rate_hz: Target sampling rate in Hz (samples per second)
                             Common values: 60, 30, 20, 10, 5, 1
        """
        if sampling_rate_hz <= 0:
            raise ValueError(f"Sampling rate must be positive, got {sampling_rate_hz}")

        self.sampling_rate_hz = sampling_rate_hz
        self.interval_ms = 1000.0 / sampling_rate_hz  # Time between samples in milliseconds

    def convert_axis_events(
            self,
            times_ms: List[int],
            values: List[int],
            interpolation: Literal["forward_fill", "linear"] = "forward_fill"
    ) -> Tuple[List[int], List[int]]:
        """
        Convert axis events to regular time-series samples.

        Args:
            times_ms: Event timestamps in milliseconds
            values: Axis values at each timestamp (typically -32768 to 32767 or 0 to 255)
            interpolation: Method to use between samples
                - "forward_fill": Hold last value until next event (default, best for raw data)
                - "linear": Linear interpolation between events (smoother, but creates artificial values)

        Returns:
            Tuple of (regular_times_ms, regular_values)
            - regular_times_ms: Regular sample times at specified rate
            - regular_values: Interpolated values at those times

        Example:
            Input events:  times=[0, 100, 500], values=[0, 127, 255]
            Output (30Hz): times=[0, 33, 66, 100, 133, ..., 500], values=[0, 0, 0, 127, 127, ..., 255]
        """
        if not times_ms or not values:
            return [], []

        if len(times_ms) != len(values):
            raise ValueError(f"times_ms and values must have same length: {len(times_ms)} != {len(values)}")

        # Convert to numpy for efficient processing
        times_array = np.array(times_ms, dtype=np.float64)
        values_array = np.array(values, dtype=np.float64)

        # Generate regular sample times from 0 to max_time
        max_time = times_array[-1]
        num_samples = int(np.ceil(max_time / self.interval_ms)) + 1
        regular_times = np.arange(num_samples) * self.interval_ms

        # Interpolate values at regular intervals
        if interpolation == "forward_fill":
            # Forward-fill: hold last value until next event
            regular_values = np.interp(regular_times, times_array, values_array, left=values_array[0])

            # For forward-fill, we need to explicitly hold values
            # np.interp does linear by default, so we need to step it
            regular_values_stepped = np.zeros_like(regular_values)
            event_idx = 0
            for i, t in enumerate(regular_times):
                # Find the last event that occurred before or at this time
                while event_idx < len(times_array) - 1 and times_array[event_idx + 1] <= t:
                    event_idx += 1
                regular_values_stepped[i] = values_array[event_idx]
            regular_values = regular_values_stepped

        elif interpolation == "linear":
            # Linear interpolation between events
            regular_values = np.interp(regular_times, times_array, values_array)
        else:
            raise ValueError(f"Unknown interpolation method: {interpolation}")

        # Convert back to lists of integers
        regular_times_int = regular_times.astype(np.int32).tolist()
        regular_values_int = np.round(regular_values).astype(np.int32).tolist()

        return regular_times_int, regular_values_int

    def convert_button_events(
            self,
            presses_ms: List[int],
            releases_ms: List[int],
            max_time_ms: int
    ) -> Tuple[List[int], List[int]]:
        """
        Convert button press/release events to regular time-series state samples.

        Args:
            presses_ms: Timestamps of button presses
            releases_ms: Timestamps of button releases
            max_time_ms: Maximum time to sample until

        Returns:
            Tuple of (regular_times_ms, button_states)
            - regular_times_ms: Regular sample times at specified rate
            - button_states: Button state at each time (0=released, 1=pressed)

        Example:
            Input:  presses=[100, 500], releases=[200, 600], max_time=700
            Output (30Hz): times=[0, 33, 66, 100, 133, 166, 200, ...],
                          states=[0, 0, 0, 1, 1, 1, 0, ...]
        """
        if max_time_ms <= 0:
            return [], []

        # Generate regular sample times from 0 to max_time
        num_samples = int(np.ceil(max_time_ms / self.interval_ms)) + 1
        regular_times = np.arange(num_samples) * self.interval_ms

        # Initialize all states as released (0)
        button_states = np.zeros(num_samples, dtype=np.int32)

        # Sort press and release events
        all_presses = sorted(presses_ms) if presses_ms else []
        all_releases = sorted(releases_ms) if releases_ms else []

        # Build a timeline of state changes
        # Each press sets state to 1, each release sets state to 0
        state_changes: List[Tuple[int, int]] = []  # (time_ms, new_state)

        for press_time in all_presses:
            state_changes.append((press_time, 1))
        for release_time in all_releases:
            state_changes.append((release_time, 0))

        # Sort by time
        state_changes.sort(key=lambda x: x[0])

        # Apply state changes to regular samples
        current_state = 0
        change_idx = 0

        for i, t in enumerate(regular_times):
            # Apply all state changes that occur before or at this sample time
            while change_idx < len(state_changes) and state_changes[change_idx][0] <= t:
                current_state = state_changes[change_idx][1]
                change_idx += 1

            button_states[i] = current_state

        # Convert to lists
        regular_times_int = regular_times.astype(np.int32).tolist()
        button_states_list = button_states.tolist()

        return regular_times_int, button_states_list

    def get_time_axis(self, max_time_ms: int) -> List[int]:
        """
        Generate a regular time axis from 0 to max_time_ms.

        Args:
            max_time_ms: Maximum time in milliseconds

        Returns:
            List of sample times at the specified sampling rate
        """
        if max_time_ms <= 0:
            return []

        num_samples = int(np.ceil(max_time_ms / self.interval_ms)) + 1
        times = np.arange(num_samples) * self.interval_ms
        return times.astype(np.int32).tolist()

    def get_sample_count(self, duration_ms: int) -> int:
        """
        Calculate how many samples would be generated for a given duration.

        Args:
            duration_ms: Duration in milliseconds

        Returns:
            Number of samples
        """
        return int(np.ceil(duration_ms / self.interval_ms)) + 1


# Convenience functions
def events_to_timeseries(
        times_ms: List[int],
        values: List[int],
        sampling_rate_hz: int = 30,
        interpolation: Literal["forward_fill", "linear"] = "forward_fill"
) -> Tuple[List[int], List[int]]:
    """
    Convert event-driven axis data to time-series in one call.

    Args:
        times_ms: Event timestamps
        values: Values at each timestamp
        sampling_rate_hz: Target sampling rate
        interpolation: "forward_fill" or "linear"

    Returns:
        (regular_times, regular_values)
    """
    converter = TimeSeriesConverter(sampling_rate_hz)
    return converter.convert_axis_events(times_ms, values, interpolation)


def buttons_to_timeseries(
        presses_ms: List[int],
        releases_ms: List[int],
        max_time_ms: int,
        sampling_rate_hz: int = 30
) -> Tuple[List[int], List[int]]:
    """
    Convert button events to time-series state in one call.

    Args:
        presses_ms: Press timestamps
        releases_ms: Release timestamps
        max_time_ms: Maximum time to sample
        sampling_rate_hz: Target sampling rate

    Returns:
        (regular_times, button_states)
    """
    converter = TimeSeriesConverter(sampling_rate_hz)
    return converter.convert_button_events(presses_ms, releases_ms, max_time_ms)