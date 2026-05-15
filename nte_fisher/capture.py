"""Background window capture using CoreGraphics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .window_manager import WindowInfo, load_quartz


class WindowCapture:
    """Captures a specific macOS window even when it is obscured."""

    def __init__(self, quartz: Any | None = None) -> None:
        self.quartz = quartz if quartz is not None else load_quartz()

    def capture(self, window: WindowInfo) -> Image.Image:
        image_ref = self.quartz.CGWindowListCreateImage(
            self.quartz.CGRectNull,
            self.quartz.kCGWindowListOptionIncludingWindow,
            window.window_id,
            self.quartz.kCGWindowImageBoundsIgnoreFraming,
        )
        if image_ref is None:
            raise RuntimeError(
                f"Quartz returned no image for window_id={window.window_id}. "
                "Ensure the window is not minimized and Screen Recording permission is granted."
            )

        width = int(self.quartz.CGImageGetWidth(image_ref))
        height = int(self.quartz.CGImageGetHeight(image_ref))
        bytes_per_row = int(self.quartz.CGImageGetBytesPerRow(image_ref))

        provider = self.quartz.CGImageGetDataProvider(image_ref)
        pixel_data = self.quartz.CGDataProviderCopyData(provider)
        data = bytes(pixel_data)

        image = Image.frombuffer(
            "RGBA",
            (width, height),
            data,
            "raw",
            "BGRA",
            bytes_per_row,
            1,
        )
        return image.copy()

    def save_capture(self, window: WindowInfo, output_path: str | Path) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        image = self.capture(window)
        image.save(output)
        return output

