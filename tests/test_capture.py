from __future__ import annotations

from nte_fisher.capture import WindowCapture
from nte_fisher.window_manager import WindowBounds, WindowInfo


class FakeQuartz:
    CGRectNull = object()
    kCGWindowListOptionIncludingWindow = 1
    kCGWindowImageBoundsIgnoreFraming = 2

    def CGWindowListCreateImage(self, *args):
        return object()

    def CGImageGetWidth(self, image_ref) -> int:
        return 1

    def CGImageGetHeight(self, image_ref) -> int:
        return 1

    def CGImageGetBytesPerRow(self, image_ref) -> int:
        return 4

    def CGImageGetDataProvider(self, image_ref):
        return object()

    def CGDataProviderCopyData(self, provider) -> bytes:
        return b"\x00\x00\x00\xff"


class RecordingQuartz(FakeQuartz):
    def __init__(self) -> None:
        self.alive_objects: set[str] = set()

    def CGWindowListCreateImage(self, *args):
        self.alive_objects.add("image_ref")
        return "image_ref"

    def CGImageGetDataProvider(self, image_ref):
        assert "image_ref" in self.alive_objects
        self.alive_objects.add("provider")
        return "provider"

    def CGDataProviderCopyData(self, provider) -> bytes:
        assert "provider" in self.alive_objects
        self.alive_objects.add("pixel_data")
        return b"\x00\x00\x00\xff"


def test_window_capture_wraps_quartz_calls_in_autorelease_pool(monkeypatch) -> None:
    events: list[str] = []

    class RecordingPool:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, exc_type, exc, traceback):
            events.append("exit")

    monkeypatch.setattr("nte_fisher.capture.autorelease_pool", lambda: RecordingPool(), raising=False)
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )

    image = WindowCapture(FakeQuartz()).capture(window)

    assert image.size == (1, 1)
    assert events == ["enter", "exit"]


def test_window_capture_releases_coregraphics_objects_before_pool_exit(monkeypatch) -> None:
    quartz = RecordingQuartz()
    events: list[set[str]] = []

    class RecordingPool:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, traceback):
            events.append(set(quartz.alive_objects))

    monkeypatch.setattr("nte_fisher.capture.autorelease_pool", lambda: RecordingPool(), raising=False)
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )

    image = WindowCapture(quartz).capture(window)

    image.close()

    assert events == [set()]
