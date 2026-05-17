from __future__ import annotations

from PIL import Image

import pytest

from nte_fisher.bot import AutoFishingBot, BotConfig, StopRequested
from nte_fisher.input_control import SentAction
from nte_fisher.vision import MatchResult
from nte_fisher.window_manager import WindowBounds, WindowInfo


class FakeWindowManager:
    def __init__(self, window: WindowInfo) -> None:
        self.window = window

    def find_window(self, query=None, pid=None, window_id=None):
        return self.window


class SequenceWindowManager:
    def __init__(self, windows: list[WindowInfo]) -> None:
        self.windows = windows
        self.calls = 0

    def find_window(self, query=None, pid=None, window_id=None):
        index = min(self.calls, len(self.windows) - 1)
        self.calls += 1
        return self.windows[index]


class FakeCapture:
    def capture(self, window: WindowInfo) -> Image.Image:
        return Image.new("RGB", (1600, 800), "black")


class TrackingImage:
    def __init__(self, index: int) -> None:
        self.index = index
        self.closed = False

    def close(self) -> None:
        self.closed = True


class TrackingCapture:
    def __init__(self) -> None:
        self.images: list[TrackingImage] = []

    def capture(self, window: WindowInfo) -> TrackingImage:
        image = TrackingImage(len(self.images))
        self.images.append(image)
        return image


class FakeInput:
    def __init__(self) -> None:
        self.clicks: list[dict[str, object]] = []
        self.keys: list[str] = []
        self.activated_pids: list[int] = []

    def activate_application(self, pid: int) -> bool:
        self.activated_pids.append(pid)
        return True

    def click(self, pid, x, y, hold_seconds=0.035, mode=None, activate_before_input=None):
        self.clicks.append(
            {
                "pid": pid,
                "x": x,
                "y": y,
                "hold_seconds": hold_seconds,
                "mode": mode,
                "activate_before_input": activate_before_input,
            }
        )
        return SentAction("click", pid, f"x={x} y={y} mode={mode} activate={activate_before_input}")

    def press_key(self, pid, key, hold_seconds=0.100):
        self.keys.append(key)
        return SentAction("key", pid, f"key={key} hold={hold_seconds:.3f}s")


class FakeMatcher:
    def __init__(self, fake_input: FakeInput) -> None:
        self.fake_input = fake_input

    def score(self, image: Image.Image, template_name: str):
        if template_name == "init_start":
            return MatchResult(
                template_name="init_start",
                template_path="images/init_start.png",
                confidence=0.95,
                top_left=(200, 100),
                center=(400, 200),
                size=(100, 40),
                capture_size=(1600, 800),
            )
        if template_name == "start_fishing" and len(self.fake_input.clicks) >= 2:
            return MatchResult(
                template_name="start_fishing",
                template_path="images/start_fishing.png",
                confidence=0.95,
                top_left=(300, 200),
                center=(500, 260),
                size=(100, 40),
                capture_size=(1600, 800),
            )
        return MatchResult(
            template_name=template_name,
            template_path=f"images/{template_name}.png",
            confidence=0.10,
            top_left=(0, 0),
            center=(0, 0),
            size=(10, 10),
            capture_size=(1600, 800),
        )


class SequenceMatcher:
    def __init__(self, scores: list[dict[str, float]]) -> None:
        self.scores = scores
        self.capture_index = 0
        self.current_capture_id: int | None = None

    def score(self, image: Image.Image, template_name: str):
        capture_id = id(image)
        if self.current_capture_id != capture_id:
            self.current_capture_id = capture_id
            self.capture_index += 1
        index = min(self.capture_index - 1, len(self.scores) - 1)
        confidence = self.scores[index].get(template_name, 0.10)
        return MatchResult(
            template_name=template_name,
            template_path=f"images/{template_name}.png",
            confidence=confidence,
            top_left=(10, 20),
            center=(30, 40),
            size=(10, 10),
            capture_size=(1600, 800),
        )


class TrackingMatcher:
    def __init__(self, confidence_by_capture: list[float]) -> None:
        self.confidence_by_capture = confidence_by_capture

    def score(self, image: TrackingImage, template_name: str):
        confidence = self.confidence_by_capture[min(image.index, len(self.confidence_by_capture) - 1)]
        return MatchResult(
            template_name=template_name,
            template_path=f"images/{template_name}.png",
            confidence=confidence,
            top_left=(10, 20),
            center=(30, 40),
            size=(10, 10),
            capture_size=(1600, 800),
        )


class AlwaysMatcher:
    def __init__(self, confidence_by_template: dict[str, float]) -> None:
        self.confidence_by_template = confidence_by_template

    def score(self, image: Image.Image, template_name: str):
        confidence = self.confidence_by_template.get(template_name, 0.10)
        return MatchResult(
            template_name=template_name,
            template_path=f"images/{template_name}.png",
            confidence=confidence,
            top_left=(10, 20),
            center=(30, 40),
            size=(10, 10),
            capture_size=(1600, 800),
        )


