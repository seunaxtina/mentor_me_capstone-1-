# Mentor Me — Data Analytics & Matching Algorithm

Work completed for Objective 1 (data analytics) and the Matching Algorithm section.

## Folder structure

```
mentor_me_capstone/
├── data/
│   └── so2020_cleaned.csv          — cleaned Stack Overflow 2020 survey (49,294 rows)
├── analysis/
│   ├── objective1_full_pipeline.py — cleaning + EDA + charts, run this to regenerate everything
│   ├── chart1-5_*.png               — the 5 key visualizations
│   ├── key_insights.txt             — written summary of findings
│   └── summary_statistics.csv       — headline numbers for slides/report
├── matching/
│   ├── matching_algorithm_v1.py     — the actual weighted matching algorithm
│   ├── app.py                       — interactive Streamlit demo (live matching)
│   ├── test_matching_scenarios.py   — edge-case tests (run after any algorithm change)
│   ├── evaluate_matching_algorithm.py — accuracy evaluation vs. random baseline
│   ├── matching_algorithm_methodology.md — full write-up: research, design, testing, evaluation
│   ├── requirements.txt
│   └── so2020_cleaned.csv           — same data file, duplicated here so the scripts run standalone
└── diagrams/
    ├── flowchart_matching_algorithm.png
    └── architecture_diagram.png
```

## How to run things

**Regenerate the data analysis:**
```
cd analysis
python objective1_full_pipeline.py
```

**Run the interactive matching demo:**
```
cd matching
pip install -r requirements.txt
streamlit run app.py
```

**Run the algorithm and LinkedIn discovery tests:**
```
cd matching
python test_matching_scenarios.py
python evaluate_matching_algorithm.py
python backend/test_linkedin_search.py
```

## Key numbers for the report/slides

- Data source: Stack Overflow 2020 Developer Survey (49,294 cleaned respondents)
- Matching algorithm: weighted scoring, 5 criteria (Role 30% / Experience 25% / Career-stage 20% / Goals 15% / Practical 10%)
- Evaluation: 80.6% improvement over random baseline matching
- Realistic-scale coverage (50-mentor pool): 63% Strong matches, 37% Good, 0% Fair/Weak

See `matching_algorithm_methodology.md` for the full write-up with reasoning behind every decision.
