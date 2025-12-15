Cover letter customizator. 

# Usage

## Prerequisite 

### Python environment

pip install -r requirements.txt

### API Keys

Set up the required API keys as environment variables (or in a `.env` file):

- `OPENAI_API_KEY`: Required for OpenAI models
- `ANTHROPIC_API_KEY`: Required for Claude/Anthropic models  
- `GOOGLE_API_KEY`: Required for Gemini models
- `MISTRAL_API_KEY`: Required for Mistral models (optional)
- `XAI_API_KEY`: Required for Grok models (optional)

### CV File

The application needs access to your CV file. Configure it by setting `CV_PATH` in your `.env` file.

**For Docker users**: 

The `docker-compose.yml` file automatically overrides `CV_PATH` to use the Docker-appropriate path (`cv-external/Experience.md`), so you don't need to change your `.env` file. The CV directory is mounted at `/app/cv-external` in the container.

If your CV is in a different location, update the volume mount and `CV_PATH` environment variable in `docker-compose.yml`.

**For local users**: You can use either a relative or absolute path:

```
CV_PATH=cv.md
```

Or:
```
CV_PATH=C:/path/to/your/cv.md
```

**Important**: 
- **In Docker**: The path must be relative to the project root (the entire project is mounted at `/app`). If your CV is outside the project directory, you need to either:
  1. Copy it into the project directory, or
  2. Mount the external directory in `docker-compose.yml` and use a path relative to that mount point
- Make sure the file exists at the specified path
- Use forward slashes `/` in paths (works on both Windows and Linux)

The default is `cv.md` in the project root if `CV_PATH` is not set.

**Note**: The web interface currently uses the CV file from `CV_PATH`. To use a different CV, update the `.env` file and restart the backend.

### Qdrant

Qdrant accessible; tested running locally in Docker on port 6333 (configurable)

### Source data

Job offers and correspective letters need to be either in different folders, or have different suffixes (be it file extension or name).
All the pairs which have the same name once the suffix is removed, are considered to be a valid data point.

In case the text the lettter is within boilerplate (for example, a `.tex` source file), it's possible to instruct to ignore before and after a given keyword.

## Running the Application

The application consists of a Django backend, a React frontend, and Qdrant vector database. You can run them either locally or using Docker.

### Option 1: Using Docker (Recommended)

The easiest way to run the entire application stack is using Docker Compose:

```bash
docker-compose up
```

This will start:
- **Qdrant** vector database on port `6333` (uses your existing data volume)
- **Django backend** on port `8000`
- **React frontend** on port `5173`

**Note**: The docker-compose configuration uses your existing Qdrant data volume (`letter-writer_qdrant_storage`). If you've already initialized Qdrant with your data, it will be available immediately. If you need to stop your existing Qdrant container first, you can do so - docker-compose will start a new one using the same data.

To run in detached mode (background):

```bash
docker-compose up -d
```

To stop all services:

```bash
docker-compose down
```

To rebuild containers after code changes:

```bash
docker-compose up --build
```

**Troubleshooting**: If backend or frontend don't start automatically:
- Check logs: `docker-compose logs backend` or `docker-compose logs frontend`
- The backend waits for Qdrant to be healthy before starting (this can take 30-60 seconds)
- If services are stopped, they will auto-restart due to `restart: unless-stopped` policy
- To start all services: `docker-compose up -d` (runs in background)

**Note**: Make sure your `.env` file is in the project root with all required API keys (see Prerequisites section).

#### Initializing Qdrant Collection

**Important**: The docker-compose setup uses the Qdrant data volume `letter-writer_qdrant_storage`. If you've already initialized Qdrant with your data in this volume, it will be available immediately.

**If you get "Qdrant collection not found" error**: This means the collection is empty and needs to be initialized. Run the refresh command below to populate it with your job offers and letters. This is a one-time setup (or whenever you add new examples).

**To check if your collection exists**, you can query Qdrant:
```bash
curl http://localhost:6333/collections
```

