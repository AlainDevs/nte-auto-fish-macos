"""Targeted Quartz keyboard and mouse input for macOS."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from .window_manager import load_quartz


InputMode = Literal["pid", "hid", "both"]
EventSourceState = Literal["hid", "private", "combined", "none"]


KEY_CODES: dict[str, int] = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "m": 46,
    "space": 49,
    "esc": 53,
    "escape": 53,
    "tab": 48,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "j": 38,
    "k": 40,
    "l": 37,
    "i": 34,
    "o": 31,
    "p": 35,
    "u": 32,
    "n": 45,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
}


@dataclass(frozen=True)
class SentAction:
    """Diagnostic record for a sent or dry-run input action."""

    action_type: str
    pid: int
    detail: str


class InputController:
    """Sends targeted Quartz events to a process ID."""

    def __init__(
        self,
        quartz: Any | None = None,
        dry_run: bool = False,
        mode: InputMode = "pid",
        event_source_state: EventSourceState = "hid",
        activate_before_input: bool = False,
        activation_delay: float = 0.15,
    ) -> None:
        self.quartz = quartz if quartz is not None else load_quartz()
        self.dry_run = dry_run
        if mode not in {"pid", "hid", "both"}:
            raise ValueError("mode must be one of: pid, hid, both")
        self.mode: InputMode = mode
        if event_source_state not in {"hid", "private", "combined", "none"}:
            raise ValueError("event_source_state must be one of: hid, private, combined, none")
        self.event_source_state: EventSourceState = event_source_state
        self.activate_before_input = activate_before_input
        self.activation_delay = activation_delay
        self.sent_actions: list[SentAction] = []

    @staticmethod
    def _validate_mode(mode: InputMode) -> None:
        if mode not in {"pid", "hid", "both"}:
            raise ValueError("mode must be one of: pid, hid, both")

    @staticmethod
    def key_code_for(key: str) -> int:
        normalized = key.lower()
        if normalized not in KEY_CODES:
            raise KeyError(f"Unsupported key {key!r}. Supported keys: {sorted(KEY_CODES)}")
        return KEY_CODES[normalized]

    @staticmethod
    def is_accessibility_trusted() -> bool:
        """Return whether the current Python process is trusted for Accessibility."""
        try:
            import ApplicationServices  # type: ignore
        except ImportError:  # pragma: no cover - host/platform dependent
            return False
        checker = getattr(ApplicationServices, "AXIsProcessTrusted", None)
        if checker is None:
            return False
        return bool(checker())

    @staticmethod
    def activate_application(pid: int) -> bool:
        """Bring the target application to the foreground as a last-resort fallback."""
        try:
            import AppKit  # type: ignore
        except ImportError:  # pragma: no cover - host/platform dependent
            return False
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        options = getattr(AppKit, "NSApplicationActivateIgnoringOtherApps", 1)
        return bool(app.activateWithOptions_(options))

    def _maybe_activate(self, pid: int, activate_before_input: bool | None = None) -> None:
        should_activate = self.activate_before_input if activate_before_input is None else activate_before_input
        if not should_activate or self.dry_run:
            return
        self.activate_application(pid)
        if self.activation_delay > 0:
            time.sleep(self.activation_delay)

    def _post_event(self, pid: int, event: Any, mode: InputMode | None = None) -> None:
        event_mode = self.mode if mode is None else mode
        self._validate_mode(event_mode)
        if event_mode in {"pid", "both"}:
            self.quartz.CGEventPostToPid(pid, event)
        if event_mode in {"hid", "both"}:
            self.quartz.CGEventPost(self.quartz.kCGHIDEventTap, event)

    def _event_source(self) -> Any:
        if self.event_source_state == "none":
            return None
        state_map = {
            "hid": getattr(self.quartz, "kCGEventSourceStateHIDSystemState", 1),
            "private": getattr(self.quartz, "kCGEventSourceStatePrivate", -1),
            "combined": getattr(self.quartz, "kCGEventSourceStateCombinedSessionState", 0),
        }
        return self.quartz.CGEventSourceCreate(state_map[self.event_source_state])

    def press_key_code(self, pid: int, key_code: int, hold_seconds: float = 0.035) -> SentAction:
        detail = (
            f"key_code={key_code} hold={hold_seconds:.3f}s mode={self.mode} "
            f"source={self.event_source_state} activate={self.activate_before_input}"
        )
        action = SentAction("key", pid, detail)
        self.sent_actions.append(action)
        if self.dry_run:
            return action

        self._maybe_activate(pid)
        source = self._event_source()
        key_down = self.quartz.CGEventCreateKeyboardEvent(source, key_code, True)
        key_up = self.quartz.CGEventCreateKeyboardEvent(source, key_code, False)
        self._post_event(pid, key_down)
        if hold_seconds > 0:
            time.sleep(hold_seconds)
        self._post_event(pid, key_up)
        return action

    def press_key(self, pid: int, key: str, hold_seconds: float = 0.035) -> SentAction:
        return self.press_key_code(pid, self.key_code_for(key), hold_seconds=hold_seconds)

    def _set_mouse_event_field(self, event: Any, field_name: str, value: int) -> None:
        setter = getattr(self.quartz, "CGEventSetIntegerValueField", None)
        field = getattr(self.quartz, field_name, None)
        if setter is None or field is None:
            return
        setter(event, field, int(value))

    def _mark_left_click(self, event: Any) -> None:
        self._set_mouse_event_field(event, "kCGMouseEventButtonNumber", 0)
        self._set_mouse_event_field(event, "kCGMouseEventClickState", 1)

    def click(
        self,
        pid: int,
        x: float,
        y: float,
        hold_seconds: float = 0.035,
        mode: InputMode | None = None,
        activate_before_input: bool | None = None,
        move_before_click: bool = True,
    ) -> SentAction:
        event_mode = self.mode if mode is None else mode
        self._validate_mode(event_mode)
        should_activate = self.activate_before_input if activate_before_input is None else activate_before_input
        detail = (
            f"x={x:.1f} y={y:.1f} hold={hold_seconds:.3f}s mode={event_mode} "
            f"source={self.event_source_state} activate={should_activate} move_before_click={move_before_click}"
        )
        action = SentAction("click", pid, detail)
        self.sent_actions.append(action)
        if self.dry_run:
            return action

        self._maybe_activate(pid, activate_before_input=should_activate)
        source = self._event_source()
        point = (float(x), float(y))
        mouse_move = None
        mouse_moved_type = getattr(self.quartz, "kCGEventMouseMoved", None)
        if move_before_click and mouse_moved_type is not None:
            mouse_move = self.quartz.CGEventCreateMouseEvent(
                source,
                mouse_moved_type,
                point,
                self.quartz.kCGMouseButtonLeft,
            )
        mouse_down = self.quartz.CGEventCreateMouseEvent(
            source,
            self.quartz.kCGEventLeftMouseDown,
            point,
            self.quartz.kCGMouseButtonLeft,
        )
        mouse_up = self.quartz.CGEventCreateMouseEvent(
            source,
            self.quartz.kCGEventLeftMouseUp,
            point,
            self.quartz.kCGMouseButtonLeft,
        )
        self._mark_left_click(mouse_down)
        self._mark_left_click(mouse_up)
        if mouse_move is not None:
            self._post_event(pid, mouse_move, mode=event_mode)
        self._post_event(pid, mouse_down, mode=event_mode)
        if hold_seconds > 0:
            time.sleep(hold_seconds)
        self._post_event(pid, mouse_up, mode=event_mode)
        return action
