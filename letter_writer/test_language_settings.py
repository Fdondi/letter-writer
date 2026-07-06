import unittest

from letter_writer.language_settings import (
    build_language_system_prefix,
    build_translation_system_message,
    normalize_default_languages,
    resolve_language_code,
)


class LanguageSettingsTests(unittest.TestCase):
    def test_normalize_applies_german_defaults(self):
        langs = normalize_default_languages([{"code": "de", "label": "DE", "enabled": True}])
        self.assertEqual(langs[0]["level"], "B2")
        self.assertIn("Umlaute", langs[0]["instructions"])

    def test_resolve_german_job_language(self):
        user_data = {"default_languages": [{"code": "de", "label": "German", "enabled": True, "level": "B2", "instructions": ""}]}
        self.assertEqual(resolve_language_code("German", user_data), "de")
        self.assertEqual(resolve_language_code("deutsch", user_data), "de")

    def test_build_system_prefix_includes_level(self):
        user_data = {
            "default_languages": [
                {
                    "code": "de",
                    "label": "DE",
                    "enabled": True,
                    "level": "B2",
                    "instructions": "Verwende echte Umlaute.",
                }
            ]
        }
        prefix = build_language_system_prefix(user_data, "German")
        self.assertIn("MANDATORY", prefix)
        self.assertIn("CEFR B2", prefix)
        self.assertIn("upper-intermediate", prefix)
        self.assertIn("Umlaute", prefix)

    def test_level_override_on_translate(self):
        user_data = {"default_languages": [{"code": "de", "label": "DE", "enabled": True, "level": "C2", "instructions": ""}]}
        msg = build_translation_system_message(user_data, "de", level_override="B2")
        self.assertIn("CEFR B2", msg)
        self.assertNotIn("CEFR C2", msg)

    def test_translation_message_for_english_c2(self):
        user_data = {
            "default_languages": [
                {"code": "en", "label": "EN", "enabled": True, "level": "C2", "instructions": "Prefer concise phrasing."}
            ]
        }
        msg = build_translation_system_message(user_data, "en")
        self.assertIn("MANDATORY", msg)
        self.assertIn("CEFR C2", msg)
        self.assertIn("concise phrasing", msg)


if __name__ == "__main__":
    unittest.main()