If the `job_offers` collection is not listed, you need to run refresh.

**Option A: Using the API (Recommended)**

Make a POST request to the refresh endpoint. Paths are relative to the project root (mounted at `/app` in the container). The Qdrant connection will use the default service name:

```bash
curl -X POST http://localhost:8000/api/refresh/ -H "Content-Type: application/json" -d "{\"jobs_source_folder\": \"jobs\", \"jobs_source_suffix\": \".txt\", \"letters_source_folder\": \"letters\", \"letters_source_suffix\": \".txt\"}"
```

**Option B: Using the CLI inside Docker**

Execute the refresh command inside the backend container. Paths are relative to `/app`. The Qdrant connection will use the service name `qdrant`:

```bash
docker-compose exec backend python -m letter_writer refresh --jobs-source-folder jobs --jobs-source-suffix .txt --letters-source-folder letters --letters-source-suffix .txt --qdrant-host qdrant --qdrant-port 6333
```

**Note**: The docker-compose setup uses your existing Qdrant data volume, so your initialized collection will be available. If you need to customize the Qdrant connection, you can set `QDRANT_HOST` and `QDRANT_PORT` in your `.env` file.

**Note**: Adjust the folder paths and suffixes according to your actual data structure. The default expects `examples/` folder with `.txt` jobs and `.tex` letters, but you can customize these paths.

### Option 2: Running Locally

#### Prerequisites

- Python 3.11+ installed
- Node.js 20+ installed
- Qdrant running (see Qdrant section below)

#### Backend (Django)

From the project root directory, run:

```bash
python letter_writer_server/manage.py runserver
```

The backend will start on `http://localhost:8000` by default.

#### Frontend (React/Vite)

First, install Node.js dependencies (if not already done):

```bash
cd letter_writer_web
npm install
```

Then start the development server:

```bash
npm run dev
```

The frontend will start on `http://localhost:5173` by default. The Vite dev server is configured to proxy API requests from `/api` to the Django backend at `http://localhost:8000`.

#### Qdrant (Local)

If not using Docker, you can run Qdrant locally:

```bash
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

#### Initializing Qdrant Collection (Local)

After starting Qdrant, populate it with your data using the CLI:

```bash
python -m letter_writer refresh --jobs-source-folder jobs --jobs-source-suffix .txt --letters-source-folder letters --letters-source-suffix .txt
```

Or use the API endpoint at `http://localhost:8000/api/refresh/` with a POST request (see Docker section above for the JSON format).

### Accessing the Application

Once all services are running, open your browser and navigate to:
- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000/api/`
- Qdrant Dashboard: `http://localhost:6333/dashboard` (if using Docker)

## Debug 

Useful information is saved under trace/

# Commands

Commands can be specified in sequence one after the other. 

- `refresh`: refreshes example repository (default)

- `process_job <path>`: writes a letter. 
   Parameter: path to the file containing the job to write a letter for, or to the folder containing the jobs. If a folder is given, the newest file will be used. 

## Options:

### Common

- `--qdrant-host=<uri>`: URI Qdrant server is running at. Defaults to localhost.
- `--qdrant-port=<num>`: Port Qdrant server is running at. Defaults to 6333.

###  For `refresh`

-`--clear`: Empty the Qdrant repository before rebuilding it.

- `--jobs-source-folder=<Path>`: folder holding the job offers to be used to build the Qdrant repo.
- `--jobs-source-suffix=<str>`: suffix used to recognize the job offers in the folder.

- `--letters-source-folder=<Path>`: folder holding the letters to be used as the payload of the Qdrant repo.
- `--letters-source-suffix=<str>`: suffix used to recognize the letters in the folder.

- `--letters-ignore-until=<str>`: if present, letter text will be discarded as boilerplate until the first occurrence of the string. In a `.tex` letter template, this might be `\makelettertitle`. 
- `--letters-ignore-after=<str>`: if present, letter text will be discarded as boilerplate after the first occurrence of the string. In a `.tex` letter template, this might be `\closing`. 

