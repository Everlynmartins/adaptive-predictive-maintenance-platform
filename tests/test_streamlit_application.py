"""Smoke test for the thin Streamlit presentation layer."""

from pathlib import Path
import os
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import streamlit as st
from predictive_maintenance.ui.api_client import APIClientError


ROOT = Path(__file__).resolve().parents[1]


class StreamlitApplicationTests(unittest.TestCase):
    def test_application_renders_default_scenario_without_exception(self):
        st.cache_resource.clear()
        with patch.dict(os.environ, {"APP_BACKEND": "local"}):
            app = AppTest.from_file(
                str(ROOT / "src" / "predictive_maintenance" / "ui" / "streamlit_app.py")
            ).run(timeout=60)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.title[0].value, "Adaptive Predictive Maintenance Platform")
        self.assertGreaterEqual(len(app.selectbox), 5)
        self.assertTrue(any("Engineering assurance" in item.value for item in app.header))
        st.cache_resource.clear()

    def test_api_unavailable_is_displayed_without_prediction(self):
        st.cache_resource.clear()
        with patch.dict(os.environ, {"APP_BACKEND": "api"}), patch(
            "predictive_maintenance.ui.api_client.APIApplicationService",
            side_effect=APIClientError("controlled API outage"),
        ):
            app = AppTest.from_file(
                str(ROOT / "src/predictive_maintenance/ui/streamlit_app.py")
            ).run(timeout=60)
        self.assertEqual(list(app.exception), [])
        self.assertTrue(any("Application unavailable" in item.value for item in app.error))
        self.assertEqual(len(app.metric), 0)
        st.cache_resource.clear()


if __name__ == "__main__":
    unittest.main()
