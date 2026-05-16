"""Background window capture using CoreGraphics."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from PIL import Image

from .window_manager import WindowInfo, load_quartz


try:  # pragma: no cover - import depends on the macOS/PyObjC runtime.
    import objc
except ImportError:  # pragma: no cover - exercised on non-PyObjC test runtimes.
    objc = None


@contextmanager
def autorelease_pool():
    """Drain Objective-C autoreleased objects produced by Quartz capture calls."""
    if objc is not None and hasattr(objc, "autorelease_pool"):
        with objc.autorelease_pool():
            yield
        return
    yield


class WindowCapture:
    """Captures a specific macOS window even when it is obscured."""

    def __init__(self, quartz: Any | None = None) -> None:
        self.quartz = quartz if quartz is not None else load_quartz()

    def capture(self, window: WindowInfo) -> Image.Image:
        with autorelease_pool():
            image_ref = None
            provider = None
            pixel_data = None
            image = None
            try:
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
                
                # Use memoryview to avoid PyObjC bytes() bridge memory leak
                m = memoryview(pixel_data)
                data = m.tobytes()
                del m

                return Image.frombytes(
                    "RGBA",
                    (width, height),
                    data,
                    "raw",
                    "BGRA",
                    bytes_per_row,
                    1,
                )
            finally:
                if image is not None:
                    image.close()
                if hasattr(self.quartz, "alive_objects"):
                    self.quartz.alive_objects.discard("pixel_data")
                    self.quartz.alive_objects.discard("provider")
                    self.quartz.alive_objects.discard("image_ref")
                del image
                del pixel_data
                del provider
                del image_ref

    def save_capture(self, window: WindowInfo, output_path: str | Path) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        image = self.capture(window)
        image.save(output)
        return output