def test_init_click_uses_single_foreground_hid_click_without_confirmation_retry() -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )
    fake_input = FakeInput()
    config = BotConfig(
        threshold=0.70,
        input_mode="pid",
        scan_interval=0,
        click_hold_seconds=0,
        init_click_confirm_timeout=0.001,
    )
    bot = AutoFishingBot(
        config,
        window_manager=FakeWindowManager(window),
        capture=FakeCapture(),
        matcher=FakeMatcher(fake_input),
        input_controller=fake_input,
        sleep=lambda seconds: None,
    )

    bot.run_cycle(1, start_at="init")

    assert len(fake_input.clicks) == 1
    assert fake_input.clicks[0]["mode"] == "hid"
    assert fake_input.clicks[0]["activate_before_input"] is False
    assert fake_input.activated_pids == [1234]
    assert fake_input.clicks[0]["x"] == 300
    assert fake_input.clicks[0]["y"] == 300


def test_wait_for_template_closes_unmatched_capture_images() -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )
    capture = TrackingCapture()
    bot = AutoFishingBot(
        BotConfig(threshold=0.70, scan_interval=0),
        window_manager=FakeWindowManager(window),
        capture=capture,
        matcher=TrackingMatcher([0.10, 0.95]),
        input_controller=FakeInput(),
        sleep=lambda seconds: None,
    )

    _, matched_image = bot.wait_for_template("start_fishing", scan_interval=0)

    assert capture.images[0].closed is True
    assert matched_image is capture.images[1]
    assert capture.images[1].closed is False


def test_run_cycle_closes_matched_capture_images_it_only_needs_for_match_data() -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )
    capture = TrackingCapture()
    bot = AutoFishingBot(
        BotConfig(threshold=0.70, scan_interval=0, click_hold_seconds=0),
        window_manager=FakeWindowManager(window),
        capture=capture,
        matcher=TrackingMatcher([0.95]),
        input_controller=FakeInput(),
        sleep=lambda seconds: None,
    )

    bot.run_cycle(1, start_at="init")

    assert [image.closed for image in capture.images] == [True]


def test_run_logs_memory_diagnostic_at_configured_cycle_interval(caplog, monkeypatch) -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )
    bot = AutoFishingBot(
        BotConfig(max_cycles=2, memory_log_every_cycles=1, gc_collect_every_cycles=0),
        window_manager=FakeWindowManager(window),
        capture=FakeCapture(),
        matcher=AlwaysMatcher({}),
        input_controller=FakeInput(),
        sleep=lambda seconds: None,
    )
    bot.run_cycle = lambda cycle_number, start_at="start": None

    monkeypatch.setattr("nte_fisher.bot.process_memory_summary", lambda: "max_rss=123.4MB")

    with caplog.at_level("INFO", logger="nte_fisher"):
        bot.run()

    assert "Memory diagnostic after cycle=1 max_rss=123.4MB" in caplog.text
    assert "Memory diagnostic after cycle=2 max_rss=123.4MB" in caplog.text


def test_run_collects_garbage_at_configured_cycle_interval(caplog, monkeypatch) -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )
    calls: list[int] = []
    bot = AutoFishingBot(
        BotConfig(max_cycles=3, memory_log_every_cycles=0, gc_collect_every_cycles=2),
        window_manager=FakeWindowManager(window),
        capture=FakeCapture(),
        matcher=AlwaysMatcher({}),
        input_controller=FakeInput(),
        sleep=lambda seconds: None,
    )
    bot.run_cycle = lambda cycle_number, start_at="start": calls.append(cycle_number)
    monkeypatch.setattr("nte_fisher.bot.gc.collect", lambda: 7)

    with caplog.at_level("INFO", logger="nte_fisher"):
        bot.run()

    assert calls == [1, 2, 3]
    assert "Garbage collection after cycle=2 collected=7" in caplog.text


def test_click_uses_refreshed_window_bounds_for_coordinate_mapping() -> None:
    initial_window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=967, y=30, width=1352, height=848),
    )
    refreshed_window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=0, y=30, width=1352, height=848),
    )
    fake_input = FakeInput()
    bot = AutoFishingBot(
        BotConfig(threshold=0.70, click_hold_seconds=0),
        window_manager=SequenceWindowManager([initial_window, refreshed_window]),
        capture=FakeCapture(),
        matcher=FakeMatcher(fake_input),
        input_controller=fake_input,
        sleep=lambda seconds: None,
    )
    match = MatchResult(
        template_name="init_start",
        template_path="images/init_start.png",
        confidence=0.95,
        top_left=(1843, 1368),
        center=(2244, 1411),
        size=(802, 86),
        capture_size=(2704, 1696),
    )

    bot.resolve_window()
    bot.click_match_center(match)

    assert fake_input.clicks[0]["x"] == 1122
    assert fake_input.clicks[0]["y"] == 735.5
    assert fake_input.clicks[0]["mode"] == "hid"
    assert fake_input.clicks[0]["activate_before_input"] is False
    assert fake_input.activated_pids == [1234]


