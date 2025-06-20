from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import typer
from qdrant_client.http import models as qdrant_models

from .config import env_default
from .vector_store import (
    get_openai_client, 
    get_qdrant_client, 
    ensure_collection, 
    embed, 
    upsert_documents,
    collection_exists
)
from .document_processing import extract_letter_text
from .retrieval import retrieve_similar_job_offers
from .generation import (
    company_research, 
    generate_letter, 
    accuracy_check, 
    precision_check, 
    company_fit_check, 
    user_fit_check, 
    rewrite_letter
)

app = typer.Typer(help="Cover letter customizator CLI.")

@app.command()
def refresh(
    jobs_source_folder: Path = typer.Option(Path(env_default("JOBS_SOURCE_FOLDER", "examples")), help="Folder holding files to build the Qdrant repo."),
    letters_source_folder: Path = typer.Option(Path(env_default("LETTERS_SOURCE_FOLDER", "examples")), help="Folder holding files to build the Qdrant repo."),
    jobs_source_suffix: str = typer.Option(env_default("JOBS_SOURCE_SUFFIX", "txt")),
    letters_source_suffix: str = typer.Option(env_default("LETTERS_SOURCE_SUFFIX", "tex")),
    letters_ignore_until: str = typer.Option(env_default("LETTERS_IGNORE_UNTIL", None)),
    letters_ignore_after: str = typer.Option(env_default("LETTERS_IGNORE_AFTER", None)),
    qdrant_host: str = typer.Option(env_default("QDRANT_HOST", "localhost")),
    qdrant_port: int = typer.Option(int(env_default("QDRANT_PORT", "6333"))),
    clear: bool = typer.Option(False, help="Empty the Qdrant repository before rebuilding it."),
):
    """Refreshes example repository used for retrieval augmented generation."""

    openai_client = get_openai_client(env_default("OPENAI_API_KEY"))
    client = get_qdrant_client(qdrant_host, qdrant_port)
    
    if clear:
        from .config import COLLECTION_NAME
        typer.echo(f"[INFO] Resetting collection: {COLLECTION_NAME}")
        client.delete_collection(collection_name=COLLECTION_NAME)
    ensure_collection(client)

    typer.echo(f"[INFO] Processing jobs from: {jobs_source_folder} with suffix: {jobs_source_suffix}")
    typer.echo(f"[INFO] Processing letters from: {letters_source_folder} with suffix: {letters_source_suffix}")
    typer.echo(f"[INFO] Ignoring until: {letters_ignore_until} and after: {letters_ignore_after}")

    points = []
    for path in jobs_source_folder.glob(f"*{jobs_source_suffix}"):
        # Job descriptions are in <company_name><jobs_source_suffix> files
        company_name = path.stem
        job_text = path.read_text(encoding="utf-8")
        
        # Look for corresponding letter in <company_name><letters_source_suffix> file
        letter_path = letters_source_folder / f"{company_name}{letters_source_suffix}"
        if not letter_path.exists():
            typer.echo(f"[WARN] No letter found for {company_name}. Skipping.")
            continue
        typer.echo(f"[INFO] Processing {company_name}")

        letter_text = extract_letter_text(letter_path, letters_ignore_until, letters_ignore_after)
    
        vector = embed(job_text, openai_client)
        payload = {
            "job_text": job_text,
            "letter_text": letter_text,
            "company_name": company_name,
            "path": str(path),
        }
        points.append(
            qdrant_models.PointStruct(
                id=abs(hash(path.stem)),  # deterministic unsigned id from path
                vector=vector,
                payload=payload,
            )
        )

    if points:
        upsert_documents(client, points)
        typer.echo(f"[INFO] Upserted {len(points)} documents to Qdrant.")
    else:
        typer.echo("[WARN] No documents found to upsert.")

@app.command()
def process_job(
    path: Path = typer.Argument(..., help="Path to the file containing the job description."),
    cv: Path = typer.Option(Path(env_default("CV_PATH", "cv.md")), help="Path to user's CV in text/markdown."),
    company_name: Optional[str] = typer.Option(env_default("COMPANY_NAME"), help="Company name. Defaults to job description filename stem."),
    out: Optional[Path] = typer.Option(None, help="Output path for the generated letter."),
    openai_key: Optional[str] = typer.Option(env_default("OPENAI_API_KEY"), help="OpenAI API key."),
    qdrant_host: str = typer.Option(env_default("QDRANT_HOST", "localhost")),
    qdrant_port: int = typer.Option(int(env_default("QDRANT_PORT", "6333"))),
    refine: bool = typer.Option(True, help="Whether to try to improve the letter through feedback."),
):
    """Writes a cover letter for the given job description."""

    openai_client = get_openai_client(openai_key)
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

    trace_dir = Path("trace", company_name)
    trace_dir.mkdir(parents=True, exist_ok=True)

    # step 1a and 1b can be done in parallel, as they are API calls and don't depend on each other
    # so we start them in different threads 
    with ThreadPoolExecutor(max_workers=2) as executor:
        job_offers_future = executor.submit(retrieve_similar_job_offers, job_text, openai_client, qdrant_client, trace_dir)
        company_report_future = executor.submit(company_research, company_name, job_text, openai_client, trace_dir)

    top_docs = job_offers_future.result()
    company_report = company_report_future.result()

    # Step 2: Letter generation
    letter = generate_letter(cv_text, top_docs, company_report, job_text, openai_client, trace_dir)
    (trace_dir / "first_draft.txt").write_text(letter, encoding="utf-8")

    if refine:
        # Step 3: Feedback
        with ThreadPoolExecutor(max_workers=4) as executor:
            accuracy_future = executor.submit(accuracy_check, letter, cv_text, openai_client)
            precision_future = executor.submit(precision_check, letter, company_report, job_text, openai_client)
            company_fit_future = executor.submit(company_fit_check, letter, company_report, job_text, openai_client)
            user_fit_future = executor.submit(user_fit_check, letter, top_docs, openai_client)
        
        accuracy_feedback = accuracy_future.result()
        precision_feedback = precision_future.result()
        company_fit_feedback = company_fit_future.result()
        user_fit_feedback = user_fit_future.result()

        # Step 4: Rewrite
        letter = rewrite_letter(letter, accuracy_feedback, precision_feedback, company_fit_feedback, user_fit_feedback, openai_client, trace_dir)

    # Output
    if out is None:
        out = Path("letters", f"{company_name}.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(letter, encoding="utf-8")
    typer.echo(f"[INFO] Letter written to {out}")

if __name__ == "__main__":
    app() 