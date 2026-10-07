from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


class HospitalResetTests(unittest.TestCase):
    def test_selected_hospital_view_can_return_to_search(self):
        hospital_page = Path(__file__).resolve().parents[1] / "pages" / "hospital.py"
        app = AppTest.from_file(str(hospital_page), default_timeout=30)
        app.session_state["selected_place_id"] = "hospital-does-not-exist"

        app.run()

        self.assertTrue(any(button.label == "다른 장소 찾기" for button in app.button))
        next(button for button in app.button if button.label == "다른 장소 찾기").click().run()

        self.assertNotIn("selected_place_id", app.session_state)
        self.assertTrue(any(selectbox.label == "시/도를 고르세요" for selectbox in app.selectbox))
        self.assertTrue(any(selectbox.label == "시/군/구를 고르세요" for selectbox in app.selectbox))
        self.assertEqual(app.radio(key="place_kind").value, "hospital")
        self.assertEqual([item.message for item in app.exception], [])


if __name__ == "__main__":
    unittest.main()
