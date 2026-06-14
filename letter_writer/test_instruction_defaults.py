from letter_writer.instruction_defaults import (
    get_default_instruction,
    instruction_content_hash,
    normalize_instruction_text,
)


def test_instruction_content_hash_stable():
    text = "Hello\nWorld"
    assert instruction_content_hash(text) == instruction_content_hash("Hello\nWorld\n")


def test_get_default_structure_has_hash():
    text, digest = get_default_instruction("structure")
    assert text.strip()
    assert len(digest) == 16
    assert digest == instruction_content_hash(text)


def test_normalize_instruction_text():
    assert normalize_instruction_text("  a\r\nb  ") == "a\nb"
