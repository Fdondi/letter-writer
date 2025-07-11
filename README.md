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

### Qdrant

Qdrant accessible; tested running locally in Docker on port 6333 (configurable)

### Source data

Job offers and correspective letters need to be either in different folders, or have different suffixes (be it file extension or name).
All the pairs which have the same name once the suffix is removed, are considered to be a valid data point.

In case the text the lettter is within boilerplate (for example, a `.tex` source file), it's possible to instruct to ignore before and after a given keyword.

## Debug 

Useful information is saved under trace/

# Commands

Commands can be specified in sequence one after the other. 

- `refresh`: refreshes example repository (default)

- `process_job <path>`: writes a letter. 
   Parameter: path to the file containing the job to write a letter for, or to the folder containing the jobs. If a folder is given, the newest file will be used. 

## Options:

### Common

- `--qdrant_host=<uri>`: URI Qdrant server is running at. Defaults to localhost.
- `--qdrant_port=<num>`: Port Qdrant server is running at. Defaults to 6333.

###  For `refresh`

-`--clear`: Empty the Qdrant repository before rebuilding it.

- `--jobs_source_folder=<Path>`: folder holding the job offers to be used to build the Qdrant repo.
- `--jobs_source_suffx=<str>`: suffix used to recognize the job offers in the folder.

- `--letters_soure_folder=<Path>`: folder holding the letters to be used as the payload of the Qdrant repo.
- `--letters_source_suffix=<str>`: suffix used to recognize the letters in the folder.

- `--letters_ignore_until=<str>`: if present, letter text will be discarded as boilerplate until the first occurrence of the string. In a `.tex` letter template, this might be `\makelettertitle`. 
- `--letters_ignore_after=<str>`: if present, letter text will be discarded as boilerplate after the first occurrence of the string. In a `.tex` letter template, this might be `\closing`. 

### For `process_job`

- `--cv=<path>`: path to the user's CV in text form; markdown recommended. Default: `cv.md`.
- `--openai_key=<key>`: OpenAI API key
- `--company_name=<str>`: company to write the letter for. If not provided, defaults to the stem of the job description filename
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