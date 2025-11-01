
# hsparc/input/gamepad.py
from __future__ import annotations

import os
import threading
import traceback
from typing import Callable, Dict, Tuple, Optional

from uuid import uuid4

try:
    from evdev import InputDevice, ecodes  # type: ignore
except Exception as e:
    raise RuntimeError("python-evdev is required for gamepad capture") from e

from hsparc.models import db as dbm
from hsparc.models.db import InputEvent


def _code_name_key(code: int) -> str:
    # Normalize to a single label. Prefer BTN_* then KEY_*.
    try:
        nm = ecodes.BTN[code]
    except Exception:
        nm = None
    if isinstance(nm, (tuple, list)):
        for s in reversed(nm):
            if isinstance(s, str) and s:
                return s
    if isinstance(nm, str) and nm:
        return nm
    # fallback: KEY table
    try:
        nm = ecodes.KEY[code]
    except Exception:
        nm = None
    if isinstance(nm, (tuple, list)):
        for s in reversed(nm):
            if isinstance(s, str) and s:
                return s
    if isinstance(nm, str) and nm:
        return nm
    return f"KEY_{code}"


def _code_name_abs(code: int) -> str:
    try:
        nm = ecodes.ABS[code]
    except Exception:
        nm = None
    if isinstance(nm, (tuple, list)):
        for s in reversed(nm):
            if isinstance(s, str) and s:
                return s
    if isinstance(nm, str) and nm:
        return nm
    return f"ABS_{code}"


class _Reader(threading.Thread):
    def __init__(
        self,
        device_path: str,
        stream_id: str,
        recording_id: str,
        session_id: str,
        time_source: Callable[[], float],
        *,
        alias: str,
        debug: bool = True,
        calibration_data: Optional[Dict] = None,
        allowed_inputs: Optional[list] = None,
    ) -> None:
        super().__init__(daemon=True)
        self.device_path = device_path
        self.stream_id = stream_id
        self.recording_id = recording_id
        self.session_id = session_id
        self.time_source = time_source
        self.alias = alias
        self.debug = debug
        self._stop = threading.Event()
        self._dev: Optional[InputDevice] = None
        
        # Calibration support
        self.calibration_data = calibration_data or {}
        self.allowed_inputs = allowed_inputs
        self._axis_calibrations = self._parse_calibrations()
    
    def _parse_calibrations(self) -> Dict:
        """Parse calibration data into usable format."""
        from dataclasses import dataclass
        
        @dataclass
        class AxisCal:
            min_value: int
            max_value: int
            
            def normalize(self, raw_value: int) -> float:
                if self.min_value == self.max_value:
                    return 0.0
                normalized = (raw_value - self.min_value) / (self.max_value - self.min_value)
                return (normalized * 2.0) - 1.0
        
        cals = {}
        if not self.calibration_data:
            return cals
        
        axes_data = self.calibration_data.get("axes", {})
        for code, data in axes_data.items():
            cals[code] = AxisCal(
                min_value=data["min"],
                max_value=data["max"]
            )
        
        return cals

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._dev is not None:
                self._dev.close()
        except Exception:
            pass

    def run(self) -> None:
        try:
            self._dev = InputDevice(self.device_path)
            if self.debug:
                print(f"[poller] open {self.device_path} -> name={self._dev.name!r}")
            for ev in self._dev.read_loop():
                if self._stop.is_set():
                    break
                # Skip SYN events
                if ev.type == ecodes.EV_SYN:
                    continue

                t_ms = int(self.time_source())

                if ev.type == ecodes.EV_ABS:
                    code = _code_name_abs(ev.code)
                    
                    # FILTER: Check if input is allowed
                    if self.allowed_inputs and code not in self.allowed_inputs:
                        continue
                    
                    # NORMALIZE: Apply calibration if available
                    if code in self._axis_calibrations:
                        cal = self._axis_calibrations[code]
                        normalized = cal.normalize(int(ev.value))
                        # Store as integer: -1000 to 1000 for precision
                        val = int(normalized * 1000)
                        if self.debug:
                            print(f"[ev_abs] {self.device_path} {code} raw={ev.value} norm={normalized:.3f} stored={val}")
                    else:
                        val = int(ev.value)
                        if self.debug:
                            print(f"[ev_abs] {self.device_path} {code} value={val} t={t_ms}")
                    
                    with dbm.get_session() as s:
                        s.add(
                            InputEvent(
                                id=uuid4().hex,
                                recording_id=self.recording_id,
                                session_id=self.session_id,
                                stream_id=self.stream_id,
                                t_ms=t_ms,
                                kind="axis",
                                code=code,
                                value=val,
                                is_press=None,
                            )
                        )
                        s.commit()

                elif ev.type == ecodes.EV_KEY:
                    code = _code_name_key(ev.code)
                    
                    # FILTER: Check if input is allowed
                    if self.allowed_inputs and code not in self.allowed_inputs:
                        continue
                    
                    v = int(ev.value)  # 0=up, 1=down, 2=repeat
                    is_press = True if v == 1 else False if v == 0 else None
                    if self.debug:
                        print(
                            f"[ev_key] {self.device_path} {code} value={v} "
                            f"is_press={is_press} t={t_ms}"
                        )
                    with dbm.get_session() as s:
                        s.add(
                            InputEvent(
                                id=uuid4().hex,
                                recording_id=self.recording_id,
                                session_id=self.session_id,
                                stream_id=self.stream_id,
                                t_ms=t_ms,
                                kind="button",
                                code=code,     # <-- single string, not tuple
                                value=v,
                                is_press=is_press,
                            )
                        )
                        s.commit()
                else:
                    # ignore other event types
                    continue
        except Exception as e:
            print(f"[poller] reader error for {self.device_path}: {e}")
            traceback.print_exc()
        finally:
            try:
                if self._dev is not None:
                    self._dev.close()
            except Exception:
                pass


class GamepadPoller:
    """
    Required signature:

      GamepadPoller(
          *,
          recording_id: str,
          session_id: str,
          time_source: Callable[[], float],  # returns ms
          assigned: Dict[str, Tuple[str, str]],  # { realpath: (stream_id, alias) }
      )
    """

    def __init__(
        self,
        *,
        recording_id: str,
        session_id: str,
        time_source: Callable[[], float],
        assigned: Dict[str, Tuple[str, str]],
        calibrations: Optional[Dict] = None,
    ) -> None:
        self.recording_id = recording_id
        self.session_id = session_id
        self.time_source = time_source
        self.assigned = assigned or {}
        self.calibrations = calibrations or {}
        self._threads: list[_Reader] = []
        self.start()

    def start(self) -> None:
        if self._threads:
            return
        for path, (stream_id, alias) in self.assigned.items():
            realp = os.path.realpath(path)
            
            # Get calibration for this stream
            cal_state = self.calibrations.get(stream_id)
            cal_data = cal_state.to_dict() if cal_state else None
            allowed = cal_state.get_allowed_inputs() if cal_state else None
            
            t = _Reader(
                device_path=realp,
                stream_id=stream_id,
                recording_id=self.recording_id,
                session_id=self.session_id,
                time_source=self.time_source,
                alias=alias,
                debug=True,
                calibration_data=cal_data,
                allowed_inputs=allowed,
            )
            self._threads.append(t)
            t.start()
        print(f"[poller] started {len(self._threads)} device reader(s)")

    def stop(self) -> None:
        for t in self._threads:
            try:
                t.stop()
            except Exception:
                pass

    def join(self, timeout: Optional[float] = None) -> None:
        for t in self._threads:
            try:
                t.join(timeout=timeout)
            except Exception:
                pass