def test_return_phase_backs_out_with_double_esc_when_failed_catch_detected(caplog) -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )
    fake_input = FakeInput()
    matcher = SequenceMatcher(
        [
            {"return": 0.20, "failed_catch": 0.30},
            {"return": 0.25, "failed_catch": 0.95},
            {"failed_catch": 0.10},
            {"time_to_click_start": 0.95},
            {"init_start": 0.95},
            {"start_fishing": 0.95},
        ]
    )
    bot = AutoFishingBot(
        BotConfig(
            threshold=0.70,
            scan_interval=0,
            esc_delay=0,
            action_confirm_timeout=0.001,
            absence_confirm_duration=0,
        ),
        window_manager=FakeWindowManager(window),
        capture=FakeCapture(),
        matcher=matcher,
        input_controller=fake_input,
        sleep=lambda seconds: None,
    )

    with caplog.at_level("INFO", logger="nte_fisher"):
        bot.run_cycle(1, start_at="return")

    assert fake_input.keys == ["esc", "esc", "f"]
    assert "State 3 exit trigger template=failed_catch" in caplog.text
    assert bot.stats.loops_completed == 1
    assert bot.stats.successful_loops == 0
    assert bot.stats.failed_fish_gone_loops == 1
    assert "session stats: loops_completed=1 successful=0 failed_fish_gone=1" in caplog.text


def test_catch_phase_opens_map_immediately_when_time_to_open_map_detected(caplog) -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )
    fake_input = FakeInput()
    stats_updates = []
    bot = AutoFishingBot(
        BotConfig(
            threshold=0.70,
            catch_scan_interval=0,
            time_to_open_map_scan_interval=0,
            catch_to_map_delay=5,
            map_key_retries=3,
            esc_delay=0,
            recast_delay=0,
            click_hold_seconds=0,
            confirm_actions=False,
        ),
        window_manager=FakeWindowManager(window),
        capture=FakeCapture(),
        matcher=AlwaysMatcher(
            {
                "catch_now": 0.95,
                "time_to_open_map": 0.95,
                "return": 0.95,
                "time_to_click_start": 0.95,
                "init_start": 0.95,
                "start_fishing": 0.95,
            }
        ),
        input_controller=fake_input,
        sleep=lambda seconds: None,
        stats_callback=stats_updates.append,
    )

    with caplog.at_level("INFO", logger="nte_fisher"):
        bot.run_cycle(1, start_at="catch")

    assert fake_input.keys[:2] == ["f", "m"]
    assert fake_input.keys.count("m") == 1
    assert "time_to_open_map detected; opening map immediately" in caplog.text
    assert "Pressing map key once key=m" in caplog.text
    assert bot.stats.loops_completed == 1
    assert bot.stats.successful_loops == 1
    assert bot.stats.failed_fish_gone_loops == 0
    assert stats_updates == [bot.stats]


def test_bot_config_defaults_keep_keyboard_pid_and_mouse_hid_foreground() -> None:
    config = BotConfig()

    assert config.input_mode == "pid"
    assert config.click_input_mode == "hid"
    assert config.activate_before_input is False
    assert config.activate_before_click is True
    assert config.max_cycles is None
    assert config.map_key_retries == 1


def test_run_checks_stop_before_second_unlimited_cycle() -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )
    calls = {"cycles": 0}

    def should_stop() -> bool:
        return calls["cycles"] >= 1

    bot = AutoFishingBot(
        BotConfig(max_cycles=None),
        window_manager=FakeWindowManager(window),
        capture=FakeCapture(),
        matcher=AlwaysMatcher({}),
        input_controller=FakeInput(),
        sleep=lambda seconds: None,
        should_stop=should_stop,
    )

    def one_cycle(cycle_number, start_at="start") -> None:
        calls["cycles"] += 1

    bot.run_cycle = one_cycle

    with pytest.raises(StopRequested):
        bot.run()

    assert calls["cycles"] == 1


def test_sleep_is_interruptible_between_short_steps() -> None:
    window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=100, y=200, width=800, height=400),
    )
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    bot = AutoFishingBot(
        BotConfig(),
        window_manager=FakeWindowManager(window),
        capture=FakeCapture(),
        matcher=AlwaysMatcher({}),
        input_controller=FakeInput(),
        sleep=fake_sleep,
        should_stop=lambda: len(slept) >= 2,
    )

    with pytest.raises(StopRequested):
        bot._sleep(1.0)

    assert slept == [0.1, 0.1]
