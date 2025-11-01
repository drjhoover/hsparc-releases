# hsparc/models/db.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from sqlalchemy import (
    create_engine, Column, String, DateTime, ForeignKey, Integer, Boolean, Text
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.engine import Engine

APP_HOME = Path.home() / ".local" / "share" / "hsparc"
APP_HOME.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_HOME / "hsparc.sqlite3"

engine: Engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
Session = sessionmaker(bind=engine, future=True)
Base = declarative_base()


def media_dir(study_id: str) -> Path:
    """Get media directory for a study."""
    d = APP_HOME / "studies" / study_id / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Study(Base):
    """
    Study: Top-level research project (formerly called 'Case').
    Each study must have a PIN for security.
    """
    __tablename__ = "cases"  # Keep table name for backward compatibility
    id = Column(String, primary_key=True)
    label = Column(String, unique=True, index=True, nullable=False)
    created_utc = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Security fields
    security_hash = Column(String, nullable=False)
    is_locked = Column(Boolean, default=True, nullable=False)

    # Observer instructions (optional, study-wide)
    observer_instructions_text = Column(Text, nullable=True)
    observer_instructions_image = Column(Text, nullable=True)  # Path to image file

    recordings = relationship("Recording", back_populates="study", cascade="all,delete")


class Recording(Base):
    __tablename__ = "recordings"
    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    created_utc = Column(DateTime, default=datetime.utcnow, nullable=False)
    video_path = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    study = relationship("Study", back_populates="recordings")
    observer_sessions = relationship("ObserverSession", back_populates="recording", cascade="all,delete")

    @property
    def study_id(self) -> str:
        return self.case_id


class ObserverSession(Base):
    __tablename__ = "observer_sessions"
    id = Column(String, primary_key=True)
    recording_id = Column(String, ForeignKey("recordings.id"), nullable=False, index=True)
    created_utc = Column(DateTime, default=datetime.utcnow, nullable=False)
    label = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    # Recognition check fields
    recognition_check_required = Column(Boolean, default=False, nullable=False)
    recognition_check_passed = Column(Boolean, nullable=True)
    recognition_check_timestamp = Column(String, nullable=True)

    recording = relationship("Recording", back_populates="observer_sessions")
    streams = relationship("InputStream", back_populates="session", cascade="all,delete")


def _json_dump(d: Optional[Dict[str, Any]]) -> Optional[str]:
    return None if d is None else json.dumps(d)


def _json_load(s: Optional[str]) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


class InputStream(Base):
    __tablename__ = "input_streams"
    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("observer_sessions.id"), nullable=False, index=True)
    device_name = Column(String, nullable=True)
    profile_id = Column(String, nullable=True)
    created_utc = Column(DateTime, default=datetime.utcnow, nullable=False)

    alias = Column(String, nullable=True)
    _construct_mapping = Column("construct_mapping", Text, nullable=True)
    
    # Calibration data (JSON format)
    _calibration_data = Column("calibration_data", Text, nullable=True)
    # Format: {"ABS_X": {"min": 0, "max": 255, "center": 128, "label": "Arousal"}, ...}
    
    _allowed_inputs = Column("allowed_inputs", Text, nullable=True)
    # Format: ["ABS_X", "ABS_Y", "BTN_TRIGGER", "BTN_THUMB"]

    session = relationship("ObserverSession", back_populates="streams")
    events = relationship("InputEvent", back_populates="stream", cascade="all,delete")

    @property
    def construct_mapping(self) -> Optional[Dict[str, str]]:
        return _json_load(self._construct_mapping)

    @construct_mapping.setter
    def construct_mapping(self, mapping: Optional[Dict[str, str]]):
        self._construct_mapping = _json_dump(mapping)
    
    @property
    def calibration_data(self) -> Optional[Dict[str, Any]]:
        return _json_load(self._calibration_data)
    
    @calibration_data.setter
    def calibration_data(self, data: Optional[Dict[str, Any]]):
        self._calibration_data = _json_dump(data)
    
    @property
    def allowed_inputs(self) -> Optional[list]:
        return _json_load(self._allowed_inputs)
    
    @allowed_inputs.setter
    def allowed_inputs(self, inputs: Optional[list]):
        self._allowed_inputs = _json_dump(inputs)



