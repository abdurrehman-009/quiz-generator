
import json
import re
import streamlit as st
from google import genai
from google.genai import types
from supabase import create_client

# ==================================================
# PAGE CONFIGURATION
# ==================================================

st.set_page_config(
    page_title="QuizCraft AI",
    page_icon="📝",
    layout="wide"
)

MODEL_NAME = "gemini-2.5-flash"
# or the cheaper one:
# MODEL_NAME = "gemini-2.5-flash-lite"
TOTAL_QUESTIONS = 20
MAX_PDF_SIZE = 20 * 1024 * 1024

# ==================================================
# DESIGN
# ==================================================

st.markdown("""
<style>
    .block-container {
        max-width: 1050px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    .hero {
        background: linear-gradient(120deg, #172554, #4338ca);
        padding: 30px;
        border-radius: 18px;
        color: white;
        margin-bottom: 25px;
    }

    .hero h1 {
        color: white;
        font-size: 38px;
    }

    .hero p {
        color: #e0e7ff;
        font-size: 16px;
    }

    div.stButton > button {
        border-radius: 10px;
        font-weight: 600;
        min-height: 42px;
    }
</style>
""", unsafe_allow_html=True)

# ==================================================
# SECRETS
# ==================================================

def get_secret(name):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def get_gemini_client():
    api_key = get_secret("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is missing. Add it to Streamlit Secrets."
        )

    return genai.Client(api_key=api_key)


def get_supabase_client():
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_KEY")

    if not url or not key:
        return None

    return create_client(url, key)


# ==================================================
# GENERATE QUIZ FROM PDF
# ==================================================

def generate_quiz(pdf_bytes, difficulty):

    client = get_gemini_client()

    pdf_part = types.Part.from_bytes(
        data=pdf_bytes,
        mime_type="application/pdf"
    )

    prompt = f"""
You are an expert educational quiz generator.

Read the attached PDF and create exactly 20 distinct
multiple-choice questions using the PDF as your source.

Difficulty: {difficulty}

Requirements:
- Use information supported by the PDF.
- Write clear questions in simple English.
- Include exactly four options for every question.
- Exactly one option must be correct.
- Cover different important topics in the PDF.
- Do not repeat questions.
- Include a short explanation for each answer.
- Do not invent information.
- If the document cannot support 20 meaningful questions,
  return an error object instead of inventing content.

Return ONLY valid JSON in this structure:

{{
  "title": "Quiz title",
  "questions": [
    {{
      "question": "Question text",
      "options": [
        "Option one",
        "Option two",
        "Option three",
        "Option four"
      ],
      "answer": 0,
      "explanation": "Explanation based on the PDF"
    }}
  ]
}}

The answer must be an integer from 0 to 3.
The questions array must contain exactly 20 questions.
Do not include Markdown fences or text outside the JSON.
"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[prompt, pdf_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
            max_output_tokens=12000
        )
    )

    if not response.text:
        raise ValueError(
            "Gemini returned an empty response. Try again."
        )

    raw_text = response.text.strip()

    raw_text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        raw_text,
        flags=re.IGNORECASE
    )

    try:
        quiz = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ValueError(
            "Gemini did not return valid JSON. Try generating again."
        ) from error

    if not isinstance(quiz, dict):
        raise ValueError("The generated quiz has an invalid format.")

    if quiz.get("error"):
        raise ValueError(str(quiz["error"]))

    questions = quiz.get("questions")

    if not isinstance(questions, list):
        raise ValueError("The quiz is missing its questions list.")

    if len(questions) != TOTAL_QUESTIONS:
        raise ValueError(
            f"Gemini generated {len(questions)} questions instead "
            "of 20. Try a longer or more detailed PDF."
        )

    for number, item in enumerate(questions, start=1):

        if not isinstance(item, dict):
            raise ValueError(f"Question {number} has an invalid format.")

        if not isinstance(item.get("question"), str):
            raise ValueError(f"Question {number} has no question text.")

        options = item.get("options")

        if (
            not isinstance(options, list)
            or len(options) != 4
            or not all(
                isinstance(option, str) and option.strip()
                for option in options
            )
        ):
            raise ValueError(
                f"Question {number} must have four non-empty options."
            )

        answer = item.get("answer")

        if type(answer) is not int or answer not in range(4):
            raise ValueError(
                f"Question {number} has an invalid answer index."
            )

        if not isinstance(item.get("explanation"), str):
            raise ValueError(
                f"Question {number} has no explanation."
            )

    quiz["title"] = str(quiz.get("title") or "Your PDF Quiz")

    return quiz


# ==================================================
# SAVE RESULTS TO SUPABASE
# ==================================================

def save_result(pdf_name, quiz, answers, score, difficulty):

    database = get_supabase_client()

    if database is None:
        return False, (
            "Supabase is not configured. Add SUPABASE_URL and "
            "SUPABASE_KEY to Streamlit Secrets."
        )

    record = {
        "pdf_name": pdf_name,
        "score": score,
        "total_questions": TOTAL_QUESTIONS,
        "questions": quiz["questions"],
        "user_answers": answers,
        "difficulty": difficulty
    }

    database.table("quiz_results").insert(record).execute()

    return True, "Your quiz result was saved."


# ==================================================
# SESSION STATE
# ==================================================

defaults = {
    "quiz": None,
    "pdf_name": None,
    "difficulty": "Medium",
    "submitted": False,
    "answers": {},
    "score": None,
    "saved": False
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ==================================================
# HEADER
# ==================================================

st.markdown("""
<div class="hero">
    <h1>QuizCraft AI</h1>
    <p>Turn your study PDFs into interactive quizzes.</p>
    <p>Powered by Gemini AI and Supabase</p>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Create a quiz")
    st.write(
        "Upload your notes or textbook PDF. "
        "Gemini will generate 20 multiple-choice questions."
    )

