from __future__ import annotations

import pytest

from nte_fisher.input_control import InputController


class FakeQuartz:
    kCGHIDEventTap = "hid"
    kCGEventSourceStateHIDSystemState = 1
    kCGEventSourceStatePrivate = -1
    kCGEventSourceStateCombinedSessionState = 0
    kCGEventLeftMouseDown = "mouse_down"
    kCGEventLeftMouseUp = "mouse_up"
    kCGMouseButtonLeft = "left"

    def __init__(self):
        self.posted = []
        self.posted_hid = []
        self.alive_events = []

    def CGEventSourceCreate(self, state):
        return ("source", state)

    def CGEventCreateKeyboardEvent(self, source, key_code, is_down):
        event = ("key", source, key_code, is_down)
        self.alive_events.append(event)
        return event

    def CGEventCreateMouseEvent(self, source, event_type, point, button):
        event = ("mouse", source, event_type, point, button)
        self.alive_events.append(event)
        return event

    def CGEventPostToPid(self, pid, event):
        self.posted.append((pid, event))

    def CGEventPost(self, tap, event):
        self.posted_hid.append((tap, event))


class FakeQuartzWithMouseMetadata(FakeQuartz):
    kCGEventMouseMoved = "mouse_moved"
    kCGMouseEventButtonNumber = "button_number"
    kCGMouseEventClickState = "click_state"

    def CGEventCreateMouseEvent(self, source, event_type, point, button):
        event = {
            "kind": "mouse",
            "source": source,
            "event_type": event_type,
            "point": point,
            "button": button,
            "fields": {},
        }
        self.alive_events.append(event)
        return event

    def CGEventSetIntegerValueField(self, event, field, value):
        event["fields"][field] = value


def test_key_code_for_known_keys() -> None:
    assert InputController.key_code_for("f") == 3
    assert InputController.key_code_for("M") == 46
    assert InputController.key_code_for("esc") == 53


def test_key_code_for_unknown_key_raises() -> None:
    with pytest.raises(KeyError):
        InputController.key_code_for("not-a-key")


def test_press_key_posts_down_and_up_events() -> None:
    quartz = FakeQuartz()
    controller = InputController(quartz=quartz)

    action = controller.press_key(1234, "f", hold_seconds=0)

    assert action.action_type == "key"
    assert quartz.posted == [
        (1234, ("key", ("source", 1), 3, True)),
        (1234, ("key", ("source", 1), 3, False)),
    ]


def test_click_posts_mouse_down_and_up_events() -> None:
    quartz = FakeQuartz()
    controller = InputController(quartz=quartz)

    action = controller.click(1234, 10.5, 20.25, hold_seconds=0)

    assert action.action_type == "click"
    assert quartz.posted == [
        (1234, ("mouse", ("source", 1), "mouse_down", (10.5, 20.25), "left")),
        (1234, ("mouse", ("source", 1), "mouse_up", (10.5, 20.25), "left")),
    ]


def test_click_can_override_mode_and_marks_mouse_click_metadata() -> None:
    quartz = FakeQuartzWithMouseMetadata()
    controller = InputController(quartz=quartz, mode="pid")

    action = controller.click(1234, 10, 20, hold_seconds=0, mode="hid", activate_before_input=False)

    assert action.action_type == "click"
    assert quartz.posted == []
    assert [event[1]["event_type"] for event in quartz.posted_hid] == [
        "mouse_moved",
        "mouse_down",
        "mouse_up",
    ]
    assert quartz.posted_hid[1][1]["fields"] == {"button_number": 0, "click_state": 1}
    assert quartz.posted_hid[2][1]["fields"] == {"button_number": 0, "click_state": 1}


def test_dry_run_does_not_post_events() -> None:
    quartz = FakeQuartz()
    controller = InputController(quartz=quartz, dry_run=True)

    controller.press_key(1234, "f")
    controller.click(1234, 1, 2)

    assert quartz.posted == []
    assert [action.action_type for action in controller.sent_actions] == ["key", "click"]


def test_hid_mode_posts_to_event_tap() -> None:
    quartz = FakeQuartz()
    controller = InputController(quartz=quartz, mode="hid")

    controller.press_key(1234, "f", hold_seconds=0)

    assert quartz.posted == []
    assert quartz.posted_hid == [
        ("hid", ("key", ("source", 1), 3, True)),
        ("hid", ("key", ("source", 1), 3, False)),
    ]


def test_both_mode_posts_to_pid_and_event_tap() -> None:
    quartz = FakeQuartz()
    controller = InputController(quartz=quartz, mode="both")

    controller.press_key(1234, "f", hold_seconds=0)

    assert quartz.posted == [
        (1234, ("key", ("source", 1), 3, True)),
        (1234, ("key", ("source", 1), 3, False)),
    ]
    assert quartz.posted_hid == [
        ("hid", ("key", ("source", 1), 3, True)),
        ("hid", ("key", ("source", 1), 3, False)),
    ]


def test_none_event_source_uses_none_source() -> None:
    quartz = FakeQuartz()
    controller = InputController(quartz=quartz, event_source_state="none")

    controller.press_key(1234, "f", hold_seconds=0)

    assert quartz.posted == [
        (1234, ("key", None, 3, True)),
        (1234, ("key", None, 3, False)),
    ]


def test_accessibility_prompt_uses_trusted_check_with_options(monkeypatch) -> None:
    calls = []

    class FakeApplicationServices:
        kAXTrustedCheckOptionPrompt = "prompt"

        @staticmethod
        def AXIsProcessTrustedWithOptions(options):
            calls.append(options)
            return True

    import sys

    monkeypatch.setitem(sys.modules, "ApplicationServices", FakeApplicationServices)

    assert InputController.is_accessibility_trusted(prompt=True) is True
    assert calls == [{"prompt": True}]


def test_reset_accessibility_permission_runs_tccutil(monkeypatch) -> None:
    import sys
    import types

    calls = []

    def fake_run(command, check=False, capture_output=False, text=False):
        calls.append((command, check, capture_output, text))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setitem(sys.modules, "subprocess", types.SimpleNamespace(run=fake_run))

    assert InputController.reset_accessibility_permission("com.example.app") is True
    assert calls == [(["tccutil", "reset", "Accessibility", "com.example.app"], False, True, True)]


def test_press_key_wraps_quartz_events_in_autorelease_pool_and_releases_refs(monkeypatch) -> None:
    quartz = FakeQuartz()
    snapshots: list[list[object]] = []

    class RecordingPool:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, traceback):
            snapshots.append(list(quartz.alive_events))

    monkeypatch.setattr("nte_fisher.input_control.autorelease_pool", lambda: RecordingPool(), raising=False)
    controller = InputController(quartz=quartz)

    controller.press_key(1234, "f", hold_seconds=0)

    assert quartz.posted == [
        (1234, ("key", ("source", 1), 3, True)),
        (1234, ("key", ("source", 1), 3, False)),
    ]
    assert snapshots == [[]]


def test_click_wraps_quartz_events_in_autorelease_pool_and_releases_refs(monkeypatch) -> None:
    quartz = FakeQuartzWithMouseMetadata()
    snapshots: list[list[object]] = []

    class RecordingPool:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, traceback):
            snapshots.append(list(quartz.alive_events))

    monkeypatch.setattr("nte_fisher.input_control.autorelease_pool", lambda: RecordingPool(), raising=False)
    controller = InputController(quartz=quartz)

    controller.click(1234, 10, 20, hold_seconds=0)

    assert [event[1]["event_type"] for event in quartz.posted] == ["mouse_moved", "mouse_down", "mouse_up"]
    assert snapshots == [[]]
