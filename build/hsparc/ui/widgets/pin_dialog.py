from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout


class PinDialog(QDialog):
    """Dialog for entering case PIN."""

    def __init__(self, parent=None, title="Enter Case PIN", message="Enter the PIN to access this case:"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        # Message
        msg = QLabel(message)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        # PIN entry (numeric only, password mode)
        self.pin_entry = QLineEdit()
        self.pin_entry.setEchoMode(QLineEdit.Password)
        self.pin_entry.setPlaceholderText("Enter 4-8 digit PIN")
        self.pin_entry.setMaxLength(8)
        # Only allow digits
        from PySide6.QtGui import QIntValidator
        self.pin_entry.setValidator(QIntValidator(0, 99999999))
        layout.addWidget(self.pin_entry)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        btn_row.addStretch()
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        layout.addLayout(btn_row)

        # Wire
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.pin_entry.returnPressed.connect(self.accept)

        # Focus
        self.pin_entry.setFocus()

    def get_pin(self) -> str:
        """Get the entered PIN."""
        return self.pin_entry.text().strip()

    @staticmethod
    def get_pin_from_user(parent=None, title="Enter Case PIN", message="Enter the PIN to access this case:") -> \
    Optional[str]:
        """Show dialog and return PIN if OK clicked, None if cancelled."""
        dialog = PinDialog(parent, title, message)
        if dialog.exec() == QDialog.Accepted:
            return dialog.get_pin()
        return None