with col2:
    st.metric("Questions per quiz", TOTAL_QUESTIONS)
    st.metric("Options per question", 4)


# ==================================================
# PDF UPLOAD
# ==================================================

uploaded_pdf = st.file_uploader(
    "Upload your PDF document",
    type=["pdf"],
    help="Choose a readable PDF under 20 MB."
)

difficulty = st.selectbox(
    "Select difficulty",
    ["Easy", "Medium", "Hard"],
    index=1
)

if uploaded_pdf is not None:
    st.info(
        f"Selected: {uploaded_pdf.name} "
        f"({uploaded_pdf.size / 1024:.1f} KB)"
    )

    if uploaded_pdf.size > MAX_PDF_SIZE:
        st.error("Your PDF is too large. Maximum size is 20 MB.")

    elif uploaded_pdf.size == 0:
        st.error("The uploaded PDF is empty.")

    elif not uploaded_pdf.getvalue().startswith(b"%PDF-"):
        st.error("This file does not appear to be a valid PDF.")


generate_disabled = (
    uploaded_pdf is None
    or uploaded_pdf.size == 0
    or uploaded_pdf.size > MAX_PDF_SIZE
    or not uploaded_pdf.getvalue().startswith(b"%PDF-")
)

if st.button(
    "Generate 20 Questions",
    type="primary",
    use_container_width=True,
    disabled=generate_disabled
):

    with st.spinner(
        "Gemini is reading your PDF and preparing your quiz..."
    ):
        try:
            quiz = generate_quiz(
                uploaded_pdf.getvalue(),
                difficulty
            )

            st.session_state.quiz = quiz
            st.session_state.pdf_name = uploaded_pdf.name
            st.session_state.difficulty = difficulty
            st.session_state.submitted = False
            st.session_state.answers = {}
            st.session_state.score = None
            st.session_state.saved = False

            st.rerun()

        except Exception as error:
            st.error("Quiz generation failed.")
            st.exception(error)


# ==================================================
# DISPLAY QUIZ
# ==================================================

quiz = st.session_state.quiz

