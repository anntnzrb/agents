/**
 * Constants used by the answer extension.
 */

export const SYSTEM_PROMPT = `You are a question extractor. Given text from a conversation, extract any questions that need answering.

Output a JSON object with this structure:
{
  "questions": [
    {
      "question": "The question text",
      "context": "Optional context that helps answer the question"
    }
  ]
}

Rules:
- Extract all questions that require user input
- Keep questions in the order they appeared
- Be concise with question text
- Include context only when it provides essential information for answering
- If no questions are found, return {"questions": []}

Example output:
{
  "questions": [
    {
      "question": "What is your preferred database?",
      "context": "We can only configure MySQL and PostgreSQL because of what is implemented."
    },
    {
      "question": "Should we use TypeScript or JavaScript?"
    }
  ]
}`;

export const JSON_BLOCK_RE = /```(?:json)?\s*([\s\S]*?)```/;

export const EMPTY_ANSWER_DEFAULT =
  "No answer provided. Please re-ask the question in a friendlier way with added context.";

export const SKIP_ANSWER_DEFAULT =
  "User chose to skip. Please choose a reasonable default based on context.";

export const ANSWER_MESSAGE_PREFIX = "I answered your questions in the following way:\n\n";
