import sys
import os
import re
import subprocess
import uuid
from pathlib import Path
import json
from xdg_utils import get_xdg_data_dir

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

        self.recent_files = []
        self.MAX_RECENT_FILES = 10
        self.load_recent_files()

        self.last_search_term = ""
        # Default flags: Case-insensitive. Change if needed.
        # QTextDocument.FindFlag(0) is equivalent to no flags, which means case-insensitive by default
        # for QTextEdit.find(). If you want explicit case insensitivity, use:
        # self.last_find_flags = QTextDocument.FindFlag.FindCaseSensitively if you want case-sensitive
        self.last_find_flags = QTextDocument.FindFlag(0) # Default behavior is case-insensitive

        self._init_ui() # recent_files_menu is created here
        self.update_recent_files_menu() # Populate menu on startup

        if initial_dtb_file:
            self.process_dtb_file(initial_dtb_file)

    def load_recent_files(self):
        data_dir = get_xdg_data_dir()
        recent_files_path = data_dir / "recent_files.json"
        if recent_files_path.exists():
            try:
                with open(recent_files_path, "r", encoding="utf-8") as f:
                    self.recent_files = json.load(f)
            except (FileNotFoundError, IOError, json.JSONDecodeError) as e:
                print(f"Warning: Could not load recent files: {e}", file=sys.stderr)
                self.recent_files = []
        else:
            self.recent_files = []

    def save_recent_files(self):
        data_dir = get_xdg_data_dir()
        recent_files_path = data_dir / "recent_files.json"
        try:
            with open(recent_files_path, "w", encoding="utf-8") as f:
                json.dump(self.recent_files, f)
        except (IOError, json.JSONEncodeError) as e: # Changed from general Exception to more specific
            print(f"Warning: Could not save recent files: {e}", file=sys.stderr)

    def add_to_recent_files(self, file_path_str: str):
        abs_file_path = str(Path(file_path_str).resolve())
        if abs_file_path in self.recent_files:
            self.recent_files.remove(abs_file_path)
        self.recent_files.insert(0, abs_file_path)
        self.recent_files = self.recent_files[:self.MAX_RECENT_FILES]
        self.save_recent_files()
        self.update_recent_files_menu() # This will be implemented later

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

        self.recent_files_menu = file_menu.addMenu("Open Recent")
        # self.update_recent_files_menu() # Called after UI setup and after loading recent files

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

    def _reformat_dtc_output_line(self, line: str) -> str:
        """
        Reformats dtc output lines to replace temporary filenames with original basenames.
        Example: /tmp/BASENAME-UUID.dts -> BASENAME.dts
        """
        # Regex to find /tmp/BASENAME-UUID.dts
        # UUID is 32 hex digits, typically 8-4-4-4-12
        pattern = r"/tmp/([^-]+)-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.dts"
        replacement = r"\1.dts"

        reformatted_line, num_subs = re.subn(pattern, replacement, line)
        if num_subs > 0:
            return reformatted_line
        return line

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
                stderr_lines = [self._reformat_dtc_output_line(line) for line in stderr_lines]
                issues_count = len(stderr_lines)
            else: # process.stderr was empty, initialize stderr_lines if it wasn't already
                stderr_lines = []


            if process.returncode == 0:
                if self.current_out_dts_tmp_file.is_file():
                    with open(self.current_out_dts_tmp_file, "r", encoding="utf-8", errors="replace") as f:
                        dts_content = f.read()
                    dtc_success = True # dtc ran and output file exists
                    self.add_to_recent_files(str(in_dtb_file_path))
                    if not stderr_lines: # If dtc was successful and process.stderr was empty
                        stderr_lines.append("dtc command executed successfully.")
                    # Apply reformatting to all lines in stderr_lines, including the newly added one.
                    stderr_lines = [self._reformat_dtc_output_line(line) for line in stderr_lines]
                    issues_count = len(stderr_lines) # Update count
                else:
                    # dtc reported success, but file is missing - this is an error condition
                    dts_content = f"Error: dtc ran successfully but output file {self.current_out_dts_tmp_file} was not created."
                    stderr_lines.append(dts_content) # Add to issues
                    stderr_lines = [self._reformat_dtc_output_line(line) for line in stderr_lines]
                    issues_count = len(stderr_lines)
                    dtc_success = False # Treat as failure for enabling features
            else:
                # dtc failed
                error_message = f"dtc command failed with exit code {process.returncode}."
                dts_content = error_message # Display error in DTS tab as well
                # stderr_lines might have content from process.stderr (already reformatted) or be empty.
                if not stderr_lines: # if dtc failed and process.stderr produced no output
                    stderr_lines.append(error_message)
                    # No reformatting needed for this specific error_message
                else: # if dtc failed and process.stderr produced output (already reformatted)
                    # Prepend the new error message, which itself doesn't need reformatting.
                    # The existing lines in stderr_lines are already reformatted.
                    stderr_lines.insert(0, error_message)
                # Reformat all lines in case new unformatted lines were added (though error_message itself is not a path)
                # This ensures consistency if stderr_lines had previous content + new content.
                # However, error_message is not a file path.
                # The lines from process.stderr are already formatted.
                # So, only reformat if we appended a simple error message to an empty list.
                # Let's ensure any line that *could* be a path is reformatted.
                # The first block `if process.stderr:` handles lines from dtc.
                # Subsequent appends/inserts are typically error messages not paths.
                # The most direct approach is to reformat `stderr_lines` after any modification *if* new lines could be paths.
                # Given `error_message` is not a path, no reformatting needed for it.
                # stderr_lines content from `process.stderr` is already formatted.
                # So, no additional reformatting call is strictly needed here if logic is sequential.
                # For safety, a final reformat before `setPlainText` might be an option,
                # but the prompt asks for it at specific points.
                # Apply reformatting to all lines in stderr_lines, including the newly added/inserted one.
                stderr_lines = [self._reformat_dtc_output_line(line) for line in stderr_lines]
                issues_count = len(stderr_lines)
                QMessageBox.warning(self, "DTC Execution Failed",
                                    f"{error_message}\nCheck the 'Issues' tab for details.")
                dtc_success = False


        except FileNotFoundError:
            dts_content = "Error: 'dtc' command not found. Please ensure it is installed and in your PATH."
            stderr_lines = [dts_content]
            stderr_lines = [self._reformat_dtc_output_line(line) for line in stderr_lines]
            issues_count = 1
            dtc_success = False
            QMessageBox.critical(self, "Error", dts_content)
        except Exception as e:
            dts_content = f"An unexpected error occurred during dtc execution: {e}"
            stderr_lines = [str(e)]
            stderr_lines = [self._reformat_dtc_output_line(line) for line in stderr_lines]
            issues_count = 1
            dtc_success = False
            QMessageBox.critical(self, "Error", dts_content)

        # Final catch-all reformatting before display can be an option,
        # but sticking to specified locations.
        # The current logic is that lines from `process.stderr` are reformatted once.
        # Other generated messages are not file paths and don't need reformatting.

        self.current_dts_content = dts_content
        self.dts_text_edit.setPlainText(self.current_dts_content)
        # Ensure all lines are processed before display
        # This is a good safety net, though ideally covered by earlier points.
        # The prompt asks for modifications at population points.
        # Let's re-evaluate the diff based on the prompt's specific wording.

        # Re-evaluating the changes to be more direct as per prompt:
        # 1. After `stderr_lines = process.stderr.strip().splitlines()` - DONE by first hunk.
        # 2. If `stderr_lines.append(dts_content)` (dtc success, file missing) - Needs specific addition.
        # 3. If `stderr_lines.append(error_message)` or `insert(0, error_message)` (dtc failed) - Needs specific addition.
        # 4. `except FileNotFoundError` - Needs specific addition.
        # 5. `except Exception as e` - Needs specific addition.

        # The previous diff was a bit too complex in its reasoning. Let's simplify.
        # The core idea: after any assignment or modification of `stderr_lines` that might introduce a path, reformat.

        # Corrected logic for applying the reformatting:
        # The first reformat (after `process.stderr.strip().splitlines()`) is the primary one for dtc output.
        # For other cases where we append/insert messages, those messages are typically not file paths
        # that match the pattern `/tmp/BASENAME-UUID.dts`.
        # The prompt implies that *any* line added to stderr_lines should be processed.

        # Let's make the changes more directly reflecting the list:
        # Location 1: if process.stderr: stderr_lines = ...; stderr_lines = [reformat(L) for L in stderr_lines]
        # Location 2 (file missing): stderr_lines.append(dts_content); stderr_lines = [reformat(L) for L in stderr_lines]
        # Location 3 (dtc failed): stderr_lines.append/insert(...); stderr_lines = [reformat(L) for L in stderr_lines]
        # Location 4 (FileNotFoundError): stderr_lines = [dts_content]; stderr_lines = [reformat(L) for L in stderr_lines]
        # Location 5 (Exception): stderr_lines = [str(e)]; stderr_lines = [reformat(L) for L in stderr_lines]

        # The current diff attempt was overly conservative. A new diff is needed.
        # The provided diff is not correct. I need to generate a new one.

        # The next call will be a new replace_with_git_merge_diff with the correct changes.
        # For now, I will output the current (flawed) diff's application.
        # I will then make a new call to replace_with_git_merge_diff.

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
        # self.recent_files is intentionally not cleared here
        
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

    def update_recent_files_menu(self):
        if not hasattr(self, 'recent_files_menu'):
            print("Warning: recent_files_menu attribute does not exist. UI not fully initialized?", file=sys.stderr)
            return

        self.recent_files_menu.clear()
        if not self.recent_files:
            no_recent_action = QAction("No Recent Files", self)
            no_recent_action.setEnabled(False)
            self.recent_files_menu.addAction(no_recent_action)
            self.recent_files_menu.setEnabled(False)
        else:
            self.recent_files_menu.setEnabled(True)
            for file_path_str in self.recent_files:
                # To make menu items more readable, display only filename or part of path
                p = Path(file_path_str)
                display_text = p.name
                # Potentially add more sophisticated shortening later if needed
                # For example, if parent + name is too long: f".../{p.parent.name}/{p.name}"

                action = QAction(display_text, self)
                action.setToolTip(file_path_str) # Show full path in tooltip
                action.triggered.connect(
                    lambda checked=False, path=file_path_str: self.open_recent_file_action(path)
                )
                self.recent_files_menu.addAction(action)

            self.recent_files_menu.addSeparator()
            clear_action = QAction("Clear Recent Files List", self)
            clear_action.triggered.connect(self.clear_recent_files_list_action)
            self.recent_files_menu.addAction(clear_action)

    def open_recent_file_action(self, file_path: str):
        p = Path(file_path)
        if p.is_file():
            self.process_dtb_file(file_path) # process_dtb_file expects a string
        else:
            reply = QMessageBox.warning(
                self,
                "File Not Found",
                f"The file '{file_path}' no longer exists or is not accessible.",
                informativeText="Do you want to remove it from the recent files list?",
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                defaultButton=QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                if file_path in self.recent_files:
                    self.recent_files.remove(file_path)
                    self.save_recent_files()
                    self.update_recent_files_menu()

    def clear_recent_files_list_action(self):
        self.recent_files.clear()
        self.save_recent_files()
        self.update_recent_files_menu()


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
