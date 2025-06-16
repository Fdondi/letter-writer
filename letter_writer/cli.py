import json
import os
from pathlib import Path
from typing import List, Optional

import typer
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from openai import OpenAI

# Constants
COLLECTION_NAME = "job_offers"
EMBED_MODEL = "text-embedding-3-small"
TRACE_DIR = Path("trace")

def _load_dotenv() -> None:
    """Load environment variables from a .env file if present."""
    load_dotenv()


def _env_default(key: str, default: Optional[str] = None) -> Optional[str]:
    """Return value from env or default."""
    return os.getenv(key, default)


# Load environment variables at module level
_load_dotenv()

app = typer.Typer(help="Cover letter customizator CLI.")


def _get_openai_client(api_key: Optional[str] = None) -> OpenAI:
    if api_key is None:
        api_key = _env_default("OPENAI_API_KEY")
    if not api_key:
        typer.echo("[ERROR] OpenAI API key not provided. Use --openai_key or set OPENAI_API_KEY env variable.")
        raise typer.Exit(code=1)
    return OpenAI(api_key=api_key)


def _embed(text: str, client: OpenAI) -> List[float]:
    """Get embedding vector for text using OpenAI."""
    response = client.embeddings.create(model=EMBED_MODEL, input=text)
    return response.data[0].embedding


def _get_qdrant_client(host: str, port: int) -> QdrantClient:
    return QdrantClient(host=host, port=port)


def _ensure_collection(client: QdrantClient, vector_size: int = 1536):
    if COLLECTION_NAME in [c.name for c in client.get_collections().collections]:
        return
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=qdrant_models.VectorParams(size=vector_size, distance=qdrant_models.Distance.COSINE),
    )

def _extract_letter_text(letter_path: Path, ignore_until: str, ignore_after: str) -> str:
    letter_content = letter_path.read_text(encoding="utf-8")
    if ignore_until:
        start_idx = letter_content.find(ignore_until)
        if start_idx != -1:
            letter_content = letter_content[start_idx:]
    if ignore_after:
        end_idx = letter_content.find(ignore_after) 
        if end_idx != -1:
            letter_content = letter_content[:end_idx]
    return letter_content.strip()

@app.command()
def refresh(
    jobs_source_folder: Path = typer.Option(Path(_env_default("JOBS_SOURCE_FOLDER", "examples")), help="Folder holding files to build the Qdrant repo."),
    letters_source_folder: Path = typer.Option(Path(_env_default("LETTERS_SOURCE_FOLDER", "examples")), help="Folder holding files to build the Qdrant repo."),
    jobs_source_suffix: str = typer.Option(_env_default("JOBS_SOURCE_SUFFIX", "txt")),
    letters_source_suffix: str = typer.Option(_env_default("LETTERS_SOURCE_SUFFIX", "tex")),
    letters_ignore_until: str = typer.Option(_env_default("LETTERS_IGNORE_UNTIL", None)),
    letters_ignore_after: str = typer.Option(_env_default("LETTERS_IGNORE_AFTER", None)),
    qdrant_host: str = typer.Option(_env_default("QDRANT_HOST", "localhost")),
    qdrant_port: int = typer.Option(int(_env_default("QDRANT_PORT", "6333"))),
    clear: bool = typer.Option(False, help="Empty the Qdrant repository before rebuilding it."),
):
    """Refreshes example repository used for retrieval augmented generation."""

    openai_client = _get_openai_client()

    client = _get_qdrant_client(qdrant_host, qdrant_port)
    if clear:
        client.delete_collection(collection_name=COLLECTION_NAME)
    _ensure_collection(client)

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
        typer.echo(f"[INFO] Processing{company_name}")

        letter_text = _extract_letter_text(letter_path, letters_ignore_until, letters_ignore_after)
    
        vector = _embed(job_text, openai_client)
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
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        typer.echo(f"[INFO] Upserted {len(points)} documents to Qdrant.")
    else:
        typer.echo("[WARN] No documents found to upsert.")


