"""Example: Adding a GUI progress reporter.

This example shows how to extend the progress reporting system
with a GUI implementation (e.g., using tkinter or PyQt).
"""

from typing import Any, Dict, Optional

from screen_airdrop.receiver.reporting.reporter import ProgressReporter


class GUIProgressReporter(ProgressReporter):
    """GUI-based progress reporter using a progress bar.

    Example implementation showing how to integrate with a GUI framework.
    This is a template - actual implementation would depend on your GUI library.
    """

    def __init__(self, progress_bar_widget, status_label_widget):
        """Initialize GUI reporter.

        Args:
            progress_bar_widget: GUI progress bar widget (e.g., tkinter.ttk.Progressbar)
            status_label_widget: GUI label widget for status text
        """
        self.progress_bar = progress_bar_widget
        self.status_label = status_label_widget
        self.total_chunks = None

    def report_progress(
        self,
        snapshot: Dict[str, Any],
        missing_count: Optional[int],
        elapsed_seconds: float,
    ) -> None:
        """Update GUI progress bar and status."""
        assembled = int(snapshot.get("assembled", 0))
        decode_ok = int(snapshot.get("decode_ok", 0))

        # Update progress bar
        if missing_count is not None:
            if self.total_chunks is None:
                self.total_chunks = assembled + missing_count
            if self.total_chunks > 0:
                progress_pct = (assembled / self.total_chunks) * 100
                self.progress_bar.configure(value=progress_pct)

        # Update status label
        status_text = f"Decoded: {decode_ok} | Assembled: {assembled}"
        if missing_count is not None:
            status_text += f" | Missing: {missing_count}"
        self.status_label.configure(text=status_text)

        # Force GUI update (framework-specific)
        # self.progress_bar.update_idletasks()

    def report_completion(
        self,
        status: str,
        output_path: str,
        output_size_bytes: int,
    ) -> None:
        """Show completion dialog."""
        if status == "ok":
            # Show success dialog
            # message = f"Transfer complete!\n\nOutput: {output_path}\nSize: {output_size_bytes} bytes"
            # messagebox.showinfo("Success", message)
            pass
        else:
            # Show error dialog
            # message = f"Transfer failed: {status}"
            # messagebox.showerror("Error", message)
            pass

    def report_error(self, error: str) -> None:
        """Show error dialog."""
        # messagebox.showerror("Error", error)
        pass


# Usage example:
"""
# In your GUI application:

import tkinter as tk
from tkinter import ttk

# Create GUI widgets
root = tk.Tk()
progress_bar = ttk.Progressbar(root, length=400, mode='determinate')
status_label = tk.Label(root, text="Starting...")

# Create GUI reporter
gui_reporter = GUIProgressReporter(progress_bar, status_label)

# Create pipeline runner with GUI reporter
runner = PipelineRunner(
    pipeline=pipeline,
    assembler=assembler,
    max_seconds=config.max_seconds,
    max_idle_seconds=config.max_idle_seconds,
    stats_interval=config.stats_interval,
    output_dir=config.output_dir,
    progress_reporter=gui_reporter,  # Use GUI reporter instead of console
)

# Run in separate thread to avoid blocking GUI
import threading
thread = threading.Thread(target=runner.run)
thread.start()
"""
