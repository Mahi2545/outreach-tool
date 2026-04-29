import streamlit as st
import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up Gemini client
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

# ---- SYSTEM PROMPT based on skill_bis_scoring.md ----
SYSTEM_PROMPT = """
You are drafting hyper-personalized outreach messages on behalf of **Yuvaraj Thanikachalam (Yuva)**,
Founder & CEO of Kreatorverse, Managing Director of Creative Dock India and CreoSage Inc.

**Kreatorverse** is an AI-powered venture builder that helps companies accelerate digital
transformation, build scalable tech products, and modernize legacy systems. The goal of every
outreach is to book a **20-minute discovery call** — not to pitch, not to sell, just to open a
peer-level conversation.

## Step 1 — Synthesize Context
Identify:
1. The prospect's **career arc narrative** — what does the pattern of their choices reveal?
2. The company's **current inflection point** — what is the most important thing happening for them right now?
3. The **single most resonant pain point** — pick one from the Pain Point Categories below.
4. Any **public words they've used** that reveal how they think — these become the humanizing trigger.

## Step 2 — Assign a Pain Point Category
Match the prospect to the category that fits their role and company context.
- **AI/ML Product Integration**: Model reliability in production vs. R&D
- **Platform Modernization**: Tech debt is now a growth ceiling
- **Scaling Engineering & Platform**: Shipping fast without increasing technical risk
- **Data Infrastructure & Analytics**: Fragmented data with no unified decision layer
- **Compliance & RegTech Automation**: Compliance consuming engineering capacity
- **Speed to Market**: Competitors shipping faster

## Step 3 — Draft Both Messages

### LinkedIn InMail (≤500 characters)
1. The conversation hook question
2. One specific company signal that justifies why you're asking NOW
3. One-line bridge to Kreatorverse capability
4. Soft CTA: "Worth 20 minutes?"
Rules: No buzzwords, no generic openers, one CTA only, under 500 chars.

### Cold Email (≤150 words for cold / ≤220 words for warm)
Subject: [7 words max — specific, not clever]
Hi [First Name],
[Conversation hook — the opening question, 1 sentence]
[Why you're asking: 2-3 specific company signals from the last 90 days]
[The constraint they're about to face: name the engineering or product tension]
[Kreatorverse bridge: one sentence, framed as what CTOs use us for]
[The character observation: 1-2 sentences referencing their career arc or choices]
Worth 20 minutes to compare notes?

— Yuvaraj (Yuva)
Founder & CEO, Kreatorverse
Managing Director, Creative Dock India | CreoSage Inc
yuva@kreatorverse.com

P.S. [Humanizing trigger using their own words or a deliberate career choice]

## Step 4 — Output Format
Always deliver in this exact order:

### 🔍 Research Brief
5–7 bullet points covering: career arc narrative, company inflection point, key recent signals, pain point rationale, and the source of the humanizing trigger.

### 📊 Profile Assessment
- **Pain Point Category:** [Category name]
- **Connection Status:** [Cold / Warm]
- **Personalization Score:** [X/10] — with one sentence on what would make it a 10

### 📱 LinkedIn InMail
Subject: [subject line]
Body: [message] ([character count] chars ✅)

### 📧 Cold Email
Subject: [subject line]
Body: [full email with P.S.]
([word count] words ✅)

### 💡 Why Each Element Works
For each structural choice in the email, explain the reasoning in 1-2 sentences.
"""

st.set_page_config(page_title="Kreatorverse Outreach Generator", page_icon="✉️", layout="wide")

st.title("✉️ Kreatorverse Outreach Generator")
st.markdown("Draft hyper-personalized executive outreach emails based on Yuva's proven framework.")

with st.sidebar:
    st.header("Context & Settings")
    
    st.info("💡 **Free API Suggestion:** We recommend using the **Google Gemini API** (Gemini 1.5 Flash). You can get a free API key instantly at [Google AI Studio](https://aistudio.google.com/app/apikey) (up to 15 requests/minute for free).")
    
    temp_key = st.text_input("Enter your Gemini API Key:", type="password", value=api_key if api_key else "")
    if temp_key:
        genai.configure(api_key=temp_key)
        api_key = temp_key
            
    st.markdown("""
    **Best Practices:**
    - Provide exact quotes if you have them.
    - Mention recent product launches or funding.
    - Be specific about their career choices.
    """)

col1, col2 = st.columns([1, 1])

with col1:
    prospect_name = st.text_input("Prospect Name", placeholder="e.g. John Smith")
    prospect_url = st.text_input("LinkedIn URL", placeholder="https://linkedin.com/in/...")
    company = st.text_input("Company", placeholder="e.g. Acme Corp")
    connection_status = st.selectbox("Connection Status", ["Cold", "Warm (Accepted Connection)"])
    hook = st.text_input("Conversation Hook (Optional)", placeholder="e.g. Scaling data infra post-Series B")

with col2:
    research_notes = st.text_area("Research Notes / Company Signals", height=250, 
                                  placeholder="Paste recent news, funding, career moves, or direct quotes from the prospect here. The more specific, the better the email.")

generate_btn = st.button("🚀 Generate Outreach", type="primary")

if generate_btn:
    if not api_key:
        st.error("Please provide a Gemini API key in the sidebar.")
    elif not prospect_name or not company:
        st.error("Please provide at least the prospect's name and company.")
    else:
        with st.spinner("Drafting personalized outreach..."):
            
            user_prompt = f"""
            Please write an outreach sequence for the following prospect.
            
            **Prospect:** {prospect_name}
            **LinkedIn URL:** {prospect_url}
            **Company:** {company}
            **Connection Status:** {connection_status}
            **Conversation Hook:** {hook if hook else 'Use best judgment based on research notes'}
            
            **Research Notes & Signals:**
            {research_notes if research_notes else 'No additional notes provided. Do your best to infer from the company and role.'}
            """
            
            try:
                model = genai.GenerativeModel(
                    "gemini-1.5-flash",
                    system_instruction=SYSTEM_PROMPT
                )
                
                response = model.generate_content(
                    user_prompt,
                    generation_config=genai.types.GenerationConfig(temperature=0.7)
                )
                
                result = response.text
                st.success("Outreach generated successfully!")
                
                st.markdown("---")
                st.markdown(result)
                
                # Option to copy / download
                st.download_button(
                    label="📥 Download Output as Text",
                    data=result,
                    file_name=f"outreach_{prospect_name.replace(' ', '_')}.md",
                    mime="text/markdown"
                )
                
            except Exception as e:
                st.error(f"Error calling Gemini API: {str(e)}")
