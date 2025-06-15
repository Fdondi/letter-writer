Cover letter customizator. 

# Usage

## Prerequisite 

Qdrant running in Docker; by default on port 6333 (configurable)

## Debug 

Useful information is saved under trace/

# Commands

Commands can be specified in sequence one after the other. 

- `refresh`: refreshes example repository (default)

- `process_job <path>`: writes a letter. Parameter: path to the file containing the job to write a letter for.

## Options:

### Common

- `--qdrant_host=<uri>`: URI Qdrant server is running at. Defaults to localhost.
- `--qdrant_port=<num>`: Port Qdrant server is running at. Defaults to 6333.

###  For `refresh`

- `--qdrant_source_folder=<Path>`: folder holding the files to use to build the Qdrant repo. Defaults to `examples`.
                                   the original job descritions are in files names `<company_name>.txt`
                                   the letters are in files named `<conpany_name>.tex`, with the text contained between `\makelettertitle`and `\closing`.

### For `process_job`

- `--cv=<path>`: path to the user's CV in text form; markdown recommended. Default: `cv.md`.
- `--openai_key=<key>`: OpenAI API key
- `--company_name=<str>`: company to write the letter for. If not provided, defaults to the stem of the job description filename
- `--out=<path>`: Path to write the letter to. Defaults to `letters/<company_name>.txt`.

## Config File:

All flags can be set through envronment variables (if not needed for the current command they will just be ignored).
Environment variables can be in turn set through an .env file, `load_dotenv()` will be called.

# Details: 

The pipeline uses existing examples to guide the model to write cover letters in the style of the existing ones. This happens in various stages:

## 1a. RAG

RAG with Qdrant is used to retrieve the top 7 most similar job offers for which a letter was already written. 

## 1b. Rechearch

The LLM is given the company_name only and asked to search the internet to write a short report on the company.
Model to use: gpt-4o-search-preview

## 2. Intellgent evaluation

The LLM is presented with the company report, the original job offer, and the retrieved documents; it then scores the documents on actual similarity to the original job offer.
The top 3 advance.

Given the recent price drop, we can use: o4-mini.
Because it's a resoning model, we should not need to try and trick the model into thinking about it by requesting a justification. We can just ask a Pydantic map lette_company_name -> score out of 10. 

## 3.

The LLM is presented with:
- The user's CV
- The 3 selected examples of job_description -> letter
- The company report
- The target job description
and is asked to write a letter for the target job description.
Model to use: o3.