if quiz:

    st.divider()
    st.subheader(quiz["title"])

    st.caption(
        f"PDF: {st.session_state.pdf_name} | "
        f"Difficulty: {st.session_state.difficulty} | "
        f"Questions: {TOTAL_QUESTIONS}"
    )

    if not st.session_state.submitted:

        with st.form("quiz_form"):

            selected_answers = {}

            for index, question in enumerate(quiz["questions"]):

                st.markdown(f"### Question {index + 1}")
                st.write(question["question"])

                selected_answers[str(index)] = st.radio(
                    "Select one answer",
                    options=[0, 1, 2, 3],
                    format_func=lambda option, opts=question["options"]:
                        f"{chr(65 + option)}. {opts[option]}",
                    index=None,
                    key=f"question_{index}",
                    label_visibility="collapsed"
                )

                st.divider()

            submitted = st.form_submit_button(
                "Submit Quiz",
                type="primary",
                use_container_width=True
            )

        if submitted:

            unanswered = [
                key for key, value in selected_answers.items()
                if value is None
            ]

            if unanswered:
                st.warning(
                    f"Please answer all 20 questions. "
                    f"{len(unanswered)} question(s) remain unanswered."
                )

            else:
                score = sum(
                    selected_answers[str(index)] == question["answer"]
                    for index, question in enumerate(quiz["questions"])
                )

                st.session_state.answers = {
                    key: int(value)
                    for key, value in selected_answers.items()
                }

                st.session_state.score = int(score)
                st.session_state.submitted = True

                st.rerun()


# ==================================================
# RESULTS AND EXPLANATIONS
# ==================================================

if quiz and st.session_state.submitted:

    score = st.session_state.score
    percentage = round(score / TOTAL_QUESTIONS * 100)

    st.divider()
    st.subheader("Your quiz results")

    col1, col2, col3 = st.columns(3)

    col1.metric("Score", f"{score}/{TOTAL_QUESTIONS}")
    col2.metric("Percentage", f"{percentage}%")
    col3.metric("Incorrect", TOTAL_QUESTIONS - score)

    st.progress(percentage / 100)

    if percentage >= 80:
        st.success("Excellent work!")
    elif percentage >= 50:
        st.info("Good effort. Review the explanations to improve.")
    else:
        st.warning("Keep practicing and review your study PDF.")

    if not st.session_state.saved:

        try:
            with st.spinner("Saving your result to Supabase..."):

                saved, message = save_result(
                    st.session_state.pdf_name,
                    quiz,
                    st.session_state.answers,
                    score,
                    st.session_state.difficulty
                )

            if saved:
                st.session_state.saved = True
                st.success(message)
            else:
                st.warning(message)

        except Exception as error:
            st.error("Your result could not be saved to Supabase.")
            st.exception(error)

    st.subheader("Review your answers")

    for index, question in enumerate(quiz["questions"]):

        chosen = st.session_state.answers[str(index)]
        correct = question["answer"]

        st.markdown(f"### Question {index + 1}")
        st.write(question["question"])

        if chosen == correct:
            st.success(f"Your answer: {question['options'][chosen]}")
        else:
            st.error(f"Your answer: {question['options'][chosen]}")
            st.info(f"Correct answer: {question['options'][correct]}")

        st.write(f"**Explanation:** {question['explanation']}")
        st.divider()

    if st.button("Create Another Quiz", type="primary"):

        for key, value in defaults.items():
            st.session_state[key] = value

        st.rerun()


# ==================================================
# SIDEBAR
# ==================================================

with st.sidebar:

    st.title("QuizCraft AI")
    st.caption("Your AI study assistant")

    st.divider()

    st.markdown("### How it works")
    st.write("1. Upload a PDF.")
    st.write("2. Choose a difficulty.")
    st.write("3. Generate 20 questions.")
    st.write("4. Complete the quiz.")
    st.write("5. Submit and review your score.")

    st.divider()

    st.caption(f"Gemini model: {MODEL_NAME}")
    st.caption("Database: Supabase")
