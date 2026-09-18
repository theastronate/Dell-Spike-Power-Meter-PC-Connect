import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dpm_ui import PowerMeterApp


class SettingsTests(unittest.TestCase):
    def test_layout_scaling_leaves_figure_size_to_tk_canvas(self):
        app = Mock(_last_scale=0, _layout_base_width=920,
                   _quadrant_refs=[], _scalable_labels=[], _scalable_pack=[])
        app.winfo_width.return_value = 920
        app.winfo_height.return_value = 980
        app._get_window_scaling.return_value = 1
        PowerMeterApp._apply_scale(app)
        app.fig.set_size_inches.assert_not_called()
        app.canvas.draw_idle.assert_called_once_with()

    def test_legacy_and_invalid_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Mock(_settings_path=Path(directory) / "dpm_ui.ini")
            app._settings_path.write_text(
                "[window]\nwidth=538\nheight=641\nx=invalid\n"
                "[connection]\nlast_port=COM7\nautoconnect=True\n"
            )
            settings = PowerMeterApp._load_window_settings(app)
            self.assertEqual((settings["width"], settings["height"]), (538, 641))
            self.assertIsNone(settings["x"])
            self.assertIsNone(settings["y"])
            self.assertEqual(settings["last_port"], "COM7")
            self.assertTrue(settings["autoconnect"])

    def test_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Mock(_settings_path=Path(directory) / "dpm_ui.ini",
                       _normal_size=(538, 641), _normal_position=(-1000, 80),
                       _last_port="COM7")
            app.state.return_value = "zoomed"
            app.autoconnect_var.get.return_value = True
            PowerMeterApp._save_settings(app)
            settings = PowerMeterApp._load_window_settings(app)
            self.assertEqual((settings["x"], settings["y"]), (-1000, 80))
            self.assertTrue(settings["maximized"])
            self.assertTrue(settings["autoconnect"])
            self.assertEqual(settings["last_port"], "COM7")

    def test_position_recovery_and_negative_monitor_coordinates(self):
        for position, expected in [((-1000, 80), (-1000, 80)),
                                   ((5000, 80), (20, 20)),
                                   ((1800, 80), (20, 20)),
                                   ((None, None), (20, 20))]:
            with self.subTest(position=position):
                app = Mock(_normal_size=(538, 641), _w=".")
                app._monitor_work_areas.return_value = [
                    (0, 0, 1920, 1040), (-1920, 0, 0, 1040)]
                app._window_rect.return_value = (0, 0, 554, 680)
                app._get_window_scaling.return_value = 1
                app.winfo_width.return_value = 538
                app.winfo_height.return_value = 641
                with patch("dpm_ui.sys.platform", "linux"):
                    PowerMeterApp._restore_position(app, *position)
                self.assertEqual(app._normal_position, expected)

    def test_oversized_window_is_reduced_to_work_area(self):
        app = Mock(_normal_size=(920, 980), _w=".")
        app._monitor_work_areas.return_value = [(0, 0, 1280, 720)]
        app._window_rect.return_value = (0, 0, 936, 1019)
        app._get_window_scaling.return_value = 1
        app.winfo_width.return_value = 920
        app.winfo_height.return_value = 980
        with patch("dpm_ui.sys.platform", "linux"):
            PowerMeterApp._restore_position(app, 20, 20)
        self.assertEqual(app._normal_size, (920, 641))

    def test_autoconnect_only_when_enabled_and_disconnected(self):
        for enabled, running, calls in [(True, False, 1), (False, False, 0),
                                         (True, True, 0)]:
            app = Mock(_last_port="COM7", running=running)
            app.autoconnect_var.get.return_value = enabled
            PowerMeterApp._autoconnect(app)
            self.assertEqual(app.toggle_connection.call_count, calls)
            if calls:
                app.port_var.set.assert_called_once_with("COM7")


if __name__ == "__main__":
    unittest.main()
