# ChatGPT Reviews Sentiment Analysis

## 📌 Project Overview
This project analyzes real user reviews of ChatGPT to understand overall sentiment, opinion strength, and which aspects of the product users most often praise or criticize. The workflow covers data cleaning, sentiment scoring, subjectivity analysis, keyword extraction, and visualizations, all implemented in a single Jupyter notebook.

**Main file:** `Chatgpt_review_analysis.ipynb`  
**Task:** End‑to‑end NLP analysis of textual app reviews with sentiment + keyword insights.

---

## 🔍 Objectives

The analysis aims to answer:

1. **What is the general sentiment** users express about ChatGPT?
2. **How strong or opinionated** are those sentiments (subjectivity)?
3. **Which features/aspects** of ChatGPT are most frequently mentioned in positive feedback?

---

## 🛠 Tech Stack

- **Language:** Python 3  
- **Libraries:**  
  - Data handling: `pandas`, `numpy`  
  - Visualization: `matplotlib`, `seaborn`  
  - NLP & sentiment: `textblob`  
  - (Optional) Word cloud: `wordcloud`
 
📊 Key Analysis & Visualizations

Sentiment distribution by rating:
Bar/stacked plots comparing Sentiment labels across star ratings.

Findings:
5‑star reviews are overwhelmingly Positive.
1–2‑star reviews contain a much higher share of Negative and Neutral sentiment.
3–4‑star reviews are mixed but still skew positive.

Subjectivity distribution:
Histogram of Subjectivity scores.
Shows how opinionated the user base is and whether reviews tend to be factual or subjective.

Positive review keyword analysis:
Filtered dataset to keep only Positive (and/or 4–5 star) reviews.
Tokenized and cleaned the text (lowercased, stripped punctuation/stopwords).
Computed word frequencies.
Top positive keywords: app, good, best, nice, great
Indicates that users strongly appreciate the overall app experience and perceive it as good / great / best.


Visual representation of the most common positive terms. (Optional) 

---

## 📂 Repository Structure

```text
.
├── Chatgpt_review_analysis.ipynb   # Main notebook with full analysis
├── chatgpt_reviews.csv            # Raw reviews dataset (if included)
└── README.md                      # Project documentation

