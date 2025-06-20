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
        "Focus on what makes the company appealing and unique. Keep it concise but informative. "
        "Do NOT include any links, only plain text."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    result = chat(messages, client, model="gpt-4o-search-preview")
    (trace_dir / "company_research.txt").write_text(result, encoding="utf-8")
    return result

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
        "produce a personalized cover letter in the same style as the examples. Keep it concise (max 1 page).\n"
        "Never mention explicitly that something matches the job description, they should think that by themselves. "
        "Whenever possible, use characters supported by LaTeX. "
        "To the extent that it's reasonable, avoid symbols like & or em-dashes. Do not double-space.\n\n"
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

def accuracy_check(letter: str, cv_text: str, client: OpenAI) -> str:
    """Check the accuracy of the cover letter against the user's CV."""
    system = (
        "You are an expert proofreader. Check the cover letter for factual accuracy against the user's CV. "
        "Look for any claims or statements that are not supported by the CV or are inconsistent with it. "
        "Provide specific feedback on any inaccuracies found. In particular:\n"
        "1. Is what is written in the letter coherent with itself?\n"
        "Examples of incoherhence:  'I am highly expert in Go, I used it once' (using once is not enough to claim experitise), or 'I used Python libraries such as Boost' (Boost is a C++ library)\n"
        "2. Is what is written coherent with the user's CV? Is every claimed expertise supported?"
        "Also pay attention to claims not strinctly about tools, they also need to be supported in some way.\n"
        "Example: 'Crypto made me a programmer' [it's a claim, it needs to be supported by the CV]\n"
        "Be very brief, a couple of sentences is enough. If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== User CV:\n" + cv_text + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for factual accuracy against the CV. "
        "Point out any claims that cannot be verified from the CV or are inconsistent with it."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    feedback = chat(messages, client, model="gpt-4o")
    return feedback

def precision_check(letter: str, company_report: str, job_text: str, client: OpenAI) -> str:
    """Check the precision and style of the cover letter against the company report and job description."""
    system = (
        "You are a senior HR manager at the company. Evaluate how well the cover letter addresses the needs of the company, as described in the company report and job description. "
        "1. Were all the requests in the letter addressed, either by claiming and substantiating the necessary competence, or a reasonably substitutable one, or at least ability and willingness to learn in this specific field?\n"
        "Example: 'required: Python, GO' -> 'I have several years of Python experience' [GO is missing]\n"
        "Example: 'required: GO' -> 'while I have not used GO professionally, I have 5 years of C++ experience, and I have follwed a course on GO. When I tried GO on LeetCode, it was easy for me to use' [OK, demonstrates ability to learn]\n"  
        "2. Is there on the contrary any claimed competence that really is superflous, does not adress the explicit or implicit requirements for the job or the company, to the point it makes you wonder if the person understands the job at all?\n"
        "Example: 'we look for a C++ developer' -> 'I have trained several AI models'\n"
        "3. Is there any claim about the company that is not supported by the company report or company information presented in the job offer; or even if it is technically supported, is presented in a way that makes you suspect the writer doesn't understand the company?\n"
        "Example: the company entered crypto last year -> 'excited to apply to a company that has been a pioneer in crypto since its origin' [incorrect, user clearly didn't follow the company for long]\n"
        "Example: the company originated in the F1 racing world, but has pivoted to banking and not worked in racing in a while -> 'excited to enter the world of racing [user is either not up to date on the company, or making up misinterpreting partial information]\n"
        "Be very brief, a couple of sentences is enough. If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Job Offer:\n" + job_text + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for consistency with the company report and job description. "
        "Provide specific feedback on how to better align with the company's needs."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    feedback = chat(messages, client, model="gpt-4.1-mini")
    return feedback

def company_fit_check(letter: str, company_report: str, job_offer: str, client: OpenAI) -> str:
    """Check how well the cover letter aligns with the company's values, culture, tone, and needs."""
    system = (
        "You are a senior HR manager at the company. Evaluate how well the cover letter "
        "demonstrates understanding of and alignment with the company's values, mission, tone, and culture "
        "as described in the company report and implied by the job offer.\n"
        "Does the letter feel like it's written for the company? "
        "Does it feel generic, or written with understadnding ad care for what the company does, values, and needs? "
        "Be very brief, a couple of sentences is enough. If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Job Offer:\n" + job_offer + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for alignment with the company's values, tone, and culture. "
        "Provide feedback on how to better demonstrate understanding of and fit with the company. "
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    feedback = chat(messages, client, model="gpt-4.1-mini")
    return feedback

def user_fit_check(letter: str, examples: List[dict], client: OpenAI) -> str:
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
        "Be very brief, a couple of sentences is enough. If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== Reference Examples:\n" + examples_formatted + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for effectiveness in adhering to the style and tone of the previous examples."
        "Provide feedback on how to improve the letter to better match the previous examples."
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    feedback = chat(messages, client, model="gpt-4.1-mini")
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
        "its core message and keeping it concise (max 1 page).\n"
    )
    had_feedback = False
    prompt = "========== Original Cover Letter:\n" + original_letter + "\n==========\n"
    if "NO COMMENT" not in accuracy_feedback:
        had_feedback = True
        prompt += "========== Accuracy Feedback:\n" + accuracy_feedback + "\n==========\n"
    if "NO COMMENT" not in precision_feedback:
        had_feedback = True
        prompt += "========== Precision Feedback:\n" + precision_feedback + "\n==========\n"
    if "NO COMMENT" not in company_fit_feedback:
        had_feedback = True
        prompt += "========== Company Fit Feedback:\n" + company_fit_feedback + "\n==========\n"
    if "NO COMMENT" not in user_fit_feedback:
        had_feedback = True
        prompt += "========== User Fit Feedback:\n" + user_fit_feedback + "\n==========\n"
    if not had_feedback:
        print("No feedback provided, returning original letter.")
        return original_letter
    
    prompt += (
        "Please rewrite the cover letter incorporating all the feedback. Output only the revised letter.\n"
        "ONLY address the feedback that was provided. Do not change any part of the letter except what is touched by feedback. \n"
    )
    (trace_dir / "rewrite_prompt.txt").write_text(prompt, encoding="utf-8")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    revised_letter = chat(messages, client, model="o3")
    (trace_dir / "final_letter.txt").write_text(revised_letter, encoding="utf-8")
    return revised_letter 