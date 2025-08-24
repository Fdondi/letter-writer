from typing import List
from pathlib import Path
from openai import OpenAI

from .config import TRACE_DIR
from .clients.base import BaseClient, ModelSize

def get_style_instructions() -> str:
    """Load style instructions from file."""
    style_file = Path(__file__).parent / "style_instructions.txt"
    try:
        return style_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Fallback to default if file doesn't exist
        return (
            "Never mention explicitly that something matches the job description, they should think that by themselves. "
            "Avoid making just a list of 'at X I did Y'. You're telling a story, the stints at specific companies are just supporting evidence for the message. "
            "Mentions of companies should mostly emerge naturally, not be the main structure (At X this, at Y that, etc).\n"
            "Follow the structure: 1. You are great 2. I am great 3. We'll be even greater together 4. Call to action. "
            "Of course, keep that structure implicit, and don't use paragraph titles.\n"
            "Whenever possible, use characters supported by LaTeX. In particular, to the extent that it's reasonable, avoid symbols like & or em-dashes. Do not double-space. "
            "If in doubt, use the version of the character that would be typed by a keyboard. For example ' and not ', or 11th and not 11ᵗʰ.\n"
        )


def company_research(company_name: str, job_text: str, client: BaseClient, trace_dir: Path) -> str:
    """Research company information using OpenAI."""
    system = "You are an expert in searching the internet for information about companies."
    prompt = (
        f"Search the internet and write a short, opinionated company report about {company_name}\n"
        f"To disambiguiate, here is how they present themselves: {job_text[:500]}...\n"
        "Focus on what makes the company appealing and unique. Keep it concise but informative. "
        "Do NOT include any links, only plain text."
    )
    result = client.call(ModelSize.LARGE, system, [prompt], search=True)
    (trace_dir / "company_research.txt").write_text(result, encoding="utf-8")
    return result