### For `process_job`

- `--cv=<path>`: path to the user's CV in text form; markdown recommended. Default: `cv.md`.
- `--openai-key=<key>`: OpenAI API key
- `--company-name=<str>`: company to write the letter for. If not provided, defaults to the stem of the job description filename
- `--refine=<bool>`: Whether to try to improve the letter through feedback. 
- `--out=<path>`: Path to write the letter to. Defaults to `letters/<company_name>.txt`.

## Config File:

All flags can be set through envronment variables (if not needed for the current command they will just be ignored).
Environment variables can be in turn set through an .env file, `load_dotenv()` will be called.

# Details: 

The pipeline uses existing examples to guide the model to write cover letters in the style of the existing ones. This happens in various stages:

## 1. Preliminary research
### 1a. Similar example retrieval

#### 1a.I RAG

RAG with Qdrant is used to retrieve the top 7 most similar job offers for which a letter was already written. 

#### 1a.II Intellgent evaluation

The LLM is presented with the company report, the original job offer, and the retrieved documents; it then scores the documents on actual similarity to the original job offer.
The top 3 advance.

Given the recent price drop, we can use: o4-mini.
Because it's a resoning model, we should not need to try and trick the model into thinking about it by requesting a justification. We can just ask a Pydantic map lette_company_name -> score out of 10. 

### 1b. Web research

The LLM is given the company_name + the start of the job offer (which usually presents the company, for disambiguation) and asked to search the internet to write a short report on the company.
Model to use: gpt-4o-search-preview

## 2. Writing the letter

The LLM is presented with:
- The user's CV
- The 3 selected examples of job_description -> letter
- The company report
- The target job description
and is asked to write a letter for the target job description.
Model to use: o3.

## 3. Feedback
Model to use: 4.1-mini -we focus on fewer documents so context isn't an issue, and we want to not worry about price to do as many checks as needed.

###  3a. Accuracy check

The LLM is presented with:
- The user's CV
- The written letter

And is asked:
1. Is what is written in the letter coherent with itself? 
Examples of incoherhence:  "I am highly expert in Go, I used it once" (using once is not enough to claim experitise), or "I used Python libraries such as Boost" (Boost is a C++ library)
2. Is what is written coherent with the user's CV? Is every claimed expertise supported? 

### 3b. Precision check

The LLM is presented with:
- The job offer
- the company research
- The written letter
is given the persona of the HR person who will evaulate the letter,
and is asked:
1. Were all the requests in the letter addressed, either by claiming and substantiating the necessary competence, or a reasonably substitutable one, or at least ability and willingness to learn in this specific field?
    Example: "required: Python, GO" -> "I have several years of Python experience" [GO is missing]
    Example: "rquired: GO" -> "while I have not used GO professionally, I have 5 years of C++ experience, and I have follwed a course on GO. When I tried GO on LeetCode, it was easy for me to use" [OK, demonstrates ability to learn]  
2. Is there on the contrary any claimed competence that really is superflous, does not adress the explicit or implicit requirements for the job or the company, to the point it makes you wonder if the person understands the job at all?
   Example: "we look for a C++ developer" -> "I have trained several AI models"

### 3c. Company fit
The LLM is presented with:
- The job offer
- the company research
- The written letter
is given the persona of the HR person who will evaulate the letter,
and is asked:
Does this letter match the style and tone of the company? Does it feel generic, or written for them?

### 3c. User fit
The LLM is presented with:
- The letters from the top examples
- The written letter
And asked:
Does the last letter match the previous ones? Does it look like it's written by the same hand? Does it pay attention to the same aspects? Does it highlight strengths and negotiate weaknesses in the same way? 

## 4 Rewrite

The LLM is presented with the letter and the feedbacks from the previous stages, and is asked to make any necesary adjustments. 