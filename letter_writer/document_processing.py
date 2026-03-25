from pathlib import Path
from typing import Optional

def extract_letter_text(
    letter_path: Path,
    ignore_until: Optional[str],
    ignore_after: Optional[str],
) -> str:
    """Extract letter text from file with optional content filtering."""
    letter_content = letter_path.read_text(encoding="utf-8")
    if ignore_until:
        start_idx = letter_content.find(ignore_until) + len(ignore_until)
        if start_idx != -1:
            letter_content = letter_content[start_idx:]
    if ignore_after:
        end_idx = letter_content.find(ignore_after) 
        if end_idx != -1:
            letter_content = letter_content[:end_idx]
    return letter_content.strip() 