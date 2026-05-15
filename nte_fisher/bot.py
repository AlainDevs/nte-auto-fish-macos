"""NTE auto-fishing state machine."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from .capture import WindowCapture
from .input_control import EventSourceState, InputController, InputMode
from .vision import MatchMethod, MatchResult, TemplateMatcher
from .window_manager import WindowInfo, WindowManager, format_window


StartPhase = str


LOGGER = logging.getLogger("nte_fisher")


@dataclass(frozen=True)
class BotConfig:
    """Timing and matching configuration for the fishing bot."""

    query: str = "NTE"
    pid: int | None = None
    window_id: int | None = None
    threshold: float = 0.80
    match_method: MatchMethod = "ccoeff"
    scan_interval: float = 0.08
    catch_scan_interval: float = 0.03
    post_start_delay: float = 0.300
    catch_to_map_delay: float = 0.666
    time_to_open_map_scan_interval: float = 0.03
    map_key: str = "m"
    map_key_retries: int = 3
    map_key_retry_delay: float = 0.250
    esc_delay: float = 0.250
    recast_delay: float = 1.500
    key_hold_seconds: float = 0.100
    click_hold_seconds: float = 0.035
    input_mode: InputMode = "pid"
    click_input_mode: InputMode | None = None
    event_source_state: EventSourceState = "hid"
    activate_before_input: bool = False
    activate_before_click: bool | None = None
    activation_delay: float = 0.15
    start_at: StartPhase = "start"
    max_cycles: int | None = None
    dry_run: bool = False
    log_wait_every: float = 2.0
    wait_timeout: float | None = None
    confirm_actions: bool = True
    start_absence_confirm_timeout: float = 8.0
    action_confirm_timeout: float = 2.0
    absence_confirm_duration: float = 0.20
    init_click_confirm_timeout: float = 2.0
    init_click_retries: int = 2
    init_click_retry_delay: float = 0.25
    click_foreground_fallback: bool = True


class AutoFishingBot:
    """Runs the requested NTE fishing loop against a background window."""

    def __init__(
        self,
        config: BotConfig,
        window_manager: WindowManager | None = None,
        capture: WindowCapture | None = None,
        matcher: TemplateMatcher | None = None,
        input_controller: InputController | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.window_manager = window_manager if window_manager is not None else WindowManager()
        self.capture = capture if capture is not None else WindowCapture()
        methods = None if config.match_method == "ccoeff" else {
            "start_fishing": config.match_method,
            "catch_now": config.match_method,
            "time_to_open_map": config.match_method,
            "return": config.match_method,
            "failed_catch": config.match_method,
            "init_start": config.match_method,
        }
        self.matcher = matcher if matcher is not None else TemplateMatcher(threshold=config.threshold, methods=methods)
        self.input = input_controller if input_controller is not None else InputController(
            dry_run=config.dry_run,
            mode=config.input_mode,
            event_source_state=config.event_source_state,
            activate_before_input=config.activate_before_input,
            activation_delay=config.activation_delay,
        )
        self.sleep = sleep
        self.window: WindowInfo | None = None

    def resolve_window(self) -> WindowInfo:
        self.window = self.window_manager.find_window(
            query=self.config.query,
            pid=self.config.pid,
            window_id=self.config.window_id,
        )
        LOGGER.info("Target window resolved: %s", format_window(self.window))
        return self.window

    def _current_window(self) -> WindowInfo:
        if self.window is None:
            return self.resolve_window()
        return self.window

    def refresh_window(self) -> WindowInfo:
        previous = self._current_window()
        refreshed = self.window_manager.find_window(
            query=self.config.query,
            pid=previous.pid,
            window_id=previous.window_id,
        )
        if refreshed.bounds != previous.bounds:
            LOGGER.info(
                "Window bounds refreshed: old=(%.1f, %.1f, %.1f, %.1f) new=(%.1f, %.1f, %.1f, %.1f)",
                previous.bounds.x,
                previous.bounds.y,
                previous.bounds.width,
                previous.bounds.height,
                refreshed.bounds.x,
                refreshed.bounds.y,
                refreshed.bounds.width,
                refreshed.bounds.height,
            )
        self.window = refreshed
        return refreshed

    def wait_for_template(
        self,
        template_name: str,
        scan_interval: float,
        timeout: float | None = None,
    ) -> tuple[MatchResult, Image.Image]:
        window = self._current_window()
        start = time.monotonic()
        last_log = 0.0
        best_score = -1.0
        wait_timeout = self.config.wait_timeout if timeout is None else timeout

        LOGGER.info("Waiting for template=%s threshold=%.2f", template_name, self.config.threshold)
        while True:
            image = self.capture.capture(window)
            scored = self.matcher.score(image, template_name)
            now = time.monotonic()

            if scored is None:
                confidence = -1.0
                center = None
            else:
                confidence = scored.confidence
                center = scored.center
                best_score = max(best_score, confidence)

            if scored is not None and confidence >= self.config.threshold:
                elapsed = now - start
                LOGGER.info(
                    "Detected template=%s confidence=%.4f top_left=%s center=%s capture=%s elapsed=%.3fs",
                    scored.template_name,
                    scored.confidence,
                    scored.top_left,
                    scored.center,
                    scored.capture_size,
                    elapsed,
                )
                return scored, image

            if now - last_log >= self.config.log_wait_every:
                LOGGER.info(
                    "Still waiting template=%s elapsed=%.1fs best_confidence=%.4f last_confidence=%.4f last_center=%s",
                    template_name,
                    now - start,
                    best_score,
                    confidence,
                    center,
                )
                last_log = now

            if wait_timeout is not None and now - start >= wait_timeout:
                raise TimeoutError(
                    f"Timed out waiting for template={template_name!r} after "
                    f"{wait_timeout:.1f}s; best_confidence={best_score:.4f}"
                )

            self.sleep(scan_interval)

    def wait_for_any_template(
        self,
        template_names: tuple[str, ...],
        scan_interval: float,
        timeout: float | None = None,
    ) -> tuple[MatchResult, Image.Image]:
        """Wait until any template in a set is detected, returning the first above threshold."""
        if not template_names:
            raise ValueError("At least one template name is required")

        window = self._current_window()
        start = time.monotonic()
        last_log = 0.0
        best_scores = {template_name: -1.0 for template_name in template_names}
        wait_timeout = self.config.wait_timeout if timeout is None else timeout
        template_list = ",".join(template_names)

        LOGGER.info("Waiting for any template=%s threshold=%.2f", template_list, self.config.threshold)
        while True:
            image = self.capture.capture(window)
            now = time.monotonic()
            last_confidences: dict[str, float] = {}
            last_centers: dict[str, tuple[int, int] | None] = {}

            for template_name in template_names:
                scored = self.matcher.score(image, template_name)
                if scored is None:
                    confidence = -1.0
                    center = None
                else:
                    confidence = scored.confidence
                    center = scored.center
                    best_scores[template_name] = max(best_scores[template_name], confidence)

                last_confidences[template_name] = confidence
                last_centers[template_name] = center

                if scored is not None and confidence >= self.config.threshold:
                    elapsed = now - start
                    LOGGER.info(
                        "Detected template=%s confidence=%.4f top_left=%s center=%s capture=%s elapsed=%.3fs",
                        scored.template_name,
                        scored.confidence,
                        scored.top_left,
                        scored.center,
                        scored.capture_size,
                        elapsed,
                    )
                    return scored, image

            if now - last_log >= self.config.log_wait_every:
                LOGGER.info(
                    "Still waiting templates=%s elapsed=%.1fs best_confidences=%s last_confidences=%s last_centers=%s",
                    template_list,
                    now - start,
                    {name: round(score, 4) for name, score in best_scores.items()},
                    {name: round(score, 4) for name, score in last_confidences.items()},
                    last_centers,
                )
                last_log = now

            if wait_timeout is not None and now - start >= wait_timeout:
                best_summary = ", ".join(f"{name}={score:.4f}" for name, score in best_scores.items())
                raise TimeoutError(
                    f"Timed out waiting for any template={template_names!r} after "
                    f"{wait_timeout:.1f}s; best_confidences={best_summary}"
                )

            self.sleep(scan_interval)

    def wait_for_template_absent(
        self,
        template_name: str,
        scan_interval: float,
        timeout: float,
        stable_duration: float,
    ) -> None:
        """Wait until a template is below threshold for a stable period."""
        window = self._current_window()
        start = time.monotonic()
        absent_since: float | None = None
        best_present_score = -1.0

        LOGGER.info(
            "Confirming template=%s is absent timeout=%.2fs stable=%.2fs threshold=%.2f",
            template_name,
            timeout,
            stable_duration,
            self.config.threshold,
        )
        while True:
            image = self.capture.capture(window)
            scored = self.matcher.score(image, template_name)
            now = time.monotonic()
            confidence = -1.0 if scored is None else scored.confidence
            best_present_score = max(best_present_score, confidence)

            if confidence < self.config.threshold:
                if absent_since is None:
                    absent_since = now
                if now - absent_since >= stable_duration:
                    LOGGER.info(
                        "Confirmed template=%s absent for %.3fs last_confidence=%.4f elapsed=%.3fs",
                        template_name,
                        now - absent_since,
                        confidence,
                        now - start,
                    )
                    return
            else:
                absent_since = None

            if now - start >= timeout:
                raise TimeoutError(
                    f"Timed out confirming template={template_name!r} absent after {timeout:.1f}s; "
                    f"last_confidence={confidence:.4f} best_confidence={best_present_score:.4f}"
                )

            self.sleep(scan_interval)

    def confirm_absent_after_action(self, template_name: str) -> None:
        if self.config.dry_run:
            LOGGER.info("Dry-run: skipping action-effect confirmation for template=%s", template_name)
            return
        if not self.config.confirm_actions:
            LOGGER.info("Action confirmation disabled for template=%s", template_name)
            return
        timeout = self.config.action_confirm_timeout
        if template_name == "start_fishing":
            timeout = self.config.start_absence_confirm_timeout
        self.wait_for_template_absent(
            template_name,
            scan_interval=self.config.scan_interval,
            timeout=timeout,
            stable_duration=self.config.absence_confirm_duration,
        )

    def wait_until_time_to_open_map(self) -> MatchResult:
        """Wait for the post-catch visual cue that it is safe to open the map."""
        timeout = max(0.0, self.config.catch_to_map_delay)
        if timeout <= 0:
            image = self.capture.capture(self._current_window())
            scored = self.matcher.score(image, "time_to_open_map")
            if scored is not None and scored.confidence >= self.config.threshold:
                LOGGER.info(
                    "Detected template=%s confidence=%.4f top_left=%s center=%s capture=%s elapsed=0.000s",
                    scored.template_name,
                    scored.confidence,
                    scored.top_left,
                    scored.center,
                    scored.capture_size,
                )
                return scored
            LOGGER.info(
                "time_to_open_map not detected before map key and catch_to_map_delay is %.0fms; opening map immediately",
                self.config.catch_to_map_delay * 1000,
            )
            raise TimeoutError("time_to_open_map not detected and catch_to_map_delay is disabled")

        try:
            match, _ = self.wait_for_template(
                "time_to_open_map",
                self.config.time_to_open_map_scan_interval,
                timeout=timeout,
            )
            LOGGER.info("time_to_open_map detected; opening map immediately")
            return match
        except TimeoutError:
            LOGGER.info(
                "time_to_open_map not detected within %.0fms; opening map using fallback delay",
                timeout * 1000,
            )
            raise

    def press(self, key: str) -> None:
        window = self._current_window()
        action = self.input.press_key(window.pid, key, hold_seconds=self.config.key_hold_seconds)
        LOGGER.info(
            "Input action=%s pid=%s detail=%s dry_run=%s",
            action.action_type,
            action.pid,
            action.detail,
            self.config.dry_run,
        )

    def press_repeated(self, key: str, count: int, delay: float) -> None:
        for index in range(count):
            LOGGER.info("Repeated input key=%s attempt=%d/%d", key, index + 1, count)
            self.press(key)
            if index < count - 1 and delay > 0:
                self.sleep(delay)

    def _configured_click_mode(self) -> InputMode:
        return self.config.click_input_mode or self.config.input_mode

    def _configured_click_activation(self) -> bool | None:
        return self.config.activate_before_click

    def _pre_activate_for_click(self, window: WindowInfo, click_activation: bool | None) -> None:
        if not click_activation or self.config.dry_run:
            return
        activator = getattr(self.input, "activate_application", None)
        if activator is None:
            return
        activated = bool(activator(window.pid))
        LOGGER.info(
            "Pre-activated target before click coordinate refresh pid=%s activated=%s",
            window.pid,
            activated,
        )
        if self.config.activation_delay > 0:
            self.sleep(self.config.activation_delay)

    def click_match_center(
        self,
        match: MatchResult,
        mode: InputMode | None = None,
        activate_before_input: bool | None = None,
    ) -> None:
        click_mode = self._configured_click_mode() if mode is None else mode
        click_activation = self._configured_click_activation() if activate_before_input is None else activate_before_input
        self._pre_activate_for_click(self._current_window(), click_activation)
        window = self.refresh_window()
        global_x, global_y = window.to_global_point(
            match.center[0],
            match.center[1],
            match.capture_size[0],
            match.capture_size[1],
        )
        LOGGER.info(
            "Clicking template=%s image_center=%s global=(%.1f, %.1f) window_bounds=(%.1f, %.1f, %.1f, %.1f) click_mode=%s activate_before_click=%s",
            match.template_name,
            match.center,
            global_x,
            global_y,
            window.bounds.x,
            window.bounds.y,
            window.bounds.width,
            window.bounds.height,
            click_mode,
            click_activation,
        )
        action = self.input.click(
            window.pid,
            global_x,
            global_y,
            hold_seconds=self.config.click_hold_seconds,
            mode=click_mode,
            activate_before_input=click_activation,
        )
        LOGGER.info(
            "Input action=%s pid=%s detail=%s dry_run=%s",
            action.action_type,
            action.pid,
            action.detail,
            self.config.dry_run,
        )

    def click_init_start_and_confirm(self, init_match: MatchResult) -> None:
        attempts = max(1, self.config.init_click_retries)
        last_error: TimeoutError | None = None
        match = init_match

        for attempt in range(1, attempts + 1):
            use_foreground_fallback = self.config.click_foreground_fallback and attempt > 1
            click_mode: InputMode | None = "hid" if use_foreground_fallback else None
            activate_before_input: bool | None = True if use_foreground_fallback else None
            if use_foreground_fallback:
                LOGGER.warning(
                    "Retrying init_start click with foreground HID fallback attempt=%d/%d",
                    attempt,
                    attempts,
                )
            else:
                LOGGER.info("Init_start click attempt=%d/%d", attempt, attempts)

            self.click_match_center(match, mode=click_mode, activate_before_input=activate_before_input)

            if self.config.init_click_confirm_timeout <= 0:
                LOGGER.info("Init_start click confirmation disabled")
                return

            try:
                self.wait_for_template(
                    "start_fishing",
                    self.config.scan_interval,
                    timeout=self.config.init_click_confirm_timeout,
                )
                LOGGER.info("Confirmed init_start click by detecting start_fishing")
                return
            except TimeoutError as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                LOGGER.warning(
                    "Init_start click attempt=%d/%d did not produce start_fishing within %.2fs; retrying after %.0fms",
                    attempt,
                    attempts,
                    self.config.init_click_confirm_timeout,
                    self.config.init_click_retry_delay * 1000,
                )
                if self.config.init_click_retry_delay > 0:
                    self.sleep(self.config.init_click_retry_delay)

                refreshed = self.matcher.score(self.capture.capture(self._current_window()), "init_start")
                if refreshed is not None and refreshed.confidence >= self.config.threshold:
                    match = refreshed
                    LOGGER.info(
                        "Refreshed init_start match before retry confidence=%.4f center=%s",
                        refreshed.confidence,
                        refreshed.center,
                    )

        raise TimeoutError(
            f"init_start click did not produce start_fishing after {attempts} attempt(s); "
            f"last_error={last_error}"
        )

    def _should_run_phase(self, start_at: StartPhase, phase: StartPhase) -> bool:
        phases = ["start", "catch", "return", "recast", "init"]
        if start_at not in phases:
            raise ValueError(f"Unsupported start phase {start_at!r}; expected one of {phases}")
        return phases.index(phase) >= phases.index(start_at)

    def run_cycle(self, cycle_number: int, start_at: StartPhase = "start") -> None:
        LOGGER.info("===== Cycle %d started =====", cycle_number)
        LOGGER.info("Cycle %d start phase=%s", cycle_number, start_at)

        if self._should_run_phase(start_at, "start"):
            LOGGER.info("State 1: wait for start_fishing, then press F")
            self.wait_for_template("start_fishing", self.config.scan_interval)
            self.press("f")
            if self.config.post_start_delay > 0:
                LOGGER.info("Post-start settle delay %.0fms before catch scan", self.config.post_start_delay * 1000)
                self.sleep(self.config.post_start_delay)
            self.confirm_absent_after_action("start_fishing")

        if self._should_run_phase(start_at, "catch"):
            LOGGER.info(
                "State 2: wait for catch_now, immediately press F, wait for time_to_open_map up to %.0fms, press M",
                self.config.catch_to_map_delay * 1000,
            )
            self.wait_for_template("catch_now", self.config.catch_scan_interval)
            self.press("f")
            try:
                self.wait_until_time_to_open_map()
            except TimeoutError:
                pass
            self.press_repeated(self.config.map_key, self.config.map_key_retries, self.config.map_key_retry_delay)

        if self._should_run_phase(start_at, "return"):
            LOGGER.info(
                "State 3: wait for return or failed_catch, press ESC, delay %.0fms, press ESC",
                self.config.esc_delay * 1000,
            )
            return_match, _ = self.wait_for_any_template(("return", "failed_catch"), self.config.scan_interval)
            LOGGER.info("State 3 exit trigger template=%s; backing out with ESC sequence", return_match.template_name)
            self.press("esc")
            self.sleep(self.config.esc_delay)
            self.press("esc")
            self.confirm_absent_after_action(return_match.template_name)

        if self._should_run_phase(start_at, "recast"):
            LOGGER.info("State 4: wait %.0fms, press F", self.config.recast_delay * 1000)
            self.sleep(self.config.recast_delay)
            self.press("f")

        if self._should_run_phase(start_at, "init"):
            LOGGER.info("State 5: wait for init_start, click center, then return to State 1")
            init_match, _ = self.wait_for_template("init_start", self.config.scan_interval)
            self.click_init_start_and_confirm(init_match)

        LOGGER.info("===== Cycle %d completed =====", cycle_number)

    def run(self) -> None:
        self.resolve_window()
        cycle = 1
        while self.config.max_cycles is None or cycle <= self.config.max_cycles:
            start_at = self.config.start_at if cycle == 1 else "start"
            self.run_cycle(cycle, start_at=start_at)
            cycle += 1


def configure_logging(verbose: bool = False, log_file: str | None = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )
