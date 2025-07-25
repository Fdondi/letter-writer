from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Literal, Optional
import zlib  # Add this import

from openai import OpenAI
from qdrant_client.models import Document
import typer
from qdrant_client.http import models as qdrant_models

from letter_writer.client import ModelVendor, get_client

from .config import env_default
from .vector_store import (
    get_qdrant_client, 
    ensure_collection, 
    embed, 
    upsert_documents,
    collection_exists
)
from .document_processing import extract_letter_text
from .retrieval import retrieve_similar_job_offers, select_top_documents
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
    rewrite_letter
)

app = typer.Typer(help="Cover letter customizator CLI.")

@app.command()
def refresh(
    jobs_source_folder: Path = typer.Option(Path(env_default("JOBS_SOURCE_FOLDER", "examples")), help="Folder holding past job offers, used as key for the Qdrant repo."),
    jobs_source_suffix: str = typer.Option(env_default("JOBS_SOURCE_SUFFIX", ".txt")),
    letters_source_folder: Path = typer.Option(Path(env_default("LETTERS_SOURCE_FOLDER", "examples")), help="Folder holding past cover letters, used as value for the Qdrant repo."),
    letters_source_suffix: str = typer.Option(env_default("LETTERS_SOURCE_SUFFIX", ".tex")),
    letters_ignore_until: str = typer.Option(env_default("LETTERS_IGNORE_UNTIL", None)),
    letters_ignore_after: str = typer.Option(env_default("LETTERS_IGNORE_AFTER", None)),
    negative_letters_source_folder: Path = typer.Option(Path(env_default("NEGATIVE_LETTERS_SOURCE_FOLDER", "examples")), 
                                                        help="Folder holding past cover letters that the AI produced, before being corrected by a human; used as value for the Qdrant repo."),
    negative_letters_source_suffix: str = typer.Option(env_default("NEGATIVE_LETTERS_SOURCE_SUFFIX", ".txt")),
    qdrant_host: str = typer.Option(env_default("QDRANT_HOST", "localhost")),
    qdrant_port: int = typer.Option(int(env_default("QDRANT_PORT", "6333"))),
    clear: bool = typer.Option(False, help="Empty the Qdrant repository before rebuilding it."),
):
    """Refreshes example repository used for retrieval augmented generation."""

    openai_client = OpenAI()
    client = get_qdrant_client(qdrant_host, qdrant_port)
    
    if clear:
        from .config import COLLECTION_NAME
        typer.echo(f"[INFO] Resetting collection: {COLLECTION_NAME}")
        client.delete_collection(collection_name=COLLECTION_NAME)
    ensure_collection(client)

    typer.echo(f"[INFO] Processing jobs from: {jobs_source_folder} with suffix: {jobs_source_suffix}")
    typer.echo(f"[INFO] Processing letters from: {letters_source_folder} with suffix: {letters_source_suffix}")
    typer.echo(f"[INFO]    [Ignoring until: {letters_ignore_until} and after: {letters_ignore_after}]")
    typer.echo(f"[INFO] Processing negative letters from: {negative_letters_source_folder} with suffix: {negative_letters_source_suffix}")

    points = []
    n_with_negative_letters = 0
    n_negative_letters = 0
    for path in jobs_source_folder.glob(f"*{jobs_source_suffix}"):
        # Job descriptions are in <company_name><jobs_source_suffix> files
        company_name = path.stem
        job_text = path.read_text(encoding="utf-8")
        
        # Look for corresponding letter in <company_name><letters_source_suffix> file
        letter_path = letters_source_folder / f"{company_name}{letters_source_suffix}"
        if not letter_path.exists():
            typer.echo(f"[WARN] No letter found for {company_name}. Skipping.")
            continue

        letter_text = extract_letter_text(letter_path, letters_ignore_until, letters_ignore_after)

        # negative letters can be written by one or more AIs, so they might have .<model_vendor>.txt suffixes. Use glob to find any
        negative_letter_paths = list(negative_letters_source_folder.glob(f"{company_name}*{negative_letters_source_suffix}"))
        if negative_letter_paths:
            negative_letter_text = "\n\n".join(f"--Letter {i+1} --\n{path.read_text(encoding='utf-8')}" for i, path in enumerate(negative_letter_paths))
            n_with_negative_letters += 1
            n_negative_letters += len(negative_letter_paths)
            negative_debug = ", ".join(str(path.stem) for path in negative_letter_paths)
            typer.echo(f"[INFO] Processing {company_name} with {len(negative_letter_paths)} negative letters ({negative_debug}) [{n_with_negative_letters} with negative letters in total]")
        else:
            negative_letter_text = None
            typer.echo(f"[INFO] Processing {company_name} (without negative letter)")
    
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
                # Use zlib.adler32 for a fast, deterministic numeric hash
                id=zlib.adler32(company_name.encode()),
                vector=vector,
                payload=payload,
            )
        )

    if points:
        upsert_documents(client, points)
        typer.echo(f"[INFO] Upserted {len(points)} documents to Qdrant. ({n_with_negative_letters} with negative letters, in total {n_negative_letters} negative letters)")
    else:
        typer.echo("[WARN] No documents found to upsert.")

@app.command()
def process_job(
    path: Path = typer.Argument(..., help="Path to the file containing the job description."),
    cv: Path = typer.Option(Path(env_default("CV_PATH", "cv.md")), help="Path to user's CV in text/markdown."),
    company_name: Optional[str] = typer.Option(env_default("COMPANY_NAME"), help="Company name. Defaults to job description filename stem."),
    out: Optional[Path] = typer.Option(None, help="Output path for the generated letter."),
    model_vendor: Optional[ModelVendor] = typer.Option(None, help="Model vendor. Default: all"),
    qdrant_host: str = typer.Option(env_default("QDRANT_HOST", "localhost")),
    qdrant_port: int = typer.Option(int(env_default("QDRANT_PORT", "6333"))),
    refine: bool = typer.Option(True, help="Whether to try to improve the letter through feedback."),
    fancy: bool = typer.Option(False, help="Whether to fancy up the letter."),
):
    """Writes a cover letter for the given job description."""

    qdrant_client = get_qdrant_client(qdrant_host, qdrant_port)
    
    if not collection_exists(qdrant_client):
        typer.echo("[ERROR] Qdrant collection not found. Run 'refresh' first.")
        raise typer.Exit(code=1)

    if path.is_dir():
        # take the newest txt file in the folder
        path = max(path.glob("*.txt"), key=lambda x: x.stat().st_mtime)
        typer.echo(f"[INFO] Using newest file in folder: {path}")

    job_text = path.read_text(encoding="utf-8")
    cv_text = cv.read_text(encoding="utf-8")
    
    # Determine company name
    if company_name is None:
        company_name = Path(path).stem

    # call Qdrant here as it's model independent; no point in doing it for each model
    openai_client = OpenAI()
    qdrant_client = get_qdrant_client(qdrant_host, qdrant_port)
    search_result = retrieve_similar_job_offers(job_text, qdrant_client, openai_client)

    if model_vendor is None:
        with ThreadPoolExecutor(max_workers=len(ModelVendor)) as executor:
            futures = [executor.submit(process_job_impl, cv_text, job_text, company_name, out, model_vendor, search_result, refine, fancy) for model_vendor in ModelVendor]
            for future in futures:
                future.result()
    else:
        process_job_impl(cv_text, job_text, company_name, out, model_vendor, search_result, refine, fancy)

def process_job_impl(cv_text: str, job_text: str, company_name: str, out: Optional[Path], model_vendor: ModelVendor, search_result: List[Document], refine: bool, fancy: bool):

    file_name = f"{company_name}.{model_vendor.value}"

    trace_dir = Path("trace", file_name)
    trace_dir.mkdir(parents=True, exist_ok=True)

    ai_client = get_client(model_vendor)
    openai_client = OpenAI()

    # step 1a and 1b can be done in parallel, as they are API calls and don't depend on each other
    # so we start them in different threads, each with its own OpenAI client
    with ThreadPoolExecutor(max_workers=2) as executor:
        job_offers_future = executor.submit(select_top_documents, search_result, job_text, ai_client, trace_dir)
        company_report_future = executor.submit(company_research, company_name, job_text, ai_client, trace_dir)

    top_docs = job_offers_future.result()
    company_report = company_report_future.result()

    # Step 2: Letter generation with a fresh client
    letter = generate_letter(cv_text, top_docs, company_report, job_text, ai_client, trace_dir)
    (trace_dir / "first_draft.txt").write_text(letter, encoding="utf-8")

    if refine:
        # Step 3: Feedback with separate clients for each thread
        with ThreadPoolExecutor(max_workers=5) as executor:
            instruction_future = executor.submit(instruction_check, letter, ai_client)
            accuracy_future = executor.submit(accuracy_check, letter, cv_text, ai_client)
            precision_future = executor.submit(precision_check, letter, company_report, job_text, ai_client)
            company_fit_future = executor.submit(company_fit_check, letter, company_report, job_text, ai_client)
            user_fit_future = executor.submit(user_fit_check, letter, top_docs, ai_client)
            human_future = executor.submit(human_check, letter, top_docs, ai_client)
        
        instruction_feedback = instruction_future.result()
        accuracy_feedback = accuracy_future.result()
        precision_feedback = precision_future.result()
        company_fit_feedback = company_fit_future.result()
        user_fit_feedback = user_fit_future.result()
        human_feedback = human_future.result()

        # Step 4: Rewrite with a fresh client
        letter = rewrite_letter(letter, instruction_feedback, accuracy_feedback, precision_feedback, company_fit_feedback, user_fit_feedback, human_feedback, ai_client, trace_dir)

    # Output
    if out is None:
        out = Path("letters", f"{file_name}.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(letter, encoding="utf-8")
    typer.echo(f"[INFO] Letter written to {out}")

    if fancy:
        fletter = fancy_letter(letter, get_client(model_vendor))
        fancy_out = Path("fancy_letters", f"{file_name}.txt")
        fancy_out.parent.mkdir(parents=True, exist_ok=True)
        fancy_out.write_text(fletter, encoding="utf-8")
        typer.echo(f"[INFO] Fancy letter written to {fancy_out}")

if __name__ == "__main__":
    app() 