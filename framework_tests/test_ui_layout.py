import unittest
from pathlib import Path
from unittest.mock import patch

from studio.ui import App


class LayoutTests(unittest.TestCase):
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
