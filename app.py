
import json
import re
import streamlit as st
from google import genai
from google.genai import types
from supabase import create_client

# ---------------- PAGE CONFIG ----------------

st.set_page_config(
    page_title="QuizCraft AI",
    page_icon="📝",
    layout="wide"
)

MODEL_NAME = "gemini-2.5-flash"
TOTAL_QUESTIONS = 20

# ---------------- PROFESSIONAL DESIGN ----------------

st.markdown("""
<style>
    .main {
        background-color: #f7f9fc;
    }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1050px;
    }
    .hero {
        padding: 28px;
        border-radius: 18px;
        background: linear-gradient(120deg, #172554, #4338ca);
        color: white;
        margin-bottom: 24px;
    }
    .hero h1 {
        color: white;
        font-size: 38px;
        margin-bottom: 8px;
    }
    .hero p {
        color: #e0e7ff;
        font-size: 16px;
    }
    .question-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 12px;
    }
    div.stButton > button {
        border-radius: 10px;
        font-weight: 600;
        min-height: 44px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------- SECRETS AND CONNECTIONS ----------------

def get_secret(name, default=None):
    try:
        value = st.secrets.get(name, default)
        return value if value else default
    except Exception:
        return default


def get_gemini_client():
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is missing from Streamlit Secrets."
        )
    return genai.Client(api_key=api_key)


def get_supabase_client():
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_KEY")

    if not url or not key:
        return None

    return create_client(url, key)


# ---------------- PDF QUIZ GENERATOR ----------------

def clean_json_response(text):
    """Convert Gemini's JSON response into a Python object."""
    text = text.strip()

    # Remove optional Markdown code fences.
    text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        text,
        flags=re.IGNORECASE
    )

    return json.loads(text)


def generate_quiz(pdf_bytes, filename, difficulty):
    client = get_gemini_client()

    pdf_part = types.Part.from_bytes(
        data=pdf_bytes,
        mime_type="application/pdf"
    )

    prompt = f"""
You are an expert educational quiz creator.

Read the attached PDF carefully. Generate exactly 20 different
multiple-choice questions using information from this PDF only.

Requirements:
1. Difficulty: {difficulty}.
2. Each question must have exactly four answer options.
3. Exactly one option must be correct.
4. Questions must cover different important ideas from the PDF.
5. Do not invent facts that are unsupported by the document.
6. Do not repeat questions.
7. Write clear, simple English.
8. Include a short explanation for each correct answer.
9. If the PDF is too short or unreadable to support 20 meaningful
   questions, return an error object instead of inventing questions.

Return ONLY valid JSON in this exact structure:

{{
  "title": "A short title for the quiz",
  "questions": [
    {{
      "question": "Question text",
      "options": [
        "First option",
        "Second option",
        "Third option",
        "Fourth option"
      ],
      "answer": 0,
      "explanation": "A brief explanation supported by the PDF"
    }}
  ]
}}

The answer field is a zero-based index: 0, 1, 2, or 3.
The questions array must contain exactly 20 questions.
Do not include Markdown or any text outside the JSON.
"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[prompt, pdf_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
            max_output_tokens=10000
        )
    )

    if not response.text:
        raise ValueError("Gemini returned an empty response.")

    data = clean_json_response(response.text)

    if "error" in data:
        raise ValueError(str(data["error"]))

    questions = data.get("questions")

    if not isinstance(questions, list) or len(questions) != TOTAL_QUESTIONS:
        raise ValueError(
            "The PDF did not produce exactly 20 questions. "
            "Try a clearer or more detailed PDF."
        )

    # Validate every question before displaying the quiz.
    for number, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            raise ValueError(f"Question {number} has an invalid format.")

        if not isinstance(question.get("question"), str):
            raise ValueError(f"Question {number} is missing its text.")

        options = question.get("options")
        answer = question.get("answer")

        if (
            not isinstance(options, list)
            or len(options) != 4
            or not all(isinstance(option, str) and option.strip()
                       for option in options)
        ):
            raise ValueError(
                f"Question {number} must have four valid options."
            )

        # bool is a subclass of int in Python, so reject it explicitly.
        if type(answer) is not int or answer not in range(4):
            raise ValueError(
                f"Question {number} has an invalid answer index."
            )

        if not isinstance(question.get("explanation"), str):
            raise ValueError(
                f"Question {number} is missing its explanation."
            )

    data["title"] = str(data.get("title") or "Your PDF Quiz")
    return data


# ---------------- SAVE RESULTS TO SUPABASE ----------------

def save_result(pdf_name, quiz, answers, score):
    try:
        supabase = get_supabase_client()

        if supabase is None:
            return False, "Supabase is not configured."

        # Do not save answer keys or explanations in a public quiz page.
        record = {
            "pdf_name": pdf_name,
            "score": score,
            "total_questions": TOTAL_QUESTIONS,
            "questions": quiz["questions"],
            "user_answers": answers
        }

        supabase.table("quiz_results").insert(record).execute()

        return True, "Quiz result saved to Supabase."

    except Exception as error:
        # The quiz can still work when database saving fails.
        return False, str(error)


# ---------------- SESSION STATE ----------------

if "quiz" not in st.session_state:
    st.session_state.quiz = None

if "pdf_name" not in st.session_state:
    st.session_state.pdf_name = None

if "submitted" not in st.session_state:
    st.session_state.submitted = False

if "saved" not in st.session_state:
    st.session_state.saved = False

if "score" not in st.session_state:
    st.session_state.score = None

if "answers" not in st.session_state:
    st.session_state.answers = {}


# ---------------- HEADER ----------------

st.markdown("""
<div class="hero">
    <h1>QuizCraft AI</h1>
    <p>Turn your study PDFs into interactive quizzes with Gemini AI.</p>
    <p>Upload • Practice • Check Your Score • Save Your Results</p>