class InputEvent(Base):
    __tablename__ = "input_events"
    id = Column(String, primary_key=True)
    recording_id = Column(String, ForeignKey("recordings.id"), nullable=False, index=True)
    session_id = Column(String, ForeignKey("observer_sessions.id"), nullable=False, index=True)
    stream_id = Column(String, ForeignKey("input_streams.id"), nullable=False, index=True)

    t_ms = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)
    code = Column(String, nullable=False)
    value = Column(Integer, nullable=True)
    is_press = Column(Boolean, nullable=True)

    stream = relationship("InputStream", back_populates="events")


# Backward compatibility aliases
Case = Study


def _ensure_column_alias():
    """Migration: Add InputStream.alias column if it doesn't exist."""
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(input_streams)")).all()
        cols = {r[1] for r in rows}
        if "alias" not in cols:
            conn.execute(text("ALTER TABLE input_streams ADD COLUMN alias TEXT"))
            conn.commit()
        if "construct_mapping" not in cols:
            conn.execute(text("ALTER TABLE input_streams ADD COLUMN construct_mapping TEXT"))
            conn.commit()


def _ensure_security_columns():
    """Migration: Add Study security columns if they don't exist."""
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(cases)")).all()
        cols = {r[1] for r in rows}
        if "security_hash" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN security_hash TEXT"))
            conn.commit()
        if "is_locked" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN is_locked BOOLEAN DEFAULT 1"))
            conn.commit()

        result = conn.execute(text("SELECT COUNT(*) FROM cases WHERE security_hash IS NULL")).fetchone()
        if result and result[0] > 0:
            print(f"[DB] Found {result[0]} studies without PINs")


def _ensure_recognition_check_columns():
    """Migration: Add ObserverSession recognition check columns if they don't exist."""
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(observer_sessions)")).all()
        cols = {r[1] for r in rows}

        if "recognition_check_required" not in cols:
            conn.execute(text("ALTER TABLE observer_sessions ADD COLUMN recognition_check_required BOOLEAN DEFAULT 0"))
            conn.commit()

        if "recognition_check_passed" not in cols:
            conn.execute(text("ALTER TABLE observer_sessions ADD COLUMN recognition_check_passed BOOLEAN"))
            conn.commit()

        if "recognition_check_timestamp" not in cols:
            conn.execute(text("ALTER TABLE observer_sessions ADD COLUMN recognition_check_timestamp TEXT"))
            conn.commit()


def _ensure_observer_instructions_columns():
    """Migration: Add Study observer instructions columns if they don't exist."""
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(cases)")).all()
        cols = {r[1] for r in rows}

        if "observer_instructions_text" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN observer_instructions_text TEXT"))
            conn.commit()
            print("[DB] Added observer_instructions_text column")

        if "observer_instructions_image" not in cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN observer_instructions_image TEXT"))
            conn.commit()
            print("[DB] Added observer_instructions_image column")


def _ensure_calibration_columns():
    """Migration: Add InputStream calibration columns if they don't exist."""
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(input_streams)")).all()
        cols = {r[1] for r in rows}
        
        if "calibration_data" not in cols:
            conn.execute(text("ALTER TABLE input_streams ADD COLUMN calibration_data TEXT"))
            conn.commit()
            print("[DB] Added calibration_data column")
        
        if "allowed_inputs" not in cols:
            conn.execute(text("ALTER TABLE input_streams ADD COLUMN allowed_inputs TEXT"))
            conn.commit()
            print("[DB] Added allowed_inputs column")


def init_db():
    Base.metadata.create_all(engine)
    _ensure_column_alias()
    _ensure_security_columns()
    _ensure_recognition_check_columns()
    _ensure_observer_instructions_columns()
    _ensure_calibration_columns()


def get_session():
    return Session()