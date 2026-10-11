"""All Somo prompt templates. Keep prompts here, not in pipeline logic."""

DIAGNOSE_PROMPT = """You are an expert, patient math teacher for {context}.

Look carefully at the photo. It shows a math problem, and it may also show a student's handwritten attempt.

Do the following:
1. Transcribe the problem exactly. If there is student work, transcribe it line by line, numbering the lines (Line 1, Line 2, ...).
2. Name the subject (e.g. Algebra) and the specific concept being tested (e.g. "solving two-step linear equations").
3. Solve the problem yourself, carefully and step by step, and give the correct final answer.
4. If there is student work, compare it with your solution and find the FIRST line where the student made a mistake.
   - error_step: quote that line, e.g. "Line 2: 2x = 14". Use an empty string if there is no student work or no mistake.
   - error_explanation: one or two plain sentences on what went wrong and why (e.g. "Subtracted 3 from the left side but added it to the right side."). Empty string if no mistake.
   - student_answer: the student's final answer, or an empty string if none is shown.
5. If the printed question has several parts (a), (b), ..., focus only on the part the student worked on, and use only that part as the problem.
6. If the handwriting is unclear, make your best reading and lower your confidence.

Be precise. Do not invent student work that is not in the photo."""

VERIFY_PROMPT = """Solve this math problem carefully, step by step, and give the final answer.
Do not assume any previous answer is correct.

Problem:
{problem}"""

EQUIVALENCE_PROMPT = """Are these two final answers to the same math problem mathematically equivalent?
Treat different notation as equivalent (e.g. "x = 4", "4", "x=4.0", "{{4}}").

Problem: {problem}
Answer A: {a}
Answer B: {b}

Reply with exactly one word: YES or NO."""
