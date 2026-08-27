# 🌟 Mentoring-Me — Equitable Mentorship Pairing & Career Growth Platform
> **Capstone Project — Team Prism-Strategists**  
> *Aligned with United Nations Sustainable Development Goal 5: Gender Equality (Target 5.5)*

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.14-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Frontend-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![Security](https://img.shields.io/badge/Auth-JWT%20%2B%202FA%20OTP-green.svg)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg)]()

---

## 📌 1. Problem Statement

Women remain significantly underrepresented in specialized technical domains (DevOps, Cloud Architecture, Systems, Data Engineering), facing unique hurdles throughout their career trajectories:

1. **The Retention Drop-off**: Empirical analysis of 49,294 developers reveals acute attrition risk at two distinct career milestones:
   - **Early-Career Transition (0–2 years)**: Juniors leaving due to isolation, lack of technical onboarding, and imposter syndrome.
   - **Mid-Career Plateau (5–10 years)**: Women leaving technical tracks due to lack of sponsorship, bias in promotion pathways, and scarcity of senior female role models.
2. **Opaque & Ineffective Matching**: Traditional mentorship programs rely on manual, arbitrary pairing or black-box algorithms that fail to account for role-specific skills, tenure gaps, and stated workplace priorities.
3. **Friction in Coordination & Outreach**: Mentees struggle with cold outreach, scheduling friction, and identifying vetted Diversity & Inclusion (D&I) allies.

---

## 💡 2. Solution Summary

**Mentoring-Me** is a full-stack, data-grounded mentorship pairing platform engineered to dismantle these barriers through transparent algorithmic matching, institutional security, and continuous career advisory tools.

### 🔑 Key Platform Features:
* **Explainable 5-Factor Weighted Matching Model**:
  - **Role & Technical Alignment (30%)**: Jaccard similarity over multi-skill sets.
  - **Relatable Experience Gap (25%)**: Optimal 2–10 year seniority window.
  - **Retention-Risk Career-Stage Priority (20%)**: Direct boost for 0–2y and 5–10y candidates.
  - **Goals & Workplace Culture Alignment (15%)**: Compatibility across stated job factors (e.g., flex-time, diversity signals).
  - **Practical & Logistics Fit (10%)**: Organizational scale alignment.
* **Transparent Compatibility Breakdown**: Interactive UI bar charts showing users exactly *why* a pair was recommended.
* **D&I Allyship & Representation Boosts**: +10% algorithmic priority for mentors registered as Diversity Allies.
* **Consumer-Grade Security**: JWT session tokens, Bcrypt password hashing, and mandatory **Double Authentication (2FA)** with 6-digit email OTPs.
* **In-App Direct Messaging Hub**: Real-time communication with unread message tracking and persistent conversation archives.
* **Seamless Calendar Scheduling**: One-click Google Calendar sync and downloadable `.ics` calendar invites for 25-minute introductory syncs.
* **AI Career Advisor**: Interactive career roadmap generator and CV analyzer powered by Google Gemini.
* **Outreach Hub & Peer Nominations**: External discovery across GitHub and ORCID directories with automated invitation email drafts.

---

## 📊 3. Empirical Data & Algorithm Performance

The algorithm was developed and validated against the **Stack Overflow Developer Survey (49,294 cleaned respondents)**:

| Metric | Result | Benchmark Significance |
| :--- | :---: | :--- |
| **Top-Match Mean Score** | **0.921 (92.1%)** | Consistently delivers "Strong" compatibility recommendations |
| **Improvement over Random Baseline** | **+80.6%** | Outperforms random assignment by >80% |
| **Strong Match Coverage (50-mentor pool)** | **63.0%** | Robust matching even with smaller initial mentor cohorts |
| **Score Standard Deviation** | **0.063** | Discriminating, non-uniform scoring distribution |

---

## 🏛️ 4. Architecture & Technology Stack

```
mentor_me_capstone/
├── analysis/                      # Objective 1: EDA, data cleaning & visualizations
│   ├── objective1_full_pipeline.py
│   ├── chart1-5_*.png             # 5 core exploratory data analysis charts
│   └── summary_statistics.csv
├── data/
│   └── so2020_cleaned.csv         # Cleaned Stack Overflow benchmark dataset (49,294 rows)
├── matching/                      # Core Web Application & API
│   ├── app.py                     # Streamlit Consumer-Grade Web UI
│   ├── matching_algorithm_v1.py   # 5-factor weighted algorithm implementation
│   ├── evaluate_matching_algorithm.py # Accuracy & baseline benchmarking suite
│   ├── test_matching_scenarios.py # Scenario & edge-case test suite
│   ├── requirements.txt
│   └── backend/                   # FastAPI REST Backend Service
│       ├── main.py                # REST endpoints & middleware
│       ├── auth.py                # JWT, Bcrypt, 2FA OTP & SMTP dispatch
│       ├── models.py              # SQLAlchemy database ORM models
│       ├── schemas.py             # Pydantic data contracts
│       ├── seed.py                # Database population script
│       └── profile_evaluator.py   # GitHub & ORCID directory evaluator
├── docker-compose.yml             # Multi-container orchestration
└── README.md                      # Project documentation
```

* **Frontend**: Streamlit, Custom Modern CSS Design System, Plotly / Altair.
* **Backend**: FastAPI, Pydantic V2, Starlette.
* **Database & ORM**: SQLite / PostgreSQL with SQLAlchemy.
* **Security & Auth**: OAuth2 (Google & Facebook SSO), Bcrypt, PyJWT, Time-limited 2FA OTPs.
* **External APIs**: Google Gemini AI, GitHub REST API, ORCID Public API, Resend / SMTP.

---

## 🚀 5. How to Run & View the Project

### Option A: Live Cloud Deployment
Access the live interactive application directly at:
👉 **[https://mentoring-me.streamlit.app](https://mentoring-me.streamlit.app)**

---

### Option B: Running Locally (Step-by-Step)

#### 1. Clone the repository:
```bash
git clone https://github.com/Mentor-Me-Collective/grow-with-google-showcase.git
cd grow-with-google-showcase
git checkout Prism-Strategists
```

#### 2. Set up a Python Virtual Environment:
```bash
# Navigate to the matching app directory
cd matching

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

#### 3. Run the Backend API:
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
*Interactive API Docs will be available at:* `http://127.0.0.1:8000/docs`

#### 4. Run the Streamlit Frontend Web App:
In a new terminal window (with virtual environment activated):
```bash
streamlit run app.py
```
*Open your browser at:* `http://localhost:8501`

---

### Option C: Running with Docker Compose
```bash
docker-compose up --build
```
* Access Frontend: `http://localhost:8501`
* Access Backend API: `http://localhost:8000/docs`

---

## 🧪 6. Running the Automated Test Suite

To run the complete automated test suite (23 unit & integration tests covering 2FA, JWT sessions, in-app messaging, algorithm scenarios, and external directories):

```bash
cd matching
pytest backend/ test_matching_scenarios.py -q
```

To run the algorithm benchmarking comparison against a random baseline:
```bash
python evaluate_matching_algorithm.py
```

---

## 👥 7. Team & Credits
* **Project Team**: **Prism-Strategists**
* **Initiative**: Mentor-Me Collective — Grow with Google Showcase (2026 Cohort)
* **License**: Open-source under the MIT License.
