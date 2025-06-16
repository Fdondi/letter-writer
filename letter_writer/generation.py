from typing import List
from pathlib import Path
from openai import OpenAI

from .config import TRACE_DIR

def chat(messages: List[dict], client: OpenAI, model: str) -> str:
    """Make a chat completion request to OpenAI."""
    response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content.strip()

def company_research(company_name: str, job_text: str, client: OpenAI, trace_dir: Path) -> str:
    """Research company information using OpenAI."""
    system = "You are an expert in searching the internet for information about companies."
    prompt = (
        f"Search the internet and write a short, opinionated company report about {company_name}\n"
        f"To disambiguiate, here is how they present themselves: {job_text[:500]}...\n"
        "Focus on what makes the company appealing and unique. Keep it concise but informative."
    )
    (trace_dir / "company_research_prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    return chat(messages, client, model="gpt-4o-search-preview")

def generate_letter(cv_text: str, examples: List[dict], company_report: str, job_text: str, client: OpenAI, trace_dir: Path) -> str:
    """Generate a personalized cover letter based on CV, examples, company report, and job description."""
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
    (trace_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    return chat(messages, client, model="o3")

def accuracy_check(letter: str, cv_text: str, client: OpenAI, trace_dir: Path) -> str:
    """Check the accuracy of the cover letter against the user's CV."""
    system = (
        "You are an expert proofreader. Check the cover letter for factual accuracy against the user's CV. "
        "Look for any claims or statements that are not supported by the CV or are inconsistent with it. "
        "Provide specific feedback on any inaccuracies found. In particular:\n"
        "1. Is what is written in the letter coherent with itself?\n"
        "Examples of incoherhence:  'I am highly expert in Go, I used it once' (using once is not enough to claim experitise), or 'I used Python libraries such as Boost' (Boost is a C++ library)\n"
        "2. Is what is written coherent with the user's CV? Is every claimed expertise supported?\n"
    )
    prompt = (
        "========== User CV:\n" + cv_text + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for factual accuracy against the CV. "
        "Point out any claims that cannot be verified from the CV or are inconsistent with it."
    )
    (trace_dir / "accuracy_check_prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    feedback = chat(messages, client, model="gpt-4o")
    (trace_dir / "accuracy_feedback.txt").write_text(feedback, encoding="utf-8")
    return feedback

def precision_check(letter: str, company_report: str, job_text: str, client: OpenAI, trace_dir: Path) -> str:
    """Check the precision and style of the cover letter against the company report and job description."""
    system = (
        "You are a senior HR manager at the company. Evaluate how well the cover letter addresses the needs of the company, as described in the company report and job description. "
        "1. Were all the requests in the letter addressed, either by claiming and substantiating the necessary competence, or a reasonably substitutable one, or at least ability and willingness to learn in this specific field?\n"
        "Example: 'required: Python, GO' -> 'I have several years of Python experience' [GO is missing]\n"
        "Example: 'required: GO' -> 'while I have not used GO professionally, I have 5 years of C++ experience, and I have follwed a course on GO. When I tried GO on LeetCode, it was easy for me to use' [OK, demonstrates ability to learn]\n"  
        "2. Is there on the contrary any claimed competence that really is superflous, does not adress the explicit or implicit requirements for the job or the company, to the point it makes you wonder if the person understands the job at all?\n"
        "Example: 'we look for a C++ developer' -> 'I have trained several AI models'\n"
    )
    prompt = (
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Job Offer:\n" + job_text + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for consistency with the company report and job description. "
        "Provide specific feedback on how to better align with the company's needs."
    )
    (trace_dir / "precision_check_prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    feedback = chat(messages, client, model="gpt-4.1-mini")
    (trace_dir / "precision_feedback.txt").write_text(feedback, encoding="utf-8")
    return feedback

def company_fit_check(letter: str, company_report: str, job_offer: str, client: OpenAI, trace_dir: Path) -> str:
    """Check how well the cover letter aligns with the company's values, culture, tone, and needs."""
    system = (
        "You are a senior HR manager at the company. Evaluate how well the cover letter "
        "demonstrates understanding of and alignment with the company's values, mission, tone, and culture "
        "as described in the company report and implied by the job offer.\n"
        "Does the letter feel like it's written for the company? "
        "Does it feel generic, or written with understadnding ad care for what the company does, values, and needs? "
    )
    prompt = (
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Job Offer:\n" + job_offer + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for alignment with the company's values, tone, and culture. "
        "Provide feedback on how to better demonstrate understanding of and fit with the company. "
    )
    (trace_dir / "company_fit_check_prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    feedback = chat(messages, client, model="gpt-4.1-mini")
    (trace_dir / "company_fit_feedback.txt").write_text(feedback, encoding="utf-8")
    return feedback

def user_fit_check(letter: str, examples: List[dict], client: OpenAI, trace_dir: Path) -> str:
    """Check how well the cover letter showcases the user's unique value proposition."""
    examples_formatted = "\n\n".join(
        f"---- Example #{i+1} - {ex['company_name']} ----\n"
        f"Cover Letter:\n{ex['letter_text']}\n\n"
        for i, ex in enumerate(examples) if ex['letter_text']
    )
    system = (
        "You are an expert in style and tone. Evaluate how well the cover letter follws the pattern of the previous examples. \n"
        "Does the last letter match the previous ones? Does it look like it's written by the same hand? \n"
        "Does it pay attention to the same aspects? Does it highlight strengths and negotiate weaknesses in the same way? \n"
    )
    prompt = (
        "========== Reference Examples:\n" + examples_formatted + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for effectiveness in adhering to the style and tone of the previous examples."
        "Provide feedback on how to improve the letter to better match the previous examples."
    )
    (trace_dir / "user_fit_check_prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    feedback = chat(messages, client, model="gpt-4.1-mini")
    (trace_dir / "user_fit_feedback.txt").write_text(feedback, encoding="utf-8")
    return feedback

def rewrite_letter(
    original_letter: str,
    accuracy_feedback: str,
    precision_feedback: str,
    company_fit_feedback: str,
    user_fit_feedback: str,
    client: OpenAI,
    trace_dir: Path
) -> str:
    """Rewrite the cover letter incorporating all feedback."""
    system = (
        "You are an expert cover letter editor. Given an original cover letter and multiple "
        "pieces of feedback, rewrite the letter to address all concerns while maintaining "
        "its core message and keeping it concise (max 1 page)."
    )
    prompt = (
        "========== Original Cover Letter:\n" + original_letter + "\n==========\n" +
        "========== Accuracy Feedback:\n" + accuracy_feedback + "\n==========\n" +
        "========== Precision Feedback:\n" + precision_feedback + "\n==========\n" +
        "========== Company Fit Feedback:\n" + company_fit_feedback + "\n==========\n" +
        "========== User Fit Feedback:\n" + user_fit_feedback + "\n==========\n\n" +
        "Please rewrite the cover letter incorporating all the feedback while maintaining "
        "clarity, conciseness, and professional tone. Output only the revised letter."
    )
    (trace_dir / "rewrite_prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    revised_letter = chat(messages, client, model="o3")
    (trace_dir / "final_letter.txt").write_text(revised_letter, encoding="utf-8")
    return revised_letter 