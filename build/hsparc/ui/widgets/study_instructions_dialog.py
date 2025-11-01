# hsparc/ui/widgets/study_instructions_dialog.py
"""
Study-level observer instructions editor.
Instructions are stored with the study and used for all observer sessions.
Supports markdown formatting with live preview.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox, QDialogButtonBox, QFileDialog, QMessageBox,
    QTabWidget, QTextBrowser, QWidget, QApplication
)
from PySide6.QtGui import QPixmap

from hsparc.models import db as dbm

# Import markdown converter
try:
    import markdown
    HAS_MARKDOWN = True
    print("[study_instructions] Markdown library loaded successfully")
except ImportError:
    HAS_MARKDOWN = False
    print("[study_instructions] Warning: markdown library not available")


class StudyInstructionsDialog(QDialog):
    """Dialog for editing study-wide observer instructions."""

    def __init__(self, parent=None, study_id: str = None):
        super().__init__(parent)
        self.study_id = study_id
        self.image_path: Optional[Path] = None

        self.setWindowTitle("Edit Observer Instructions")
        self.setModal(True)

        # FIXED: Set size based on screen resolution
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            max_height = int(screen_geometry.height() * 0.85)  # Use 85% of screen height
            max_width = min(900, int(screen_geometry.width() * 0.9))
            self.resize(max_width, min(600, max_height))
            self.setMaximumHeight(max_height)
            print(f"[study_instructions] Screen size: {screen_geometry.width()}x{screen_geometry.height()}, using max height: {max_height}")
        else:
            self.resize(900, 600)

        # Load current instructions from database
        self._load_current_instructions()

        self._setup_ui()
        self._populate_ui()

    def _load_current_instructions(self):
        """Load existing instructions from database."""
        self.current_text = ""
        self.current_image_path = None

        if not self.study_id:
            return

        try:
            with dbm.get_session() as s:
                study = s.query(dbm.Study).filter_by(id=self.study_id).first()
                if study:
                    self.current_text = study.observer_instructions_text or ""
                    if study.observer_instructions_image:
                        self.current_image_path = Path(study.observer_instructions_image)
                        if self.current_image_path.exists():
                            self.image_path = self.current_image_path
                    print(f"[study_instructions] Loaded: text={len(self.current_text)} chars, image={self.current_image_path is not None}")
        except Exception as e:
            print(f"[study_instructions] Error loading instructions: {e}")
            import traceback
            traceback.print_exc()

    def _setup_ui(self):
        """Build the UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # ADDED: Header with title and close button
        header_layout = QHBoxLayout()

        title = QLabel("Observer Instructions")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Close button (X in top right)
        btn_close = QPushButton("✖")
        btn_close.setFixedSize(30, 30)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        btn_close.setToolTip("Close without saving")
        btn_close.clicked.connect(self.reject)
        header_layout.addWidget(btn_close)

        layout.addLayout(header_layout)

        info = QLabel(
            "These instructions will be shown to participants before each observer session.\n"
            "Instructions are optional but recommended."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666; padding: 4px; font-size: 11px;")
        layout.addWidget(info)

        # Tab widget for editor and preview
        self.tabs = QTabWidget()

        # Tab 1: Editor
        editor_tab = self._create_editor_tab()
        self.tabs.addTab(editor_tab, "📝 Editor")

        # Tab 2: Preview
        preview_tab = self._create_preview_tab()
        self.tabs.addTab(preview_tab, "👁️ Preview")

        layout.addWidget(self.tabs, 1)

        # Image section (more compact)
        image_group = QGroupBox("Optional Instructional Image")
        image_layout = QVBoxLayout(image_group)
        image_layout.setSpacing(5)
        image_layout.setContentsMargins(8, 8, 8, 8)

        # Image preview (smaller)
        self.image_preview = QLabel("No image selected")
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setStyleSheet(
            "border: 2px dashed #ccc; "
            "background: #f9f9f9; "
            "padding: 8px; "
            "min-height: 80px; "
            "max-height: 120px;"
        )
        self.image_preview.setScaledContents(False)
        image_layout.addWidget(self.image_preview)

        # Image buttons
        btn_row = QHBoxLayout()
        self.btn_upload = QPushButton("📁 Upload...")
        self.btn_upload.clicked.connect(self._upload_image)
        btn_row.addWidget(self.btn_upload)

        self.btn_clear_image = QPushButton("✖ Clear")
        self.btn_clear_image.clicked.connect(self._clear_image)
        self.btn_clear_image.setEnabled(False)
        btn_row.addWidget(self.btn_clear_image)

        btn_row.addStretch()
        image_layout.addLayout(btn_row)

        layout.addWidget(image_group)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Connect tab change to update preview
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _create_editor_tab(self) -> QWidget:
        """Create the markdown editor tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)

        # FIXED: Simplified help text, removed markdown warning
        if HAS_MARKDOWN:
            help_text = QLabel(
                "<b>Markdown:</b> <code># Heading</code>, <code>**bold**</code>, "
                "<code>*italic*</code>, <code>- List</code>"
            )
        else:
            help_text = QLabel("<b>Plain Text Mode</b>")
        help_text.setWordWrap(True)
        help_text.setStyleSheet("background: #f0f8ff; padding: 5px; border-radius: 3px; font-size: 10px;")
        layout.addWidget(help_text)

        # Text editor
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "Enter instructions here.\n\n"
            "Example:\n\n"
            "# Welcome!\n\n"
            "You will watch a video and use your controller to respond.\n\n"
            "## Controls\n"
            "- Left stick: Navigate\n"
            "- A button: Confirm"
        )
        self.text_edit.setStyleSheet("font-family: 'Courier New', monospace;")
        layout.addWidget(self.text_edit, 1)

        return widget

    def _create_preview_tab(self) -> QWidget:
        """Create the preview tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)

        preview_label = QLabel("Preview:")
        preview_label.setStyleSheet("font-weight: bold; color: #666; font-size: 11px;")
        layout.addWidget(preview_label)

        self.preview_browser = QTextBrowser()
        self.preview_browser.setStyleSheet("""
            QTextBrowser {
                background: white;
                border: 2px solid #ddd;
                border-radius: 6px;
                padding: 15px;
                font-size: 14px;
            }
        """)
        layout.addWidget(self.preview_browser, 1)

        return widget

    def _on_tab_changed(self, index: int):
        """Update preview when switching to preview tab."""
        if index == 1:  # Preview tab
            self._update_preview()

    def _update_preview(self):
        """Update the preview with current markdown content."""
        text = self.text_edit.toPlainText().strip()

        if not text:
            self.preview_browser.setHtml("<p><i>No content to preview</i></p>")
            return

        if HAS_MARKDOWN:
            try:
                html = markdown.markdown(
                    text,
                    extensions=['nl2br', 'sane_lists', 'fenced_code', 'tables']
                )
                self.preview_browser.setHtml(html)
            except Exception as e:
                self.preview_browser.setHtml(
                    f"<p style='color: red;'>Error: {e}</p><pre>{text}</pre>"
                )
        else:
            # Fallback: plain text with line breaks
            html = f"<p>{text.replace(chr(10), '<br>')}</p>"
            self.preview_browser.setHtml(html)

    def _populate_ui(self):
        """Populate UI with current data."""
        # Set text
        self.text_edit.setPlainText(self.current_text)
        print(f"[study_instructions] Populated text: {len(self.current_text)} chars")

        # Set image if exists
        if self.image_path and self.image_path.exists():
            self._update_image_preview(self.image_path)
            print(f"[study_instructions] Loaded image: {self.image_path}")

    def _upload_image(self):
        """Upload an instructional image."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Instructional Image",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.gif *.bmp);;All Files (*)"
        )

        if not file_path:
            return

        source_path = Path(file_path)
        if not source_path.exists():
            QMessageBox.warning(self, "File Not Found", "Selected file does not exist.")
            return

        self.image_path = source_path
        self._update_image_preview(source_path)

    def _update_image_preview(self, image_path: Path):
        """Update the image preview."""
        try:
            pixmap = QPixmap(str(image_path))
            if pixmap.isNull():
                self.image_preview.setText("⚠️ Could not load image")
                return

            # Scale to fit preview area
            scaled = pixmap.scaled(
                500, 100,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_preview.setPixmap(scaled)
            self.btn_clear_image.setEnabled(True)

        except Exception as e:
            self.image_preview.setText(f"⚠️ Error: {e}")

    def _clear_image(self):
        """Clear the selected image."""
        self.image_path = None
        self.image_preview.clear()
        self.image_preview.setText("No image selected")
        self.btn_clear_image.setEnabled(False)

    def _save(self):
        """Save instructions to database."""
        if not self.study_id:
            QMessageBox.warning(self, "Error", "No study ID provided.")
            return

        instructions_text = self.text_edit.toPlainText().strip()
        print(f"[study_instructions] Saving {len(instructions_text)} chars")

        # Handle image storage
        stored_image_path = None
        if self.image_path and self.image_path.exists():
            try:
                media_folder = dbm.media_dir(self.study_id)
                instructions_folder = media_folder.parent / "instructions"
                instructions_folder.mkdir(parents=True, exist_ok=True)

                dest_path = instructions_folder / f"observer_instructions{self.image_path.suffix}"

                # FIXED: Only copy if different files
                if self.image_path.resolve() != dest_path.resolve():
                    shutil.copy2(self.image_path, dest_path)
                    print(f"[study_instructions] Copied image to: {dest_path}")
                else:
                    print(f"[study_instructions] Image already at: {dest_path}")

                stored_image_path = str(dest_path)

            except Exception as e:
                print(f"[study_instructions] Image error: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.critical(
                    self, "Image Save Error",
                    f"Could not save image:\n{e}\n\nInstructions will be saved without image."
                )
                stored_image_path = None

        # FIXED: Save to database with proper commit
        try:
            with dbm.get_session() as s:
                study = s.query(dbm.Study).filter_by(id=self.study_id).first()
                if not study:
                    QMessageBox.warning(self, "Error", "Study not found.")
                    return

                # Set values
                study.observer_instructions_text = instructions_text if instructions_text else None
                study.observer_instructions_image = stored_image_path

                # Commit
                s.commit()

                print(f"[study_instructions] ✅ SAVED TO DB:")
                print(f"  Text: {len(instructions_text) if instructions_text else 0} chars")
                print(f"  Image: {stored_image_path}")

            # Success message
            QMessageBox.information(
                self, "Saved",
                "Observer instructions have been saved.\n\n"
                "These will be shown before all observer sessions in this study."
            )
            self.accept()

        except Exception as e:
            print(f"[study_instructions] ❌ DB ERROR: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self, "Save Error",
                f"Could not save instructions:\n{e}"
            )

    @staticmethod
    def edit_instructions(parent=None, study_id: str = None) -> bool:
        """Show dialog to edit study instructions."""
        dialog = StudyInstructionsDialog(parent, study_id)
        return dialog.exec() == QDialog.Accepted