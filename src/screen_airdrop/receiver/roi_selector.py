"""Interactive ROI selector with transparent overlay."""

from typing import Callable, Optional, Tuple


def select_region(
    monitor_region: Tuple[int, int, int, int],
    title: str = "Select Region",
    on_confirm: Optional[Callable[[Tuple[int, int, int, int]], None]] = None,
) -> Optional[Tuple[int, int, int, int]]:
    """Show a transparent selection window on the monitor.

    Returns absolute screen coordinates (x, y, w, h) of the selected region,
    or None if cancelled.

    Coordinates are derived from event.x_root / event.y_root (absolute screen
    position), so the result is correct regardless of where the overlay window
    is placed or moved on screen.

    Args:
        monitor_region: (left, top, width, height) of the monitor to overlay
        title: window title
        on_confirm: optional callback invoked after window is hidden but before
                    returning. Use this to start capture/decode work while the
                    compositor is still flushing the overlay from screen buffer.

    Keys:
        Drag  – draw selection rectangle
        Enter – confirm selection
        R     – reset / redraw selection
        Esc   – cancel
    """

    left, top, width, height = monitor_region

    try:
        import tkinter as tk
    except Exception as exc:
        raise RuntimeError(f"tkinter required: {exc}")

    root = tk.Tk()
    root.title("ROI Selector – Enter确认 | R重绘 | Esc取消")
    root.geometry(f"{width}x{height}+{left}+{top}")
    root.attributes("-alpha", 0.3)
    root.attributes("-topmost", True)

    canvas = tk.Canvas(root, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)

    canvas.create_text(
        width // 2,
        40,
        text="拖动鼠标选择区域",
        fill="#00FF00",
        font=("Arial", 24, "bold"),
        tags="instruction",
    )
    canvas.create_text(
        width // 2,
        85,
        text="Enter 确认 | R 重绘 | Esc 取消",
        fill="#FFFF00",
        font=("Arial", 18),
        tags="instruction",
    )

    # Canvas-relative coords for drawing the rectangle on screen.
    start_canvas = None
    current_canvas = None
    # Absolute screen coords for computing the final result.
    start_abs = None
    current_abs = None

    rect_id = None
    result = None

    def reset_selection():
        nonlocal start_canvas, current_canvas, start_abs, current_abs, rect_id
        start_canvas = None
        current_canvas = None
        start_abs = None
        current_abs = None
        if rect_id is not None:
            canvas.delete(rect_id)
            rect_id = None

    def on_press(event):
        nonlocal start_canvas, current_canvas, start_abs, current_abs, rect_id
        reset_selection()
        start_canvas = (event.x, event.y)
        current_canvas = start_canvas
        # x_root / y_root are absolute screen coordinates – independent of
        # where/how the overlay window is positioned or decorated.
        start_abs = (event.x_root, event.y_root)
        current_abs = start_abs
        rect_id = canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#00FF00",
            width=4,
            dash=(10, 5),
        )

    def on_drag(event):
        nonlocal current_canvas, current_abs
        if start_canvas is None or rect_id is None:
            return
        current_canvas = (event.x, event.y)
        current_abs = (event.x_root, event.y_root)
        x1, y1 = start_canvas
        canvas.coords(rect_id, x1, y1, event.x, event.y)

    def on_key(event):
        nonlocal result
        if event.keysym == "Return":
            if start_abs is not None and current_abs is not None:
                x = min(start_abs[0], current_abs[0])
                y = min(start_abs[1], current_abs[1])
                w = abs(current_abs[0] - start_abs[0])
                h = abs(current_abs[1] - start_abs[1])
                if w > 0 and h > 0:
                    result = (x, y, w, h)
                    root.withdraw()
                    root.update_idletasks()
                    # Schedule callback after compositor has time to flush
                    if on_confirm is not None:
                        confirmed_result = result
                        callback = on_confirm
                        root.after(400, lambda: callback(confirmed_result))
                    # Delay quit to allow the callback to execute
                    root.after(450, root.quit)
        elif event.keysym in ("r", "R"):
            reset_selection()
        elif event.keysym == "Escape":
            root.withdraw()
            root.update_idletasks()
            root.after(50, root.quit)

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    root.bind("<Key>", on_key)

    root.mainloop()

    try:
        root.destroy()
    except Exception:
        pass

    return result
