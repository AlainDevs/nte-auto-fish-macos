from __future__ import annotations

import sys
import types


class FakeVariable:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class FakeWidget:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def grid(self, *args, **kwargs) -> None:
        pass

    def grid_columnconfigure(self, *args, **kwargs) -> None:
        pass

    def grid_rowconfigure(self, *args, **kwargs) -> None:
        pass

    def configure(self, *args, **kwargs) -> None:
        pass

    def insert(self, *args, **kwargs) -> None:
        pass

    def see(self, *args, **kwargs) -> None:
        pass

    def delete(self, *args, **kwargs) -> None:
        pass


class FakeRoot(FakeWidget):
    def title(self, *args, **kwargs) -> None:
        pass

    def geometry(self, *args, **kwargs) -> None:
        pass

    def minsize(self, *args, **kwargs) -> None:
        pass

    def after(self, *args, **kwargs) -> None:
        pass

    def protocol(self, *args, **kwargs) -> None:
        pass

    def mainloop(self) -> None:
        pass

    def destroy(self) -> None:
        pass


fake_ctk = types.SimpleNamespace(
    CTk=FakeRoot,
    CTkFrame=FakeWidget,
    CTkLabel=FakeWidget,
    CTkButton=FakeWidget,
    CTkEntry=FakeWidget,
    CTkOptionMenu=FakeWidget,
    CTkCheckBox=FakeWidget,
    CTkTextbox=FakeWidget,
    CTkFont=lambda *args, **kwargs: (args, kwargs),
    StringVar=FakeVariable,
    BooleanVar=FakeVariable,
    set_appearance_mode=lambda *args, **kwargs: None,
    set_default_color_theme=lambda *args, **kwargs: None,
)

sys.modules.setdefault("customtkinter", fake_ctk)

from nte_fisher.bot import SessionStats
from nte_fisher.gui import NTEFisherApp
from nte_fisher.window_manager import WindowBounds, WindowInfo


def test_gui_build_config_uses_selected_window_and_simplified_input_modes() -> None:
    app = NTEFisherApp.__new__(NTEFisherApp)
    app.query_var = FakeVariable("NTE")
    app.threshold_var = FakeVariable("0.75")
    app.scan_interval_var = FakeVariable("0.09")
    app.catch_scan_interval_var = FakeVariable("0.04")
    app.map_key_var = FakeVariable("m")
    app.dry_run_var = FakeVariable(False)
    app.selected_window = WindowInfo(
        owner_name="NTE",
        window_name="Main",
        pid=1234,
        window_id=5678,
        bounds=WindowBounds(x=0, y=30, width=1352, height=848),
    )

    config = app.build_config()

    assert config.pid == 1234
    assert config.window_id == 5678
    assert config.threshold == 0.75
    assert config.scan_interval == 0.09
    assert config.catch_scan_interval == 0.04
    assert config.max_cycles is None
    assert config.map_key_retries == 1
    assert config.input_mode == "pid"
    assert config.click_input_mode == "hid"
    assert config.activate_before_input is False
    assert config.activate_before_click is True


def test_gui_prefers_non_gui_windows_when_query_matches_itself() -> None:
    app = NTEFisherApp.__new__(NTEFisherApp)
    current_pid = 99999
    gui_window = WindowInfo(
        owner_name="NTE Auto Fisher",
        window_name="NTE Auto Fisher",
        pid=current_pid,
        window_id=10,
        bounds=WindowBounds(x=0, y=0, width=900, height=700),
    )
    game_window = WindowInfo(
        owner_name="NTE",
        window_name="NTE",
        pid=2,
        window_id=20,
        bounds=WindowBounds(x=0, y=0, width=1352, height=848),
    )

    import nte_fisher.gui as gui

    original_getpid = gui.os.getpid
    gui.os.getpid = lambda: current_pid
    try:
        assert app._pick_best_window([gui_window, game_window]) == [game_window]
        assert app._pick_best_window([gui_window]) == []
    finally:
        gui.os.getpid = original_getpid


def test_gui_applies_session_stats_text() -> None:
    app = NTEFisherApp.__new__(NTEFisherApp)
    app.session_stats_var = FakeVariable()

    app._apply_session_stats(SessionStats(loops_completed=5, successful_loops=3, failed_fish_gone_loops=2))

    assert app.session_stats_var.get() == "Session: loops=5 success=3 failed/fish gone=2"
