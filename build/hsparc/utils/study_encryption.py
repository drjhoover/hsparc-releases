"""Per-study file encryption using study PIN."""

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64
import os


def derive_key_from_pin(study_id: str, pin: str) -> bytes:
    """Derive encryption key from study ID and PIN."""
    # Use study ID as salt (deterministic per study)
    salt = study_id.encode()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    key = base64.urlsafe_b64encode(kdf.derive(pin.encode()))
    return key


def encrypt_file(filepath: str, study_id: str, pin: str) -> str:
    """Encrypt a file and replace it with encrypted version."""
    key = derive_key_from_pin(study_id, pin)
    fernet = Fernet(key)

    # Read original file
    with open(filepath, 'rb') as f:
        data = f.read()

    # Encrypt
    encrypted = fernet.encrypt(data)

    # Write encrypted file with .enc extension
    encrypted_path = filepath + '.enc'
    with open(encrypted_path, 'wb') as f:
        f.write(encrypted)

    # Remove original
    os.remove(filepath)

    return encrypted_path


def decrypt_file(encrypted_path: str, study_id: str, pin: str) -> str:
    """Decrypt a file temporarily for use."""
    key = derive_key_from_pin(study_id, pin)
    fernet = Fernet(key)

    # Read encrypted file
    with open(encrypted_path, 'rb') as f:
        encrypted = f.read()

    # Decrypt
    try:
        decrypted = fernet.decrypt(encrypted)
    except Exception:
        raise ValueError("Invalid PIN or corrupted file")

    # Write to temp location
    original_path = encrypted_path.replace('.enc', '')
    temp_path = f"/tmp/{os.path.basename(original_path)}"

    with open(temp_path, 'wb') as f:
        f.write(decrypted)

    return temp_path


def encrypt_study_folder(study_path: str, study_id: str, pin: str):
    """Encrypt all files in a study folder."""
    for root, dirs, files in os.walk(study_path):
        for filename in files:
            if not filename.endswith('.enc'):
                filepath = os.path.join(root, filename)
                encrypt_file(filepath, study_id, pin)