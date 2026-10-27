import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from studio.ui import App


class LayoutTests(unittest.TestCase):
    def test_multiple_glasses_can_be_saved_and_passed_to_cases(self):
        with patch.object(App, 'load_state', return_value={}), patch.object(App, 'save_state'), \
             patch.object(App, 'refresh_devices'), patch.object(App, 'poll'):
            app = App(Path(__file__).resolve().parents[1])
            try:
                app.phone.set('phone')
                app.devices_by_label['phone'] = SimpleNamespace(serial='PHONE')
                app.glasses_name.set('DPVR G1_7BAF')
                app.extra_product.set('G1/G3/G6')
                app.change_extra_product()
                app.extra_name.set('DPVR G1_13E6')
                app.save_extra_glasses()
                self.assertEqual(app.context()['glasses_inventory'], [
                    {'product': 'G系列', 'model': 'G1', 'glasses_name': 'DPVR G1_7BAF'},
                    {'product': 'G系列', 'model': 'G1', 'glasses_name': 'DPVR G1_13E6'}])
                app.extra_view.selection_set('0')
                app.select_extra_glasses()
                app.extra_name.set('DPVR G1_2831')
                app.save_extra_glasses()
                self.assertEqual(app.extra_glasses[0]['glasses_name'], 'DPVR G1_2831')
                app.extra_view.selection_set('0')
                app.remove_extra_glasses()
                self.assertEqual(app.extra_glasses, [])
            finally:
                app.destroy()

    def test_simple_flow_and_live_results(self):
        with patch.object(App, 'refresh_devices'), patch.object(App, 'poll'):
            app = App(Path(__file__).resolve().parents[1])
        try:
            app.update()
            self.assertFalse(app.advanced.winfo_manager())
            if not app.target_queue:
                self.assertFalse(app.targets_panel.winfo_manager())
            app.toggle_advanced()
            self.assertTrue(app.advanced.winfo_manager())
            app.toggle_advanced()
            self.assertFalse(app.advanced.winfo_manager())
            app.total, app.completed = 2, 1
            app.show_case_result({'sheet': 'G05_空间', 'id': 'Space_006', 'status': 'PASS', 'detail': ''})
            app.show_case_result({'sheet': 'G05_空间', 'id': 'Space_007', 'status': 'FAIL',
                                  'detail': '暂停后视频仍在播放。'})
            rows = app.result_view.get_children()
            self.assertEqual(app.result_view.set(rows[0], 'status'), 'Passed')
            self.assertEqual(app.result_view.set(rows[1], 'detail'), '暂停后视频仍在播放。')
            self.assertIn('暂停后视频仍在播放', app.log.get('1.0', 'end'))
        finally:
            app.destroy()

    def test_small_windows_keep_all_controls_reachable(self):
        with patch.object(App, 'refresh_devices'), patch.object(App, 'poll'):
            app = App(Path(__file__).resolve().parents[1])
        try:
            app.update()
            self.assertLessEqual(app.winfo_height(), app.winfo_screenheight() - 120)
            for size in ('1024x600', '800x450', '640x400', '1180x780'):
                with self.subTest(size=size):
                    app.geometry(size)
                    app.update()
                    canvas = app.canvas
                    content = app.content
                    self.assertGreaterEqual(content.winfo_height(), content.winfo_reqheight())
                    self.assertGreaterEqual(content.winfo_width(), content.winfo_reqwidth())
                    canvas.yview_moveto(1)
                    canvas.xview_moveto(0)
                    app.update()
                    button_y = app.start_button.winfo_rooty() - canvas.winfo_rooty()
                    self.assertGreaterEqual(button_y, 0)
                    self.assertLess(button_y + app.start_button.winfo_height(), canvas.winfo_height())
                    canvas.xview_moveto(1)
                    app.update()
                    self.assertAlmostEqual(canvas.xview()[1], 1.0, places=2)
                    self.assertAlmostEqual(canvas.yview()[1], 1.0, places=2)
                    canvas.yview_moveto(0)
                    app.update()
                    self.assertEqual(canvas.yview()[0], 0.0)
        finally:
            app.destroy()


if __name__ == '__main__':
    unittest.main()
