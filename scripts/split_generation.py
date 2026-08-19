"""One-off helper: split letter_writer/generation.py into focused modules."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "letter_writer" / "generation.py"
lines = GEN.read_text(encoding="utf-8").splitlines(keepends=True)


def slice_lines(start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


JOB_EXTRACTION_HEADER = '''"""Job posting extraction, competence grading, and extraction cache."""

import json
import logging
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from langsmith import traceable

from .clients.base import BaseClient, ModelRole
from .skill_utils import core_skill_name as _core_skill_name

logger = logging.getLogger(__name__)

'''

INSTRUCTIONS_HEADER = '''"""Structure, style, and search instructions; translation and company research."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from langsmith import traceable

from .clients.base import BaseClient, ModelRole

logger = logging.getLogger(__name__)

'''

LETTER_GENERATION_HEADER = '''"""Cover letter plan, draft generation, and fancy refinement."""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langsmith import traceable

from .clients.base import BaseClient, ModelRole
from .instructions import (
    _prepend_language_prefix,
    get_structure_instructions,
    get_style_instructions,
)
from .job_extraction import MissingCVError
from .typed_shapes import TopDocument

logger = logging.getLogger(__name__)

'''

FEEDBACK_CHECKS_HEADER = '''"""Phased and vendor feedback checks, normalization, and agentic context helpers."""

import copy
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langsmith import traceable

from .clients.base import BaseClient, ModelRole
from .feedback_topics import AGENTIC_TOPIC_KEYS, get_agentic_topic_context_from_registry
from .instructions import get_style_instructions
from .typed_shapes import TopDocument

logger = logging.getLogger(__name__)

'''

REWRITE_HEADER = '''"""Cover letter rewrite incorporating phased feedback."""

import logging
from pathlib import Path
from typing import Any, List

from langsmith import traceable

from .clients.base import BaseClient, ModelRole
from .feedback_checks import (
    FEEDBACK_CONTEXT_MATERIAL_SOURCES_FROZEN,
    FEEDBACK_CONTEXT_USER_SOURCE,
    _is_no_comment,
)
from .instructions import _prepend_language_prefix, get_style_instructions

logger = logging.getLogger(__name__)

'''

job_extraction_body = (
    "_EXTRACTION_CACHE: OrderedDict = OrderedDict()\n"
    + slice_lines(25, 31)
    + slice_lines(1145, 1181)
    + slice_lines(1223, 1657)
)

instructions_body = slice_lines(1659, 1846)

letter_generation_body = (
    slice_lines(276, 325)
    + slice_lines(348, 395)
    + slice_lines(1184, 1220)
    + slice_lines(1850, 2031)
    + slice_lines(2562, 2576)
)

feedback_checks_body = (
    slice_lines(35, 274)
    + slice_lines(327, 345)
    + slice_lines(398, 582)
    + "# Keys must match phased feedback buckets; sourced from feedback_topics registry.\n"
    + "PHASED_FEEDBACK_CATEGORY_KEYS = AGENTIC_TOPIC_KEYS\n\n"
    + slice_lines(597, 1136)
    + slice_lines(1139, 1142)
    + slice_lines(2034, 2405)
)

rewrite_body = slice_lines(2408, 2559)

(ROOT / "letter_writer" / "job_extraction.py").write_text(
    JOB_EXTRACTION_HEADER + job_extraction_body, encoding="utf-8"
)
(ROOT / "letter_writer" / "instructions.py").write_text(
    INSTRUCTIONS_HEADER + instructions_body, encoding="utf-8"
)
(ROOT / "letter_writer" / "letter_generation.py").write_text(
    LETTER_GENERATION_HEADER + letter_generation_body, encoding="utf-8"
)
(ROOT / "letter_writer" / "feedback_checks.py").write_text(
    FEEDBACK_CHECKS_HEADER + feedback_checks_body, encoding="utf-8"
)
(ROOT / "letter_writer" / "rewrite.py").write_text(
    REWRITE_HEADER + rewrite_body, encoding="utf-8"
)

print("Wrote split modules")
