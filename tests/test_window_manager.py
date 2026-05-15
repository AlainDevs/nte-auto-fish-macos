from __future__ import annotations

import pytest

from nte_fisher.window_manager import WindowBounds, WindowInfo, WindowManager


class FakeQuartz:
    kCGWindowListOptionOnScreenOnly = 1
    kCGWindowListExcludeDesktopElements = 16
    kCGWindowListOptionAll = 0
    kCGNullWindowID = 0

    def __init__(self, windows):
        self.windows = windows

    def CGWindowListCopyWindowInfo(self, options, window_id):
        assert options == 0
        assert window_id == 0
        return self.windows


def test_find_window_prefers_largest_layer_zero_match() -> None:
    windows = [
        {
            "kCGWindowOwnerName": "NTE",
            "kCGWindowName": "Small overlay",
            "kCGWindowOwnerPID": 111,
            "kCGWindowNumber": 10,
            "kCGWindowLayer": 1,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 100},
        },
        {
            "kCGWindowOwnerName": "NTE",
            "kCGWindowName": "Main",
            "kCGWindowOwnerPID": 111,
            "kCGWindowNumber": 11,
            "kCGWindowLayer": 0,
            "kCGWindowBounds": {"X": 10, "Y": 20, "Width": 1280, "Height": 720},
        },
    ]
    manager = WindowManager(quartz=FakeQuartz(windows))

    result = manager.find_window("nte")

    assert result.window_id == 11
    assert result.pid == 111
    assert result.bounds.width == 1280


def test_find_window_can_filter_by_pid_and_window_id() -> None:
    windows = [
        {
            "kCGWindowOwnerName": "NTE",
            "kCGWindowName": "Wrong PID",
            "kCGWindowOwnerPID": 222,
            "kCGWindowNumber": 20,
            "kCGWindowLayer": 0,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600},
        },
        {
            "kCGWindowOwnerName": "NTE",
            "kCGWindowName": "Correct",
            "kCGWindowOwnerPID": 333,
            "kCGWindowNumber": 21,
            "kCGWindowLayer": 0,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 900, "Height": 600},
        },
    ]
    manager = WindowManager(quartz=FakeQuartz(windows))

    result = manager.find_window("NTE", pid=333, window_id=21)

    assert result.window_name == "Correct"


def test_find_window_raises_when_no_match() -> None:
    manager = WindowManager(quartz=FakeQuartz([]))

    with pytest.raises(LookupError):
        manager.find_window("NTE")


def test_to_global_point_handles_retina_scaling() -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=123,
        window_id=456,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )

    assert window.to_global_point(800, 400, capture_width=1600, capture_height=800) == (500, 400)

    with pytest.raises(ValueError):
        window.to_global_point(1, 1, capture_width=0, capture_height=1)


def test_query_ranking_prefers_owner_match_over_title_match() -> None:
    windows = [
        {
            "kCGWindowOwnerName": "Code",
            "kCGWindowName": "README.md — nte-auto-fish-macos",
            "kCGWindowOwnerPID": 444,
            "kCGWindowNumber": 30,
            "kCGWindowLayer": 0,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1352, "Height": 848},
        },
        {
            "kCGWindowOwnerName": "NTE",
            "kCGWindowName": "NTE  ",
            "kCGWindowOwnerPID": 36240,
            "kCGWindowNumber": 31,
            "kCGWindowLayer": 0,
            "kCGWindowBounds": {"X": 0, "Y": 30, "Width": 1352, "Height": 848},
        },
    ]
    manager = WindowManager(quartz=FakeQuartz(windows))

    result = manager.find_window("NTE")

    assert result.owner_name == "NTE"
    assert result.pid == 36240
    assert [window.owner_name for window in manager.list_windows("NTE")] == ["NTE"]


def test_short_query_does_not_match_inside_unrelated_words() -> None:
    windows = [
        {
            "kCGWindowOwnerName": "Notification Centre",
            "kCGWindowName": "Notification Center",
            "kCGWindowOwnerPID": 555,
            "kCGWindowNumber": 40,
            "kCGWindowLayer": 21,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 1352, "Height": 878},
        },
        {
            "kCGWindowOwnerName": "NTE",
            "kCGWindowName": "NTE  ",
            "kCGWindowOwnerPID": 36240,
            "kCGWindowNumber": 41,
            "kCGWindowLayer": 0,
            "kCGWindowBounds": {"X": 0, "Y": 30, "Width": 1352, "Height": 848},
        },
    ]
    manager = WindowManager(quartz=FakeQuartz(windows))

    results = manager.list_windows("NTE")

    assert [window.owner_name for window in results] == ["NTE"]
