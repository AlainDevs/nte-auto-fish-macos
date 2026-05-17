"""CustomTkinter desktop app for the NTE auto-fishing bot."""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
from dataclasses import dataclass
from typing import Callable

import customtkinter as ctk

from .bot import AutoFishingBot, BotConfig, SessionStats, StopRequested, configure_logging
from .input_control import InputController
from .window_manager import WindowInfo, WindowManager, format_window


LOGGER = logging.getLogger("nte_fisher.gui")


class QueueLogHandler(logging.Handler):
    """Logging handler that forwards formatted log records into a queue."""

    def __init__(self, log_queue: queue.Queue[str]) -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            try:
                self.log_queue.put_nowait(message)
            except queue.Full:
                try:
                    self.log_queue.get_nowait()
                except queue.Empty:
                    pass
                self.log_queue.put_nowait(message)
        except Exception:  # pragma: no cover - logging safety net
            self.handleError(record)


@dataclass(frozen=True)
class WindowChoice:
    """Display text plus WindowInfo for a GUI dropdown option."""

    label: str
    window: WindowInfo


class NTEFisherApp(ctk.CTk):
    """Small GUI wrapper around the simplified auto-fishing state machine."""

    def __init__(self) -> None:
        super().__init__()
        self.title("NTE Auto Fisher")
        self.geometry("920x680")
        self.minsize(780, 560)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.window_manager = WindowManager()
        self.max_log_lines = 1000
        self._log_line_count = 0
        self.log_queue: queue.Queue[str] = queue.Queue(maxsize=self.max_log_lines * 2)
        self.window_choices: list[WindowChoice] = []
        self.selected_window: WindowInfo | None = None
        self.bot_thread: threading.Thread | None = None
        self.stop_event = threading.Event()

        self.query_var = ctk.StringVar(value="NTE")
        self.window_var = ctk.StringVar(value="No window selected")
        self.status_var = ctk.StringVar(value="Idle")
        self.session_stats_var = ctk.StringVar(value=self._format_session_stats(SessionStats()))
        self.threshold_var = ctk.StringVar(value="0.70")
        self.scan_interval_var = ctk.StringVar(value="0.08")
        self.catch_scan_interval_var = ctk.StringVar(value="0.01")
        self.map_key_var = ctk.StringVar(value="m")
        self.dry_run_var = ctk.BooleanVar(value=False)

        self._build_ui()
        self._install_logging()
        self.after(100, self._drain_logs)
        self.after(250, self._watch_bot_thread)
        self.after(500, self.request_permissions)
        self.refresh_windows()
        self._log_process_identity()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header, text="NTE Auto Fisher", font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 2), sticky="w"
        )
        ctk.CTkLabel(
            header,
            text="Keyboard uses PID background events; mouse clicks use foreground HID activation once per init_start.",
            anchor="w",
        ).grid(row=1, column=0, columnspan=3, padx=12, pady=(0, 12), sticky="ew")

        ctk.CTkLabel(header, textvariable=self.session_stats_var, anchor="w").grid(
            row=2, column=0, columnspan=3, padx=12, pady=(0, 12), sticky="ew"
        )

        self.status_label = ctk.CTkLabel(header, textvariable=self.status_var, font=ctk.CTkFont(weight="bold"))
        self.status_label.grid(row=0, column=2, padx=12, pady=12, sticky="e")

        target_frame = ctk.CTkFrame(self)
        target_frame.grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        target_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(target_frame, text="Window query").grid(row=0, column=0, padx=12, pady=12, sticky="w")
        ctk.CTkEntry(target_frame, textvariable=self.query_var, width=140).grid(row=0, column=1, padx=8, pady=12, sticky="w")
        ctk.CTkButton(target_frame, text="Refresh Windows", command=self.refresh_windows).grid(
            row=0, column=2, padx=8, pady=12
        )
        ctk.CTkButton(target_frame, text="Request Permissions", command=self.request_permissions).grid(
            row=0, column=3, padx=8, pady=12
        )

        ctk.CTkLabel(target_frame, text="Target window").grid(row=1, column=0, padx=12, pady=12, sticky="w")
        self.window_menu = ctk.CTkOptionMenu(
            target_frame,
            variable=self.window_var,
            values=["No window selected"],
            command=self._select_window_by_label,
            width=520,
        )
        self.window_menu.grid(row=1, column=1, columnspan=3, padx=8, pady=12, sticky="ew")

        settings = ctk.CTkFrame(self)
        settings.grid(row=2, column=0, padx=16, pady=8, sticky="ew")
        for column in range(8):
            settings.grid_columnconfigure(column, weight=1)

        self._labeled_entry(settings, "Threshold", self.threshold_var, row=0, column=0)
        self._labeled_entry(settings, "Scan interval", self.scan_interval_var, row=0, column=2)
        self._labeled_entry(settings, "Catch scan", self.catch_scan_interval_var, row=0, column=4)
        self._labeled_entry(settings, "Map key", self.map_key_var, row=0, column=6)
        ctk.CTkCheckBox(settings, text="Dry run", variable=self.dry_run_var).grid(
            row=1, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="w"
        )

        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=3, column=0, padx=16, pady=8, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(log_frame, text="Logs", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w"
        )
        self.log_text = ctk.CTkTextbox(log_frame, wrap="word")
        self.log_text.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.log_text.configure(state="disabled")

        controls = ctk.CTkFrame(self)
        controls.grid(row=4, column=0, padx=16, pady=(8, 16), sticky="ew")
        controls.grid_columnconfigure(2, weight=1)
        self.start_button = ctk.CTkButton(controls, text="Start Unlimited", command=self.start_bot)
        self.start_button.grid(row=0, column=0, padx=12, pady=12)
        self.stop_button = ctk.CTkButton(controls, text="Stop", command=self.stop_bot, state="disabled", fg_color="#8a1f1f")
        self.stop_button.grid(row=0, column=1, padx=12, pady=12)
        ctk.CTkButton(controls, text="Clear Logs", command=self.clear_logs).grid(row=0, column=3, padx=12, pady=12)

    def _labeled_entry(
        self,
        parent: ctk.CTkFrame,
        label: str,
        variable: ctk.StringVar,
        row: int,
        column: int,
    ) -> None:
        ctk.CTkLabel(parent, text=label).grid(row=row, column=column, padx=(12, 4), pady=12, sticky="w")
        ctk.CTkEntry(parent, textvariable=variable, width=90).grid(
            row=row, column=column + 1, padx=(0, 12), pady=12, sticky="w"
        )

    def _install_logging(self) -> None:
        configure_logging(verbose=False)
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logging.getLogger().addHandler(handler)

    def _log_to_widget(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self._log_line_count += 1
        while self._log_line_count > self.max_log_lines:
            self.log_text.delete("1.0", "2.0")
            self._log_line_count -= 1
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain_logs(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._log_to_widget(message)
        self.after(100, self._drain_logs)

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self._log_line_count = 0
        self.log_text.configure(state="disabled")

    def _format_session_stats(self, stats: SessionStats) -> str:
        return (
            "Session: "
            f"loops={stats.loops_completed} "
            f"success={stats.successful_loops} "
            f"failed/fish gone={stats.failed_fish_gone_loops}"
        )

    def _apply_session_stats(self, stats: SessionStats) -> None:
        self.session_stats_var.set(self._format_session_stats(stats))

    def _schedule_session_stats_update(self, stats: SessionStats) -> None:
        self.after(0, lambda stats=stats: self._apply_session_stats(stats))

    def _log_process_identity(self) -> None:
        LOGGER.info("App process pid=%s executable=%s", os.getpid(), sys.executable)

    def request_permissions(self) -> None:
        trusted = InputController.is_accessibility_trusted(prompt=True)
        LOGGER.info("Accessibility trusted=%s", trusted)
        if not trusted:
            LOGGER.warning(
                "Accessibility permission is not trusted. Enable NTE Auto Fisher in System Settings, then restart the app."
            )
            LOGGER.warning(
                "If NTE Auto Fisher is already enabled but this still says False, macOS may have a stale permission entry. "
                "Remove NTE Auto Fisher with the minus button, press Request Permissions again, enable it, then quit and reopen."
            )
            InputController.open_accessibility_settings()

        LOGGER.info(
            "If capture is blank or templates do not detect, enable Screen Recording for NTE Auto Fisher."
        )

    def refresh_windows(self) -> None:
        query = self.query_var.get().strip() or None
        try:
            windows = self._pick_best_window(self.window_manager.list_windows(query=query))
        except Exception as exc:
            LOGGER.error("Failed to list windows: %s", exc)
            self.status_var.set("Window refresh failed")
            return

        self.window_choices = [WindowChoice(label=self._window_label(window), window=window) for window in windows]
        labels = [choice.label for choice in self.window_choices] or ["No matching windows"]
        self.window_menu.configure(values=labels)
        self.window_var.set(labels[0])
        self._select_window_by_label(labels[0])
        LOGGER.info("Found %d matching window(s) for query=%r", len(windows), query)

    def _window_label(self, window: WindowInfo) -> str:
        return (
            f"{window.display_name} | pid={window.pid} | window={window.window_id} | "
            f"{window.bounds.width:.0f}x{window.bounds.height:.0f}"
        )

    def _select_window_by_label(self, label: str) -> None:
        self.selected_window = None
        for choice in self.window_choices:
            if choice.label == label:
                self.selected_window = choice.window
                self.status_var.set("Ready")
                LOGGER.info("Selected target window: %s", format_window(choice.window))
                return
        self.status_var.set("No target window")

    def _pick_best_window(self, windows: list[WindowInfo]) -> list[WindowInfo]:
        """Prefer game windows over the GUI itself when the query is broad."""
        current_pid = os.getpid()
        return [
            window
            for window in windows
            if window.pid != current_pid and window.owner_name != "NTE Auto Fisher"
        ]

    def _parse_float(self, variable: ctk.StringVar, name: str) -> float:
        try:
            value = float(variable.get())
        except ValueError as exc:
            raise ValueError(f"{name} must be a number") from exc
        if value < 0:
            raise ValueError(f"{name} must be zero or greater")
        return value

    def build_config(self) -> BotConfig:
        selected = self.selected_window
        if selected is None:
            raise LookupError("Select an NTE window before starting")

        map_key = self.map_key_var.get().strip().lower() or "m"
        return BotConfig(
            query=self.query_var.get().strip() or "NTE",
            pid=selected.pid,
            window_id=selected.window_id,
            threshold=self._parse_float(self.threshold_var, "Threshold"),
            scan_interval=self._parse_float(self.scan_interval_var, "Scan interval"),
            catch_scan_interval=self._parse_float(self.catch_scan_interval_var, "Catch scan interval"),
            map_key=map_key,
            max_cycles=None,
            dry_run=bool(self.dry_run_var.get()),
            input_mode="pid",
            click_input_mode="hid",
            activate_before_input=False,
            activate_before_click=True,
        )

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        self.status_var.set("Running" if running else "Idle")

    def start_bot(self) -> None:
        if self.bot_thread is not None and self.bot_thread.is_alive():
            LOGGER.warning("Bot is already running")
            return
        try:
            config = self.build_config()
        except Exception as exc:
            LOGGER.error("Cannot start bot: %s", exc)
            self.status_var.set("Start failed")
            return

        if not config.dry_run:
            trusted = InputController.is_accessibility_trusted(prompt=True)
            LOGGER.info("Accessibility trusted=%s", trusted)
            if not trusted:
                LOGGER.warning("Accessibility permission is not trusted; opening macOS permission settings")
                LOGGER.warning(
                    "If the checkbox is already enabled, remove NTE Auto Fisher from Accessibility with the minus button, "
                    "press Request Permissions again, enable it, then quit and reopen."
                )
                InputController.open_accessibility_settings()
                self.status_var.set("Needs Accessibility")
                return

        self.stop_event.clear()
        self._apply_session_stats(SessionStats())
        self._set_running(True)
        self.bot_thread = threading.Thread(target=self._run_bot, args=(config,), daemon=True)
        self.bot_thread.start()

    def _run_bot(self, config: BotConfig) -> None:
        try:
            LOGGER.info("Starting unlimited bot run with config=%s", config)
            AutoFishingBot(
                config,
                should_stop=self.stop_event.is_set,
                stats_callback=self._schedule_session_stats_update,
            ).run()
        except StopRequested:
            LOGGER.info("Bot stopped by user")
        except Exception as exc:
            LOGGER.exception("Bot stopped after error: %s", exc)
        finally:
            self.after(0, lambda: self._set_running(False))

    def stop_bot(self) -> None:
        if self.bot_thread is None or not self.bot_thread.is_alive():
            self._set_running(False)
            return
        LOGGER.info("Stop requested")
        self.status_var.set("Stopping")
        self.stop_event.set()

    def _watch_bot_thread(self) -> None:
        if self.bot_thread is not None and not self.bot_thread.is_alive():
            self.bot_thread = None
            if self.status_var.get() in {"Running", "Stopping"}:
                self._set_running(False)
        self.after(250, self._watch_bot_thread)

    def on_close(self) -> None:
        self.stop_event.set()
        self.destroy()


def main(factory: Callable[[], NTEFisherApp] = NTEFisherApp) -> int:
    app = factory()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