</div>
""", unsafe_allow_html=True)

left, right = st.columns([3, 1])

with left:
    st.subheader("Create your quiz")
    st.write(
        "Upload your notes, textbook chapter, or study PDF. "
        "QuizCraft AI will create 20 multiple-choice questions."
    )

with right:
    st.metric("Questions per quiz", TOTAL_QUESTIONS)
    st.metric("Options per question", 4)

# ---------------- UPLOAD SECTION ----------------

uploaded_pdf = st.file_uploader(
    "Upload your study PDF",
    type=["pdf"],
    help="Upload a readable PDF containing your study material."
)

difficulty = st.selectbox(
    "Choose quiz difficulty",
    ["Easy", "Medium", "Hard"]
)

if uploaded_pdf:
    st.info(f"Selected file: {uploaded_pdf.name}")

    if uploaded_pdf.size > 20 * 1024 * 1024:
        st.error("Please upload a PDF smaller than 20 MB.")
        uploaded_pdf = None

if st.button(
    "✨ Generate 20 Questions",
    type="primary",
    use_container_width=True,
    disabled=uploaded_pdf is None
):
    if uploaded_pdf is not None:
        if uploaded_pdf.read(5) != b"%PDF-":
            st.error("This file does not appear to be a valid PDF.")
        else:
            uploaded_pdf.seek(0)
            pdf_bytes = uploaded_pdf.getvalue()

            with st.spinner(
                "Gemini is reading your PDF and creating your quiz..."
            ):
                try:
                    quiz = generate_quiz(
                        pdf_bytes,
                        uploaded_pdf.name,
                        difficulty
                    )

                    st.session_state.quiz = quiz
                    st.session_state.pdf_name = uploaded_pdf.name
                    st.session_state.submitted = False
                    st.session_state.saved = False
                    st.session_state.score = None
                    st.session_state.answers = {}

                    st.rerun()

                except Exception as error:
                    st.error(
                        "Quiz generation failed. Check your Gemini API "
                        "key, model access, PDF, and API usage limits."
                    )
                    st.caption(f"Technical details: {error}")

# ---------------- QUIZ SECTION ----------------

quiz = st.session_state.quiz

if quiz:
    st.divider()
    st.subheader(quiz["title"])
    st.caption(
        f"File: {st.session_state.pdf_name} · "
        f"{TOTAL_QUESTIONS} questions · {difficulty} difficulty"
    )

    if not st.session_state.submitted:
        with st.form("quiz_form"):
            selected_answers = {}

            for index, question in enumerate(quiz["questions"]):
                st.markdown(
                    f"**Question {index + 1} of {TOTAL_QUESTIONS}**"
                )
                st.markdown(question["question"])

                selected_answers[str(index)] = st.radio(
                    f"Choose your answer for question {index + 1}",
                    options=range(4),
                    format_func=lambda i, opts=question["options"]:
                        f"{chr(65 + i)}. {opts[i]}",
                    index=None,
                    key=f"answer_{index}",
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
                str(i)
                for i, answer in selected_answers.items()
                if answer is None
            ]

            if unanswered:
                st.warning(
                    f"You have {len(unanswered)} unanswered question(s). "
                    "Select an answer for every question before submitting."
                )
            else:
                score = sum(
                    selected_answers[str(i)] == question["answer"]
                    for i, question in enumerate(quiz["questions"])
                )

                st.session_state.answers = {
                    key: int(value)
                    for key, value in selected_answers.items()
                }
                st.session_state.score = int(score)
                st.session_state.submitted = True
                st.rerun()

    # ---------------- RESULTS SECTION ----------------

    if st.session_state.submitted:
        score = st.session_state.score
        percentage = round((score / TOTAL_QUESTIONS) * 100)

        st.success("Quiz completed!")
        st.metric("Your Score", f"{score} / {TOTAL_QUESTIONS}")
        st.progress(percentage / 100)
        st.write(f"**Percentage:** {percentage}%")

        if percentage >= 80:
            st.write("Excellent work! You understand much of this material.")
        elif percentage >= 50:
            st.write("Good effort. Review the explanations to improve.")
        else:
            st.write("Keep practicing and review your study PDF.")

        # Save only once for each submitted attempt.
        if not st.session_state.saved:
            with st.spinner("Saving your result to Supabase..."):
                saved, message = save_result(
                    st.session_state.pdf_name,
                    quiz,
                    st.session_state.answers,
                    score
                )

            if saved:
                st.session_state.saved = True
                st.success(message)
            else:
                st.warning(
                    "Your score is displayed, but it was not saved. "
                    "Check your Supabase settings and database permissions."
                )
                st.caption(message)

        st.divider()
        st.subheader("Review your answers")

        for index, question in enumerate(quiz["questions"]):
            selected = st.session_state.answers[str(index)]
            correct = question["answer"]
            is_correct = selected == correct

            st.markdown(f"### Question {index + 1}")
            st.write(question["question"])

            if is_correct:
                st.success(f"Your answer: {question['options'][selected]}")
            else:
                st.error(f"Your answer: {question['options'][selected]}")
                st.info(f"Correct answer: {question['options'][correct]}")

            st.write(f"**Explanation:** {question['explanation']}")
            st.divider()

        if st.button("Create Another Quiz", type="primary"):
            st.session_state.quiz = None
            st.session_state.pdf_name = None
            st.session_state.submitted = False
            st.session_state.saved = False
            st.session_state.score = None
            st.session_state.answers = {}
            st.rerun()

# ---------------- SIDEBAR ----------------

with st.sidebar:
    st.title("QuizCraft AI")
    st.caption("AI-powered study assistant")
    st.divider()
    st.write("**How to use**")
    st.write("1. Upload a PDF.")
    st.write("2. Choose difficulty.")
    st.write("3. Generate 20 questions.")
    st.write("4. Answer every question.")
    st.write("5. Submit and review your score.")
    st.divider()
    st.caption("Powered by Gemini AI and Supabase.")
