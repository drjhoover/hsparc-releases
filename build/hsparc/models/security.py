import hashlib
from datetime import datetime
from typing import Optional

def hash_pin(pin: str) -> str:
    """Hash a PIN using SHA256."""
    return hashlib.sha256(pin.encode('utf-8')).hexdigest()

def verify_pin(stored_hash: str, entered_pin: str) -> bool:
    """Verify an entered PIN against stored hash."""
    return hash_pin(entered_pin) == stored_hash

class AccessLog:
    """Log security-relevant actions."""
    @staticmethod
    def log(case_id: str, action: str, success: bool = True):
        """Log an access attempt."""
        timestamp = datetime.utcnow().isoformat()
        # For now, just print. Later could write to file/DB
        status = "SUCCESS" if success else "FAILED"
        print(f"[ACCESS LOG] {timestamp} | Case: {case_id[:8]} | {action} | {status}")