def generate_letter(cv_text: str, examples: List[dict], company_report: str, job_text: str, client: BaseClient, trace_dir: Path) -> str:
    """Generate a personalized cover letter based on CV, examples, company report, and job description."""
    examples_formatted = "\n\n".join(
        f"---- Example #{i+1} [estimated relevance: {ex['score']}/10] - {ex['company_name']} ----\n"
        f"Job Description:\n{ex['job_text']}\n\n"
        f"Cover Letter:\n{ex['letter_text']}\n\n"
        for i, ex in enumerate(examples) if ex['letter_text']
    )
    system = (
        "You are an expert cover letter writer. Using the user's CV, relevant examples of job descriptions "
        "and their corresponding cover letters, the company report, and the target job description, "
        "produce a personalized cover letter in the same style as the examples. Keep it concise (max 1 page).\n"
        "Remember to use the language of THE TARGET JOB DESCRIPTION, even if some or all of the examples might be in a different language. "
        "Use the examples at a higher level: look at style, structure, what is paid attention to, etc.\n"
        + get_style_instructions() +
        "\n\n"
    )
    prompt = (
        "========== User CV:\n" + cv_text + "\n==========\n" +
        "========== Examples:\n" + examples_formatted + "\n==========\n" +
        "========== Company Report:\n" + company_report + "\n==========\n" +
        "========== Target Job Description:\n" + job_text + "\n=========="
    )
    (trace_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    return client.call(ModelSize.XLARGE, system, [prompt])

def instruction_check(letter: str, client: BaseClient) -> str:
    """Check the letter for consistency with the instructions."""
    system = (
        "You are an expert in style and tone. Check the letter for consistency with the style instructions."
        "Be very brief, a couple of sentences is enough. It is likely the instructions were already follwed. "
        "If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== Style Instructions:\n" + get_style_instructions() + "\n==========\n\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please catch any strong inconsitency with the instructions, or output NO COMMENT"
    )
    return client.call(ModelSize.TINY, system, [prompt])


def accuracy_check(letter: str, cv_text: str, client: BaseClient) -> str:
    """Check the accuracy of the cover letter against the user's CV."""
    system = (
        "You are an expert proofreader. Check the cover letter for factual accuracy against the user's CV. "
        "Look for any claims or statements that are not supported by the CV or are inconsistent with it. "
        "Provide specific feedback on any inaccuracies found. In particular:\n"
        "1. Is what is written in the letter coherent with itself?\n"
        "Examples of incoherhence:  'I am highly expert in Go, I used it once' (using once is not enough to claim experitise), or 'I used Python libraries such as Boost' (Boost is a C++ library)\n"
        "2. Is what is written coherent with the user's CV? Is every claimed expertise supported?"
        "Also pay attention to claims not strictly about tools, they also need to be supported in some way.\n"
        "Example: 'Crypto made me a programmer' [it's a claim, it needs to be supported by the CV]\n"
        "Be especially wary of claims of a 'common thread' or 'throughout my carreer' if it's not supported by the CV.\n"
        "Be very brief, a couple of sentences is enough. If at any point you see that there is no strong negative feedback, output NO COMMENT and end the answer. \n"
    )
    prompt = (
        "========== User CV:\n" + cv_text + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for factual accuracy against the CV. "
        "Point out any claims that cannot be verified from the CV or are inconsistent with it."
    )
    return client.call(ModelSize.TINY, system, [prompt])

def precision_check(letter: str, company_report: str, job_text: str, client: BaseClient) -> str:
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
    return client.call(ModelSize.TINY, system, [prompt])

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
    return client.call(ModelSize.TINY, system, [prompt])

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
    return client.call(ModelSize.TINY, system, [prompt])

def human_check(letter: str, examples: List[dict], client: OpenAI) -> str:
    """Check the letter for consistency with the instructions."""
    rewritten_examples = [ex for ex in examples if "letter_text" in ex and "negative_letter_text" in ex]
    
    if not rewritten_examples:
        print(f"none of {', '.join(ex['company_name'] for ex in examples)} have a negative letter, skipping")
        return "NO COMMENT"

    examples_formatted = "\n\n".join(
        f"---- Example #{i+1} - {ex['company_name']} ----\n"
        f"Initial cover Letter:\n{ex['negative_letter_text']}\n\n"
        f"Revised cover Letter:\n{ex['letter_text']}\n\n"
        for i, ex in enumerate(rewritten_examples)
    )
    system = (
        "You are an expert in noticing the patterns behind edits. You will receive a list of examples of job descriptions and corresponding cover letters; "
        "first the cover letter how it was initially written, then the cover letter how a reviewer rewrote it. "
        "The reviewer might have copied parts of the initial letter, or rewrote it from scratch. Either way, pay attention to what was changed. "
        "Once you noticed what changes tend to be made, flag if in the final, new letter anything looks like a feature than the reviewer would change in the earler examples.\n"
        "Note you should NOT flag elements just for not being in the positive examples, but only if they are present in the initial examples AND usually removed in the revised ones.\n"
        "Be very brief, a couple of sentences is enough. "
        "If at any point you see that nothing in the final letter looks like something the reviewer would change, output NO COMMENT and end the answer. \n"
    )
    prompt = (  
        "========== Reference Examples:\n" + examples_formatted + "\n==========\n" +
        "========== Cover Letter to Check:\n" + letter + "\n==========\n\n" +
        "Please review the cover letter for anything that looks like something the reviewer would change, based on the examples."
    )
    return client.call(ModelSize.TINY, system, [prompt])


def rewrite_letter(
    original_letter: str,
    instruction_feedback: str,
    accuracy_feedback: str,
    precision_feedback: str,
    company_fit_feedback: str,
    user_fit_feedback: str,
    human_feedback: str,
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
    if "NO COMMENT" not in instruction_feedback:
        had_feedback = True
        prompt += "========== Instruction Feedback:\n" + instruction_feedback + "\n==========\n"
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
    if "NO COMMENT" not in human_feedback:
        had_feedback = True
        prompt += "========== Human Feedback:\n" + human_feedback + "\n==========\n"
    if not had_feedback:
        print("No feedback provided, returning original letter.")
        return original_letter
    
    prompt += (
        "Please rewrite the cover letter incorporating all the feedback. Output only the revised letter.\n"
        "ONLY address the feedback that was provided. Do not change any part of the letter except what is touched by feedback. \n"
        "Feedback is meant to call attention to specific aspects, but can be short-sighted in context. "
        "If you see that no feedback meaningfully needs to be addressed, output NO REVISIONS and end the answer.\n"
    )
    (trace_dir / "rewrite_prompt.txt").write_text(prompt, encoding="utf-8")
    revised_letter = client.call(ModelSize.XLARGE, system, [prompt])
    if "NO REVISIONS" in revised_letter:
        print("No revisions needed, returning original letter.")
        return original_letter
    return revised_letter 

def fancy_letter(letter: str, client: OpenAI) -> str:
    """Fancy up the letter with a fancy style."""
    system = (
        "You are an expert in writing cover letters. You will receive a cover letter. "
        "Keep as close to the original as possible, but spell the name of the company with the first letter of each paragraph. "
        "The first paragraph should start with the company name itself. For example:\n"
        "Apple -> 'Apple means excellence... Passion for me is... Pluses of employing me... Leading comes natural to me... Excited to contribute...' "
    )
    prompt = (
        "========== Cover Letter:\n" + letter + "\n==========\n" +
        "Please rewrite the cover letter in a more fancy style. "
    )
    return client.call(ModelSize.XLARGE, system, [prompt])

