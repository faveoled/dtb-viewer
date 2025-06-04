import sys
import os
import subprocess
import uuid
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget,
    QTextEdit, QPushButton, QFileDialog, QMessageBox, QInputDialog
)
from PyQt6.QtGui import QAction, QKeySequence, QTextDocument, QTextCursor
from PyQt6.QtCore import Qt


class DTBViewerApp(QMainWindow):
    def __init__(self, initial_dtb_file=None):
        super().__init__()
        self.setWindowTitle("DTB Viewer & DTS Converter")
        self.setGeometry(100, 100, 800, 600)

        self.current_dts_content = ""
        self.current_dtb_basename = "Untitled"
        self.current_out_dts_tmp_file = None

        self.last_search_term = ""
        # Default flags: Case-insensitive. Change if needed.
        # QTextDocument.FindFlag(0) is equivalent to no flags, which means case-insensitive by default
        # for QTextEdit.find(). If you want explicit case insensitivity, use:
        # self.last_find_flags = QTextDocument.FindFlag.FindCaseSensitively if you want case-sensitive
        self.last_find_flags = QTextDocument.FindFlag(0) # Default behavior is case-insensitive

        self._init_ui()

        if initial_dtb_file:
            self.process_dtb_file(initial_dtb_file)

    def _init_ui(self):
        # --- Menu Bar ---
        menu_bar = self.menuBar()

        # File Menu
        file_menu = menu_bar.addMenu("&File")
        open_action = QAction("&Open DTB...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_dtb_dialog)
        file_menu.addAction(open_action)

        self.save_dts_action = QAction("&Save DTS As...", self)
        self.save_dts_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_dts_action.triggered.connect(self.save_dts_as)
        self.save_dts_action.setEnabled(False)
        file_menu.addAction(self.save_dts_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit Menu
        edit_menu = menu_bar.addMenu("&Edit")
        self.find_action = QAction("&Find...", self)
        self.find_action.setShortcut(QKeySequence.StandardKey.Find) # Ctrl+F
        self.find_action.triggered.connect(self.handle_find_request)
        self.find_action.setEnabled(False) # Disabled initially
        edit_menu.addAction(self.find_action)
        
        # --- Tab Widget ---
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        # --- Tab 1: DTS Content ---
        self.dts_tab = QWidget()
        dts_layout = QVBoxLayout(self.dts_tab)

        self.dts_text_edit = QTextEdit()
        self.dts_text_edit.setReadOnly(True)
        self.dts_text_edit.setFontFamily("Monospace") # Good for code/DTS
        dts_layout.addWidget(self.dts_text_edit)

        self.save_dts_button = QPushButton("Save DTS As...")
        self.save_dts_button.clicked.connect(self.save_dts_as)
        self.save_dts_button.setEnabled(False)
        dts_layout.addWidget(self.save_dts_button)

        self.tab_widget.addTab(self.dts_tab, "DTS Output") # Placeholder name

        # --- Tab 2: Issues ---
        self.issues_tab = QWidget()
        issues_layout = QVBoxLayout(self.issues_tab)

        self.issues_text_edit = QTextEdit()
        self.issues_text_edit.setReadOnly(True)
        self.issues_text_edit.setFontFamily("Monospace") # Good for logs
        issues_layout.addWidget(self.issues_text_edit)

        self.tab_widget.addTab(self.issues_tab, "Issues (0)") # Placeholder name

    def handle_find_request(self):
        if self.tab_widget.currentWidget() != self.dts_tab or not self.dts_text_edit.toPlainText():
            QMessageBox.information(self, "Find", "No DTS content to search in, or DTS tab not active.")
            return

        self.dts_text_edit.setFocus() # Ensure the text edit has focus

        search_term, ok = QInputDialog.getText(
            self,
            "Find Text",
            "Enter text to find:",
            text=self.last_search_term # Pre-fill with last search term
        )

        if ok and search_term:
            self.last_search_term = search_term
            # You can add a dialog here to ask for find flags (e.g., case sensitive)
            # For now, using self.last_find_flags (default: case-insensitive)
            
            # Try to find from current cursor position
            # QTextEdit.find() searches forward from the current cursor position.
            # If found, it selects the text and returns True.
            found = self.dts_text_edit.find(self.last_search_term, self.last_find_flags)

            if not found:
                # If not found from the current position, ask the user if they want to search from the beginning
                reply = QMessageBox.question(self, 'Find Text',
                                             f"Text '{self.last_search_term}' not found from current position.\nSearch from the beginning?",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                             QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    # Move cursor to the beginning of the document
                    cursor = self.dts_text_edit.textCursor()
                    cursor.movePosition(QTextCursor.MoveOperation.Start)
                    self.dts_text_edit.setTextCursor(cursor)
                    found = self.dts_text_edit.find(self.last_search_term, self.last_find_flags)
            
            if not found: # If still not found after potentially searching from start
                 QMessageBox.information(self, "Find Text", f"Text '{self.last_search_term}' not found.")
        elif ok and not search_term: # User pressed OK but entered no text
            # Clear any existing selection if desired, or do nothing
            cursor = self.dts_text_edit.textCursor()
            if cursor.hasSelection():
                cursor.clearSelection()
                self.dts_text_edit.setTextCursor(cursor)

    def open_dtb_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open DTB File",
            "", # Start directory
            "Device Tree Blob (*.dtb);;All Files (*)"
        )
        if file_path:
            self.process_dtb_file(file_path)

    def process_dtb_file(self, in_dtb_file_path_str):
        in_dtb_file_path = Path(in_dtb_file_path_str)

        if not in_dtb_file_path.is_file():
            QMessageBox.critical(self, "Error", f"DTB file not found: {in_dtb_file_path}")
            self.clear_views()
            return

        self.current_dtb_basename = in_dtb_file_path.name
        random_uuid_str = str(uuid.uuid4())
        out_dts_filename = f"{in_dtb_file_path.stem}-{random_uuid_str}.dts"
        
        tmp_dir = Path("/tmp")
        if not tmp_dir.exists() or not os.access(tmp_dir, os.W_OK):
            try:
                import tempfile
                tmp_dir_fallback = Path(tempfile.gettempdir())
                if not tmp_dir_fallback.exists() or not os.access(tmp_dir_fallback, os.W_OK):
                    raise OSError("System temp directory also not accessible.")
                tmp_dir = tmp_dir_fallback
                print(f"Warning: /tmp not available or writable. Using system temp directory: {tmp_dir}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Cannot access /tmp or system temp directory: {e}")
                self.clear_views()
                return

        self.current_out_dts_tmp_file = tmp_dir / out_dts_filename

        dtc_command = [
            "dtc",
            "-I", "dtb",
            "-O", "dts",
            str(in_dtb_file_path),
            "-o", str(self.current_out_dts_tmp_file)
        ]

        dts_content = ""
        stderr_lines = []
        issues_count = 0
        dtc_success = False # Flag to track if dtc actually produced a usable .dts file

        try:
            print(f"Running command: {' '.join(dtc_command)}")
            process = subprocess.run(
                dtc_command,
                capture_output=True,
                text=True, # Decodes stdout/stderr as text
                check=False # We check returncode manually
            )

            if process.stderr:
                stderr_lines = process.stderr.strip().splitlines()
                issues_count = len(stderr_lines)

            if process.returncode == 0:
                if self.current_out_dts_tmp_file.is_file():
                    with open(self.current_out_dts_tmp_file, "r", encoding="utf-8", errors="replace") as f:
                        dts_content = f.read()
                    dtc_success = True # dtc ran and output file exists
                    if not stderr_lines: # If dtc was successful and no errors, add a success message
                         stderr_lines.append("dtc command executed successfully.")
                         issues_count = len(stderr_lines) # Update count if it was 0
                else:
                    # dtc reported success, but file is missing - this is an error condition
                    dts_content = f"Error: dtc ran successfully but output file {self.current_out_dts_tmp_file} was not created."
                    stderr_lines.append(dts_content) # Add to issues
                    issues_count = len(stderr_lines)
                    dtc_success = False # Treat as failure for enabling features
            else:
                # dtc failed
                error_message = f"dtc command failed with exit code {process.returncode}."
                dts_content = error_message # Display error in DTS tab as well
                if not stderr_lines: # if dtc failed but produced no stderr
                    stderr_lines.append(error_message)
                else: # if dtc failed and produced stderr, prepend the error message
                    stderr_lines.insert(0, error_message)
                issues_count = len(stderr_lines)
                QMessageBox.warning(self, "DTC Execution Failed",
                                    f"{error_message}\nCheck the 'Issues' tab for details.")
                dtc_success = False


        except FileNotFoundError:
            dts_content = "Error: 'dtc' command not found. Please ensure it is installed and in your PATH."
            stderr_lines = [dts_content]
            issues_count = 1
            dtc_success = False
            QMessageBox.critical(self, "Error", dts_content)
        except Exception as e:
            dts_content = f"An unexpected error occurred during dtc execution: {e}"
            stderr_lines = [str(e)]
            issues_count = 1
            dtc_success = False
            QMessageBox.critical(self, "Error", dts_content)

        self.current_dts_content = dts_content
        self.dts_text_edit.setPlainText(self.current_dts_content)
        self.issues_text_edit.setPlainText("\n".join(stderr_lines))

        self.tab_widget.setTabText(0, self.current_dtb_basename)
        self.tab_widget.setTabText(1, f"Issues ({issues_count})")

        # Enable save/find options only if DTS content was successfully generated AND is not an error message itself.
        # dtc_success ensures the command returned 0 and the output file was created.
        can_use_dts_features = dtc_success and bool(dts_content)
        
        self.save_dts_action.setEnabled(can_use_dts_features)
        self.save_dts_button.setEnabled(can_use_dts_features)
        self.find_action.setEnabled(can_use_dts_features)


    def save_dts_as(self):
        if not self.current_dts_content or not self.save_dts_button.isEnabled():
            QMessageBox.information(self, "Nothing to Save", "No DTS content available to save or save is disabled.")
            return

        # Suggest a filename based on the input DTB name
        suggested_filename = Path(self.current_dtb_basename).with_suffix(".dts").name

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save DTS File As...",
            suggested_filename,
            "Device Tree Source (*.dts);;All Files (*)"
        )

        if file_path:
            try:
                # Save the content from the text editor.
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.dts_text_edit.toPlainText())
                QMessageBox.information(self, "Success", f"DTS file saved to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error Saving File", f"Could not save file: {e}")
    
    def clear_views(self):
        self.current_dts_content = ""
        self.current_dtb_basename = "Untitled"
        
        self.dts_text_edit.clear()
        self.issues_text_edit.clear()
        self.tab_widget.setTabText(0, "DTS Output")
        self.tab_widget.setTabText(1, "Issues (0)")
        self.save_dts_action.setEnabled(False)
        self.save_dts_button.setEnabled(False)
        self.find_action.setEnabled(False)
        self.last_search_term = "" # Reset last search term on clear


    def closeEvent(self, event):
        # Clean up temporary file if it exists
        if self.current_out_dts_tmp_file and self.current_out_dts_tmp_file.exists():
            try:
                self.current_out_dts_tmp_file.unlink()
                print(f"Cleaned up temporary file on exit: {self.current_out_dts_tmp_file}")
            except OSError as e:
                print(f"Warning: Could not delete temporary file {self.current_out_dts_tmp_file} on exit: {e}")
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)

    initial_file = None
    if len(sys.argv) > 1:
        initial_file_path = Path(sys.argv[1])
        if initial_file_path.exists() and initial_file_path.suffix.lower() == ".dtb":
            initial_file = str(initial_file_path)
        else:
            print(f"Warning: Argument '{sys.argv[1]}' is not a valid .dtb file or does not exist. Ignoring.")

    viewer = DTBViewerApp(initial_dtb_file=initial_file)
    viewer.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
