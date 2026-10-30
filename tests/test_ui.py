import asyncio
from pathlib import Path
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


class DemoUITests(unittest.TestCase):
    def test_demo_scenarios(self):
        # Avoid Windows socketpair creation in AppTest's synchronous event loop.
        with patch("asyncio.new_event_loop", side_effect=asyncio.BaseEventLoop):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"),
                                    default_timeout=30).run()
            self.assertFalse(app.exception)
            for choice, outcome in [("Customer order totals", "success"),
                                    ("Missing schema", "warning"), ("Unsafe request", "error")]:
                app.selectbox[0].select(choice).run()
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(len(getattr(app, outcome)), 1)