@app.command()
def process_job(
    path: Path = typer.Argument(..., help="Path to the file containing the job description."),
    cv: Path = typer.Option(Path(_env_default("CV_PATH", "cv.md")), help="Path to user's CV in text/markdown."),
    company_name: Optional[str] = typer.Option(_env_default("COMPANY_NAME"), help="Company name. Defaults to job description filename stem."),
    out: Optional[Path] = typer.Option(None, help="Output path for the generated letter."),
    openai_key: Optional[str] = typer.Option(_env_default("OPENAI_API_KEY"), help="OpenAI API key."),
    qdrant_host: str = typer.Option(_env_default("QDRANT_HOST", "localhost")),
    qdrant_port: int = typer.Option(int(_env_default("QDRANT_PORT", "6333"))),
):
    """Writes a cover letter for the given job description."""

    openai_client = _get_openai_client(openai_key)

    client = _get_qdrant_client(qdrant_host, qdrant_port)
    if COLLECTION_NAME not in [c.name for c in client.get_collections().collections]:
        typer.echo("[ERROR] Qdrant collection not found. Run 'refresh' first.")
        raise typer.Exit(code=1)

    job_text = path.read_text(encoding="utf-8")
    cv_text = cv.read_text(encoding="utf-8")
    
    # Determine company name
    if company_name is None:
        company_name = Path(path).stem

    TRACE_DIR = Path("trace", company_name)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1a: Retrieve similar job offers
    vector = _embed(job_text, openai_client)
    search_result = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=7,
    )
    retrieved_docs = [r.payload for r in search_result]
    (TRACE_DIR / "retrieved_docs.json").write_text(json.dumps(retrieved_docs, indent=2), encoding="utf-8")

    # Step 1b: Company research
    company_report = _company_research(company_name, job_text, openai_client)

    # Step 2: Intelligent evaluation
    top_docs = _rerank_documents(job_text, retrieved_docs, openai_client)

    # Step 3: Letter generation
    letter = _generate_letter(cv_text, top_docs, company_report, job_text, openai_client)

    # Output
    if out is None:
        out = Path("letters", f"{company_name}.txt")
    out.write_text(letter, encoding="utf-8")
    typer.echo(f"[INFO] Letter written to {out}")


# --- LLM helper functions --------------------------------------------------

def _chat(messages: List[dict], client: OpenAI, model: str) -> str:
    response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content.strip()


def _company_research(company_name: str, job_text: str, client: OpenAI) -> str:
    system = "You are an expert in searching the internet for information about companies."
    prompt = (
        f"Search the internet and write a short, opinionated company report about {company_name}\n"
        f"To disambiguiate, here is how they present themselves: {job_text[:500]}...\n"
        "Focus on what makes the company appealing and unique. Keep it concise but informative."
    )
    (TRACE_DIR / "company_research_prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    return _chat(messages, client, model="gpt-4o-search-preview")


def _rerank_documents(job_text: str, docs: List[dict], client: OpenAI) -> List[dict]:
    """Ask the model to score docs and return top 3."""
    # Prepare mapping of doc id -> company_name for scoring
    mapping = {i: {"company_name": d["company_name"], "job_text": d["job_text"]} for i, d in enumerate(docs)}
    mapping_json = json.dumps(mapping, indent=2)

    system = (
        "You are an expert in scoring the similarity of job descriptions to a target job description. \n\n"
        "Given the original job description and a set of other job descriptions with their company names, "
        "score each on how similar it is to the original on a scale of 1-10. \n\n"
        "Return a JSON map of letter_company_name -> score out of 10. Keep output strictly JSON.\n\n"
    )
    prompt = "Original Job Description:\n" + job_text + "\n\nOther Descriptions (JSON):\n" + mapping_json

    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    raw_scores = _chat(messages, client, model="o4-mini")

    try:
        scores = json.loads(raw_scores)
        # Convert company_name scores back to indices
        index_scores = {}
        for i, doc in enumerate(docs):
            company_name = doc["company_name"]
            index_scores[str(i)] = scores.get(company_name, 5)
    except json.JSONDecodeError:
        # Fallback: naive equal scoring
        index_scores = {str(i): 5 for i in range(len(docs))}

    # Sort by score desc, pick top 3
    ranked_indices = sorted(range(len(docs)), key=lambda i: float(index_scores.get(str(i), 0)), reverse=True)[:3]
    return [docs[i] for i in ranked_indices]


def _generate_letter(cv_text: str, examples: List[dict], company_report: str, job_text: str, client: OpenAI) -> str:
    examples_formatted = "\n\n".join(
        f"---- Example #{i+1} - {ex['company_name']} ----\n"
        f"Job Description:\n{ex['job_text']}\n\n"
        f"Cover Letter:\n{ex['letter_text']}\n\n"
        for i, ex in enumerate(examples) if ex['letter_text']
    )
    system = (
        "You are an expert cover letter writer. Using the user's CV, relevant examples of job descriptions "
        "and their corresponding cover letters, the company report, and the target job description, "
        "produce a personalized cover letter in the same style as the examples. Keep it concise (max 1 page).\n\n"
    )
    prompt = (
        "========== User CV:\n" + cv_text + "\n==========\n" +
        "========== Examples:\n" + examples_formatted + "\n==========\n" +
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Target Job Description:\n" + job_text + "\n=========="
    )
    (TRACE_DIR / "prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    return _chat(messages, client, model="o3")


if __name__ == "__main__":
    app() 