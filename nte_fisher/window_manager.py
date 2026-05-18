"""Window discovery and coordinate mapping for macOS Quartz windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import re


def load_quartz() -> Any:
    """Import Quartz lazily so tests can inject a fake module."""
    try:  # pragma: no cover
        import Quartz  # type: ignore  # pragma: no cover
    except ImportError as exc:  # pragma: no cover - host/platform dependent
        raise RuntimeError(
            "Quartz is unavailable. Install dependencies with "
            "`python -m pip install -r requirements.txt` on macOS."
        ) from exc
    return Quartz  # pragma: no cover


@dataclass(frozen=True)
class WindowBounds:
    """Quartz window bounds in global screen coordinates."""

    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return max(self.width, 0.0) * max(self.height, 0.0)

    @classmethod
    def from_quartz_dict(cls, data: dict[str, Any]) -> "WindowBounds":
        return cls(
            x=float(data.get("X", 0.0)),
            y=float(data.get("Y", 0.0)),
            width=float(data.get("Width", 0.0)),
            height=float(data.get("Height", 0.0)),
        )


@dataclass(frozen=True)
class WindowInfo:
    """Relevant metadata for a macOS window."""

    owner_name: str
    window_name: str
    pid: int
    window_id: int
    bounds: WindowBounds
    layer: int = 0
    alpha: float = 1.0
    sharing_state: int = 1

    @property
    def display_name(self) -> str:
        if self.window_name:  # pragma: no cover
            return f"{self.owner_name} / {self.window_name}"  # pragma: no cover
        return self.owner_name  # pragma: no cover

    def to_global_point(
        self,
        image_x: float,
        image_y: float,
        capture_width: int,
        capture_height: int,
    ) -> tuple[float, float]:
        """Map captured-image pixel coordinates to global window coordinates."""
        if capture_width <= 0 or capture_height <= 0:
            raise ValueError("capture_width and capture_height must be positive")

        scale_x = self.bounds.width / float(capture_width)
        scale_y = self.bounds.height / float(capture_height)
        return (
            self.bounds.x + (image_x * scale_x),
            self.bounds.y + (image_y * scale_y),
        )


class WindowManager:
    """Finds target game windows using Quartz window metadata."""

    def __init__(self, quartz: Any | None = None) -> None:
        self.quartz = quartz if quartz is not None else load_quartz()

    def _window_options(self) -> int:
        # Some games, including NTE during testing, do not appear in
        # kCGWindowListOptionOnScreenOnly even though their main window is
        # capturable by window ID. Use the full window list, then filter and
        # rank candidates ourselves.
        return int(getattr(self.quartz, "kCGWindowListOptionAll", 0))

    def raw_windows(self) -> list[dict[str, Any]]:
        windows = self.quartz.CGWindowListCopyWindowInfo(
            self._window_options(),
            getattr(self.quartz, "kCGNullWindowID"),
        )
        return list(windows or [])

    @staticmethod
    def _string_value(value: Any) -> str:
        return "" if value is None else str(value)

    def iter_windows(self) -> Iterable[WindowInfo]:
        for raw in self.raw_windows():
            bounds_raw = raw.get("kCGWindowBounds") or {}
            bounds = WindowBounds.from_quartz_dict(bounds_raw)
            if bounds.width <= 0 or bounds.height <= 0:
                continue  # pragma: no cover

            try:
                window_id = int(raw.get("kCGWindowNumber"))
                pid = int(raw.get("kCGWindowOwnerPID"))
            except (TypeError, ValueError):  # pragma: no cover
                continue  # pragma: no cover

            yield WindowInfo(
                owner_name=self._string_value(raw.get("kCGWindowOwnerName")),
                window_name=self._string_value(raw.get("kCGWindowName")),
                pid=pid,
                window_id=window_id,
                bounds=bounds,
                layer=int(raw.get("kCGWindowLayer", 0) or 0),
                alpha=float(raw.get("kCGWindowAlpha", 1.0) or 0.0),
                sharing_state=int(raw.get("kCGWindowSharingState", 1) or 0),
            )

    @staticmethod
    def _query_match_score(window: WindowInfo, query: str | None) -> int | None:
        if not query:
            return 0  # pragma: no cover

        query_lower = query.strip().lower()
        owner = window.owner_name.strip().lower()
        name = window.window_name.strip().lower()

        if owner == query_lower:
            return 0
        if query_lower in owner:
            return 1  # pragma: no cover
        if name == query_lower:
            return 2  # pragma: no cover
        if len(query_lower) <= 3:
            token_pattern = rf"(?<![a-z0-9]){re.escape(query_lower)}(?![a-z0-9])"
            if re.search(token_pattern, owner):
                return 1  # pragma: no cover
            return None
        if query_lower in name:  # pragma: no cover
            return 3  # pragma: no cover
        return None  # pragma: no cover

    def list_windows(self, query: str | None = None, pid: int | None = None) -> list[WindowInfo]:
        results: list[tuple[int, WindowInfo]] = []

        for window in self.iter_windows():
            if window.alpha <= 0.0:
                continue  # pragma: no cover
            if window.sharing_state == 0:
                continue  # pragma: no cover
            if pid is not None and window.pid != pid:
                continue
            score = self._query_match_score(window, query)
            if score is None:
                continue
            results.append((score, window))

        ordered = sorted(results, key=lambda item: (item[0], item[1].layer != 0, -item[1].bounds.area))
        return [window for _, window in ordered]

    def find_window(
        self,
        query: str = "NTE",
        pid: int | None = None,
        window_id: int | None = None,
    ) -> WindowInfo:
        candidates = self.list_windows(query=query, pid=pid)
        if window_id is not None:
            candidates = [window for window in candidates if window.window_id == window_id]

        if not candidates:
            pid_part = f", pid={pid}" if pid is not None else ""
            window_part = f", window_id={window_id}" if window_id is not None else ""
            raise LookupError(f"No visible window found for query={query!r}{pid_part}{window_part}")

        candidates.sort(key=lambda item: (item.layer != 0, -item.bounds.area))
        return candidates[0]


def format_window(window: WindowInfo) -> str:
    """Return a compact human-readable window summary."""
    return (
        f"owner={window.owner_name!r} name={window.window_name!r} "
        f"pid={window.pid} window_id={window.window_id} layer={window.layer} "
        f"alpha={window.alpha:.2f} sharing={window.sharing_state} "
        f"bounds=({window.bounds.x:.0f},{window.bounds.y:.0f},"
        f"{window.bounds.width:.0f}x{window.bounds.height:.0f})"
    )
