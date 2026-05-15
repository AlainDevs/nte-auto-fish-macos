"""Command-line interface for NTE auto-fishing tools."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .bot import AutoFishingBot, BotConfig, configure_logging
from .capture import WindowCapture
from .input_control import InputController
from .vision import MatchMethod, TemplateMatcher
from .window_manager import WindowManager, format_window


LOGGER = logging.getLogger("nte_fisher.cli")


def _add_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", default="NTE", help="Window owner/title query, default: NTE")
    parser.add_argument("--pid", type=int, default=None, help="Optional target process ID")
    parser.add_argument("--window-id", type=int, default=None, help="Optional target Quartz window ID")


def _find_window(args: argparse.Namespace):
    manager = WindowManager()
    return manager.find_window(query=args.query, pid=args.pid, window_id=args.window_id)


def cmd_list_windows(args: argparse.Namespace) -> int:
    manager = WindowManager()
    windows = manager.list_windows(query=args.query, pid=args.pid)
    if args.window_id is not None:
        windows = [window for window in windows if window.window_id == args.window_id]

    if not windows:
        LOGGER.error("No windows matched query=%r pid=%r window_id=%r", args.query, args.pid, args.window_id)
        return 1

    for index, window in enumerate(windows, start=1):
        LOGGER.info("[%d] %s", index, format_window(window))
    return 0


def cmd_capture_test(args: argparse.Namespace) -> int:
    window = _find_window(args)
    LOGGER.info("Capture target: %s", format_window(window))
    output = WindowCapture().save_capture(window, args.out)
    LOGGER.info("Saved capture to %s", output)
    return 0


def _template_name_from_path(path: str | Path) -> str:
    return Path(path).stem


def _methods_from_args(args: argparse.Namespace) -> dict[str, MatchMethod] | None:
    method = getattr(args, "match_method", "ccoeff")
    if method == "auto":
        return {
            "start_fishing": "sqdiff",
            "catch_now": "sqdiff",
            "return": "sqdiff",
            "failed_catch": "sqdiff",
            "init_start": "sqdiff",
        }
    return None if method == "ccoeff" else {}


def cmd_detect_test(args: argparse.Namespace) -> int:
    window = _find_window(args)
    LOGGER.info("Detection target: %s", format_window(window))
    image = WindowCapture().capture(window)
    LOGGER.info("Captured image size=%sx%s", image.width, image.height)

    if args.all:
        matcher = TemplateMatcher(threshold=args.threshold, methods=_methods_from_args(args))
        for name in matcher.templates:
            score = matcher.score(image, name)
            if score is None:
                LOGGER.info("template=%s is larger than capture; no score", name)
                continue
            LOGGER.info(
                "template=%s confidence=%.4f threshold=%.2f matched=%s method=%s top_left=%s center=%s size=%s",
                name,
                score.confidence,
                args.threshold,
                score.confidence >= args.threshold,
                score.method,
                score.top_left,
                score.center,
                score.size,
            )
        return 0

    if not args.template:
        raise SystemExit("detect-test requires --template or --all")

    name = _template_name_from_path(args.template)
    method = args.match_method
    methods = None if method in {"auto", "ccoeff"} else {name: method}
    if method == "auto":
        methods = {name: "sqdiff"}
    matcher = TemplateMatcher({name: args.template}, threshold=args.threshold, methods=methods)
    score = matcher.score(image, name)
    if score is None:
        LOGGER.error("template=%s path=%s is larger than capture", name, args.template)
        return 2

    LOGGER.info(
        "template=%s path=%s confidence=%.4f threshold=%.2f matched=%s method=%s top_left=%s center=%s size=%s",
        name,
        args.template,
        score.confidence,
        args.threshold,
        score.confidence >= args.threshold,
        score.method,
        score.top_left,
        score.center,
        score.size,
    )
    return 0 if score.confidence >= args.threshold else 2


def cmd_input_test(args: argparse.Namespace) -> int:
    if not args.yes:
        LOGGER.error("Refusing to send input without --yes. Re-run with --yes after confirming target details.")
        return 2
    window = _find_window(args)
    LOGGER.info("Input target: %s", format_window(window))
    if args.input_mode in {"hid", "both"} and not args.activate_before_input and not args.dry_run:
        LOGGER.warning("input_mode=%s posts to the active session. Use --activate-before-input to target NTE first.", args.input_mode)
    controller = InputController(
        dry_run=args.dry_run,
        mode=args.input_mode,
        event_source_state=args.event_source_state,
        activate_before_input=args.activate_before_input,
        activation_delay=args.activation_delay,
    )
    LOGGER.info("Accessibility trusted=%s", controller.is_accessibility_trusted())
    action = controller.press_key(window.pid, args.key, hold_seconds=args.hold_seconds)
    LOGGER.info(
        "Sent action=%s pid=%s detail=%s dry_run=%s",
        action.action_type,
        action.pid,
        action.detail,
        args.dry_run,
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.dry_run:
        trusted = InputController.is_accessibility_trusted()
        LOGGER.info("Accessibility trusted=%s", trusted)
        if not trusted and not args.ignore_accessibility_check:
            LOGGER.error("Accessibility is not trusted. Grant Accessibility permission or use --ignore-accessibility-check.")
            return 2

    config = BotConfig(
        query=args.query,
        pid=args.pid,
        window_id=args.window_id,
        threshold=args.threshold,
        match_method=args.match_method,
        scan_interval=args.scan_interval,
        catch_scan_interval=args.catch_scan_interval,
        post_start_delay=args.post_start_delay,
        catch_to_map_delay=args.catch_to_map_delay,
        time_to_open_map_scan_interval=args.time_to_open_map_scan_interval,
        map_key=args.map_key,
        map_key_retries=args.map_key_retries,
        map_key_retry_delay=args.map_key_retry_delay,
        esc_delay=args.esc_delay,
        recast_delay=args.recast_delay,
        key_hold_seconds=args.key_hold_seconds,
        click_hold_seconds=args.click_hold_seconds,
        input_mode=args.input_mode,
        click_input_mode=None if args.click_input_mode == "same" else args.click_input_mode,
        event_source_state=args.event_source_state,
        activate_before_input=args.activate_before_input,
        activate_before_click=True if args.activate_before_click else None,
        activation_delay=args.activation_delay,
        start_at=args.start_at,
        max_cycles=args.max_cycles,
        dry_run=args.dry_run,
        log_wait_every=args.log_wait_every,
        wait_timeout=args.wait_timeout,
        confirm_actions=not args.no_confirm_actions,
        start_absence_confirm_timeout=args.start_absence_confirm_timeout,
        action_confirm_timeout=args.action_confirm_timeout,
        absence_confirm_duration=args.absence_confirm_duration,
        init_click_confirm_timeout=args.init_click_confirm_timeout,
        init_click_retries=args.init_click_retries,
        init_click_retry_delay=args.init_click_retry_delay,
        click_foreground_fallback=not args.no_click_foreground_fallback,
    )
    LOGGER.info("Starting bot with config=%s", config)
    AutoFishingBot(config).run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NTE macOS background auto-fishing bot")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--log-file", default=None, help="Optional path for duplicate detailed logs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-windows", help="List matching macOS windows")
    _add_target_args(list_parser)
    list_parser.set_defaults(func=cmd_list_windows)

    capture_parser = subparsers.add_parser("capture-test", help="Save one background window capture")
    _add_target_args(capture_parser)
    capture_parser.add_argument("--out", default="artifacts/nte_capture.png", help="Output PNG path")
    capture_parser.set_defaults(func=cmd_capture_test)

    detect_parser = subparsers.add_parser("detect-test", help="Capture once and test template matching")
    _add_target_args(detect_parser)
    detect_parser.add_argument("--template", default=None, help="Template image path")
    detect_parser.add_argument("--all", action="store_true", help="Test all default templates")
    detect_parser.add_argument("--threshold", type=float, default=0.80, help="Match threshold")
    detect_parser.add_argument("--match-method", choices=["ccoeff", "sqdiff", "auto"], default="ccoeff", help="Template matching method")
    detect_parser.set_defaults(func=cmd_detect_test)

    input_parser = subparsers.add_parser("input-test", help="Send one targeted key press")
    _add_target_args(input_parser)
    input_parser.add_argument("--key", choices=["f", "m", "tab", "b", "c", "j", "k", "l", "i", "o", "p", "u", "n", "f1", "f2", "f3", "f4", "esc"], required=True, help="Key to press")
    input_parser.add_argument("--input-mode", choices=["pid", "hid", "both"], default="pid", help="Input posting mode")
    input_parser.add_argument("--event-source-state", choices=["hid", "private", "combined", "none"], default="hid", help="Quartz event source state")
    input_parser.add_argument("--hold-seconds", type=float, default=0.100, help="Key hold duration for input-test")
    input_parser.add_argument("--activate-before-input", action="store_true", help="Bring NTE to front before sending input")
    input_parser.add_argument("--activation-delay", type=float, default=0.15, help="Delay after foreground activation")
    input_parser.add_argument("--yes", action="store_true", help="Confirm sending input")
    input_parser.add_argument("--dry-run", action="store_true", help="Log only; do not send input")
    input_parser.set_defaults(func=cmd_input_test)

    run_parser = subparsers.add_parser("run", help="Run the full fishing state machine")
    _add_target_args(run_parser)
    run_parser.add_argument("--threshold", type=float, default=0.80, help="OpenCV match confidence threshold")
    run_parser.add_argument("--match-method", choices=["ccoeff", "sqdiff"], default="ccoeff", help="Template matching method for the bot")
    run_parser.add_argument("--scan-interval", type=float, default=0.08, help="Normal scan interval in seconds")
    run_parser.add_argument("--catch-scan-interval", type=float, default=0.03, help="Fast scan interval for catch_now")
    run_parser.add_argument("--post-start-delay", type=float, default=0.300, help="Settle delay after first F before catch scanning")
    run_parser.add_argument("--catch-to-map-delay", type=float, default=0.250, help="Maximum seconds to wait for time_to_open_map before pressing the map key anyway")
    run_parser.add_argument("--time-to-open-map-scan-interval", type=float, default=0.03, help="Fast scan interval for time_to_open_map after catch F")
    run_parser.add_argument("--map-key", choices=["m", "tab", "b", "c", "j", "k", "l", "i", "o", "p", "u", "n", "f1", "f2", "f3", "f4", "esc"], default="m", help="Menu key to press after catching")
    run_parser.add_argument("--map-key-retries", type=int, default=3, help="Number of M presses after catch")
    run_parser.add_argument("--map-key-retry-delay", type=float, default=0.250, help="Delay between repeated M presses")
    run_parser.add_argument("--esc-delay", type=float, default=0.250, help="Delay between ESC presses")
    run_parser.add_argument("--recast-delay", type=float, default=1.000, help="Delay before recast F")
    run_parser.add_argument("--key-hold-seconds", type=float, default=0.100, help="Keyboard down/up hold duration")
    run_parser.add_argument("--click-hold-seconds", type=float, default=0.035, help="Mouse down/up hold duration")
    run_parser.add_argument("--input-mode", choices=["pid", "hid", "both"], default="pid", help="Input mode: pid=background, hid=active session, both=try both")
    run_parser.add_argument("--click-input-mode", choices=["same", "pid", "hid", "both"], default="same", help="Mouse click input mode. same inherits --input-mode")
    run_parser.add_argument("--event-source-state", choices=["hid", "private", "combined", "none"], default="hid", help="Quartz event source state for generated events")
    run_parser.add_argument("--activate-before-input", action="store_true", help="Bring NTE to front before every input action")
    run_parser.add_argument("--activate-before-click", action="store_true", help="Bring NTE to front before mouse clicks only")
    run_parser.add_argument("--activation-delay", type=float, default=0.15, help="Delay after foreground activation")
    run_parser.add_argument("--start-at", choices=["start", "catch", "return", "recast", "init"], default="start", help="Start the first cycle from a specific phase")
    run_parser.add_argument("--max-cycles", type=int, default=None, help="Optional maximum fishing cycles")
    run_parser.add_argument("--dry-run", action="store_true", help="Detect and log only; do not send input")
    run_parser.add_argument("--ignore-accessibility-check", action="store_true", help="Run even if Accessibility trust check fails")
    run_parser.add_argument("--log-wait-every", type=float, default=2.0, help="Log waiting status every N seconds")
    run_parser.add_argument("--wait-timeout", type=float, default=None, help="Optional per-template wait timeout in seconds")
    run_parser.add_argument("--no-confirm-actions", action="store_true", help="Skip post-input visual absence confirmations")
    run_parser.add_argument("--start-absence-confirm-timeout", type=float, default=8.0, help="Timeout for confirming start_fishing disappears")
    run_parser.add_argument("--action-confirm-timeout", type=float, default=2.0, help="Timeout for post-input visual confirmations")
    run_parser.add_argument("--absence-confirm-duration", type=float, default=0.20, help="Stable absent duration needed to confirm UI changed")
    run_parser.add_argument("--init-click-confirm-timeout", type=float, default=2.0, help="Seconds to wait for start_fishing after init_start click before retry/failure")
    run_parser.add_argument("--init-click-retries", type=int, default=2, help="Total init_start click attempts before failing")
    run_parser.add_argument("--init-click-retry-delay", type=float, default=0.250, help="Delay between init_start click attempts")
    run_parser.add_argument("--no-click-foreground-fallback", action="store_true", help="Disable automatic foreground HID retry when the first init_start click is not confirmed")
    run_parser.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose, log_file=args.log_file)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user")
        return 130
    except (LookupError, RuntimeError, TimeoutError, FileNotFoundError, KeyError) as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
