/** Feedback type descriptions for tooltips (based on actual prompts in generation.py). */
export const FEEDBACK_DESCRIPTIONS = {
  'instruction': 'Checks the letter for consistency with the style instructions. Flags any strong inconsistencies with the specified writing style and tone.',
  'instruction_feedback': 'Checks the letter for consistency with the style instructions. Flags any strong inconsistencies with the specified writing style and tone.',
  'accuracy': 'Verifies factual accuracy against your CV. Checks if claims are coherent with themselves and supported by your CV. Flags unsupported expertise claims or inconsistencies.',
  'accuracy_feedback': 'Verifies factual accuracy against your CV. Checks if claims are coherent with themselves and supported by your CV. Flags unsupported expertise claims or inconsistencies.',
  'precision': 'Evaluates how well the letter addresses job requirements. Checks if all required competencies are addressed (or substituted), flags superfluous claims, and verifies company-related claims match the company report.',
  'precision_feedback': 'Evaluates how well the letter addresses job requirements. Checks if all required competencies are addressed (or substituted), flags superfluous claims, and verifies company-related claims match the company report.',
  'company_fit': 'Assesses alignment with the company\'s values, mission, tone, and culture. Checks if the letter feels personalized for the company rather than generic.',
  'company_fit_feedback': 'Assesses alignment with the company\'s values, mission, tone, and culture. Checks if the letter feels personalized for the company rather than generic.',
  'user_fit': 'Compares the letter to your previous cover letters for voice and habits (same-hand cues): tone, structure, how strengths and caveats are framed—not the same topics or facts as older letters.',
  'user_fit_feedback': 'Compares the letter to your previous cover letters for voice and habits (same-hand cues): tone, structure, how strengths and caveats are framed—not the same topics or facts as older letters.',
  'human': 'Analyzes patterns from your previous letter revisions. Flags elements that were typically changed or removed in your past edits, based on your review history.',
  'human_feedback': 'Analyzes patterns from your previous letter revisions. Flags elements that were typically changed or removed in your past edits, based on your review history.',
};
