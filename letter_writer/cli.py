from pathlib import Path
from typing import Optional

import typer

from letter_writer.client import ModelVendor

# Import shared business logic
from .service import refresh_repository, write_cover_letter

from .config import env_default

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
    """Refresh the example repository used for retrieval-augmented generation."""

    refresh_repository(
        jobs_source_folder=jobs_source_folder,
        jobs_source_suffix=jobs_source_suffix,
        letters_source_folder=letters_source_folder,
        letters_source_suffix=letters_source_suffix,
        letters_ignore_until=letters_ignore_until,
        letters_ignore_after=letters_ignore_after,
        negative_letters_source_folder=negative_letters_source_folder,
        negative_letters_source_suffix=negative_letters_source_suffix,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        clear=clear,
        logger=typer.echo,
    )

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
    """Write a cover letter for the given job description."""

    try:
        write_cover_letter(
            path=path,
            cv=cv,
            company_name=company_name,
            out=out,
            model_vendor=model_vendor,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            refine=refine,
            fancy=fancy,
            logger=typer.echo,
        )
    except RuntimeError as err:
        typer.echo(f"[ERROR] {err}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app() 