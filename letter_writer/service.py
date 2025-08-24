from __future__ import annotations

from tqdm import tqdm

"""Business-logic layer shared by CLI and Web API.
Extracted from letter_writer.cli to avoid code duplication.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional
import zlib

from openai import OpenAI
from qdrant_client.http import models as qdrant_models
from qdrant_client.models import Document

from .client import ModelVendor, get_client
from .config import env_default
from .document_processing import extract_letter_text
from .generation import (
    company_research,
    fancy_letter,
    generate_letter,
    accuracy_check,
    human_check,
    instruction_check,
    precision_check,
    company_fit_check,
    user_fit_check,
    rewrite_letter,
)
from .retrieval import retrieve_similar_job_offers, select_top_documents
from .vector_store import (
    ensure_collection,
    embed,
    get_qdrant_client,
    upsert_documents,
    collection_exists,
)

__all__ = [
    "refresh_repository",
    "write_cover_letter",
]


def refresh_repository(
    jobs_source_folder: Path = Path(env_default("JOBS_SOURCE_FOLDER", "examples")),
    jobs_source_suffix: str = env_default("JOBS_SOURCE_SUFFIX", ".txt"),
    letters_source_folder: Path = Path(env_default("LETTERS_SOURCE_FOLDER", "examples")),
    letters_source_suffix: str = env_default("LETTERS_SOURCE_SUFFIX", ".tex"),
    letters_ignore_until: Optional[str] = env_default("LETTERS_IGNORE_UNTIL", None),
    letters_ignore_after: Optional[str] = env_default("LETTERS_IGNORE_AFTER", None),
    negative_letters_source_folder: Path = Path(env_default("NEGATIVE_LETTERS_SOURCE_FOLDER", "examples")),
    negative_letters_source_suffix: str = env_default("NEGATIVE_LETTERS_SOURCE_SUFFIX", ".txt"),
    qdrant_host: str = env_default("QDRANT_HOST", "localhost"),
    qdrant_port: int = int(env_default("QDRANT_PORT", "6333")),
    clear: bool = False,
    logger=print,
):
    """Populate or refresh the Qdrant collection used for retrieval-augmented generation."""

    from .config import COLLECTION_NAME

    openai_client = OpenAI()
    client = get_qdrant_client(qdrant_host, qdrant_port)

    if clear:
        logger(f"[INFO] Resetting collection: {COLLECTION_NAME}")
        client.delete_collection(collection_name=COLLECTION_NAME)
    ensure_collection(client)

    logger(
        f"[INFO] Processing jobs from: {jobs_source_folder} with suffix: {jobs_source_suffix}"
    )
    logger(
        f"[INFO] Processing letters from: {letters_source_folder} with suffix: {letters_source_suffix}"
    )
    logger(
        f"[INFO]    [Ignoring until: {letters_ignore_until} and after: {letters_ignore_after}]"
    )
    logger(
        f"[INFO] Processing negative letters from: {negative_letters_source_folder} with suffix: {negative_letters_source_suffix}"
    )

    points: List[qdrant_models.PointStruct] = []
    n_with_negative_letters = 0
    n_negative_letters = 0
    skipped = []

    for path in jobs_source_folder.glob(f"*{jobs_source_suffix}"):
        company_name = path.stem
        job_text = path.read_text(encoding="utf-8")

        letter_path = letters_source_folder / f"{company_name}{letters_source_suffix}"
        if not letter_path.exists():
            logger(f"[WARN] No letter found for {company_name}. Skipping.")
            skipped.append(company_name)
            continue

        letter_text = extract_letter_text(
            letter_path, letters_ignore_until, letters_ignore_after
        )

        negative_letter_paths = list(
            negative_letters_source_folder.glob(
                f"{company_name}*{negative_letters_source_suffix}"
            )
        )
        if negative_letter_paths:
            negative_letter_text = "\n\n".join(
                f"--Letter {i+1} --\n{p.read_text(encoding='utf-8')}"
                for i, p in enumerate(negative_letter_paths)
            )
            n_with_negative_letters += 1
            n_negative_letters += len(negative_letter_paths)
            neg_debug = ", ".join(str(p.stem) for p in negative_letter_paths)
            logger(
                f"[INFO] Processing {company_name} with {len(negative_letter_paths)} negative letters ({neg_debug}) [{n_with_negative_letters} with negative letters in total]"
            )
        else:
            negative_letter_text = None
            logger(f"[INFO] Processing {company_name} (without negative letter)")

        vector = embed(job_text, openai_client)
        payload = {
            "job_text": job_text,
            "letter_text": letter_text,
            "company_name": company_name,
            "path": str(path),
        }
        if negative_letter_text is not None:
            payload["negative_letter_text"] = negative_letter_text

        points.append(
            qdrant_models.PointStruct(
                id=zlib.adler32(company_name.encode()),
                vector=vector,
                payload=payload,
            )
        )

    if points:
        upsert_documents(client, points)
        logger(
            f"[INFO] Upserted {len(points)} documents to Qdrant. ({n_with_negative_letters} with negative letters, in total {n_negative_letters} negative letters). Skipped {len(skipped)} companies: {', '.join(skipped)}"
        )
    else:
        logger("[WARN] No documents found to upsert.")


# ---------------------------------------------------------------------------
#  Cover-letter generation
# ---------------------------------------------------------------------------


def _process_single_vendor(
    cv_text: str,
    job_text: str,
    company_name: str,
    out: Optional[Path],
    model_vendor: ModelVendor,
    search_result: List[Document],
    refine: bool,
    fancy: bool,
    logger=print,
):
    """Generate the letter for one model vendor and return its text."""
    trace_dir = Path("trace", f"{company_name}.{model_vendor.value}")
    trace_dir.mkdir(parents=True, exist_ok=True)

    ai_client = get_client(model_vendor)

    # step 1a and 1b in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        job_offers_future = executor.submit(
            select_top_documents, search_result, job_text, ai_client, trace_dir
        )
        company_report_future = executor.submit(
            company_research, company_name, job_text, ai_client, trace_dir
        )

    top_docs = job_offers_future.result()
    company_report = company_report_future.result()

    # letter generation
    letter = generate_letter(
        cv_text, top_docs, company_report, job_text, ai_client, trace_dir
    )
    (trace_dir / "first_draft.txt").write_text(letter, encoding="utf-8")

    if refine:
        with ThreadPoolExecutor(max_workers=5) as executor:
            instruction_future = executor.submit(instruction_check, letter, ai_client)
            accuracy_future = executor.submit(
                accuracy_check, letter, cv_text, ai_client
            )
            precision_future = executor.submit(
                precision_check, letter, company_report, job_text, ai_client
            )
            company_fit_future = executor.submit(
                company_fit_check, letter, company_report, job_text, ai_client
            )
            user_fit_future = executor.submit(
                user_fit_check, letter, top_docs, ai_client
            )
            human_future = executor.submit(human_check, letter, top_docs, ai_client)

        letter = rewrite_letter(
            letter,
            instruction_future.result(),
            accuracy_future.result(),
            precision_future.result(),
            company_fit_future.result(),
            user_fit_future.result(),
            human_future.result(),
            ai_client,
            trace_dir,
        )

    # write output
    if out is None:
        out = Path("letters", f"{company_name}.{model_vendor.value}.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(letter, encoding="utf-8")
    logger(f"[INFO] Letter written to {out}")

    if fancy:
        fletter = fancy_letter(letter, get_client(model_vendor))
        fancy_out = Path("fancy_letters", f"{company_name}.{model_vendor.value}.txt")
        fancy_out.parent.mkdir(parents=True, exist_ok=True)
        fancy_out.write_text(fletter, encoding="utf-8")
        logger(f"[INFO] Fancy letter written to {fancy_out}")

    return letter  # Return generated letter text

class FakeTDQM:
    def __init__(self, total: int, unit: str, desc: str = "Processing", logger=print):
        self.total = total
        self.logger = logger
        self.desc = desc
        self.unit = unit
        self.count = 0

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def update(self, x: int = 1):
        self.count += x
        self.logger(f"{self.desc} {self.count}/{self.total} {self.unit}")

    def set_description(self, desc: str):
        self.desc = desc

def get_progress_tracker(total: int, logger=print):
    try:
        from tqdm import tqdm
        return tqdm(total=total, unit="vendors")
    except ImportError:
        return FakeTDQM(total, unit="vendors", logger=logger)

# Public API

def write_cover_letter(
    *,
    path: Optional[Path] = None,
    job_text: Optional[str] = None,
    cv: Path = Path(env_default("CV_PATH", "cv.md")),
    cv_text: Optional[str] = None,
    company_name: Optional[str] = None,
    out: Optional[Path] = None,
    model_vendor: Optional[ModelVendor] = None,
    qdrant_host: str = env_default("QDRANT_HOST", "localhost"),
    qdrant_port: int = int(env_default("QDRANT_PORT", "6333")),
    refine: bool = True,
    fancy: bool = False,
    logger=print,
) -> dict[str, str]:
    """Generate cover letter(s) from text or file and return them.

    Parameters
    ----------
    path : Optional[Path]
        Path to job description text file (fallback if *job_text* not given).
    job_text : Optional[str]
        Raw job description text. If given, *path* can be omitted.
    cv : Path
        Path to CV file (fallback if *cv_text* not given).
    cv_text : Optional[str]
        Raw CV text overriding the *cv* file.
    company_name : str, optional
        Company name; if omitted and *path* given, it is derived from path stem.
    out : Path, optional
        Base output path (folder+filename) for generated letter(s).
    model_vendor : ModelVendor, optional
        If omitted, generate letters for all vendors.

    Returns
    -------
    dict
        Mapping ``vendor_name -> letter_text``.
    """

    qdrant_client = get_qdrant_client(qdrant_host, qdrant_port)
    if not collection_exists(qdrant_client):
        raise RuntimeError("Qdrant collection not found. Run 'refresh' first.")
    # Ensure we have job_text and cv_text
    if job_text is None:
        if path is None:
            raise ValueError("Either job_text or path must be provided")
        if path.is_dir():
            path = max(path.glob("*.txt"), key=lambda p: p.stat().st_mtime)
            logger(f"[INFO] Using newest file in folder: {path}")
        job_text = path.read_text(encoding="utf-8")

    if cv_text is None:
        cv_text = cv.read_text(encoding="utf-8")

    # Determine company name
    if company_name is None:
        if path is not None:
            company_name = path.stem
        else:
            raise ValueError("Either company_name or path must be provided")

    openai_client = OpenAI()
    search_result = retrieve_similar_job_offers(job_text, qdrant_client, openai_client)

    letters: dict[str, str] = {}

    if model_vendor is None:
        with ThreadPoolExecutor(max_workers=len(ModelVendor)) as executor:
            futures = {
                executor.submit(
                    _process_single_vendor,
                    cv_text,
                    job_text,
                    company_name,
                    out,
                    mv,
                    search_result,
                    refine,
                    fancy,
                    logger,
                ): mv
                for mv in ModelVendor
            }
            with get_progress_tracker(len(futures)) as pbar:
                for future in as_completed(futures):
                    key = futures[future].value
                    pbar.set_description(f"Processing {key}")
                    try:
                        letters[key] = future.result()
                    except Exception as e:
                        logger.error(f"{key} failed: {e}")
                    finally:
                        pbar.update()
    else:
        letters[model_vendor.value] = _process_single_vendor(
            cv_text,
            job_text,
            company_name,
            out,
            model_vendor,
            search_result,
            refine,
            fancy,
            logger,
        )

    return letters