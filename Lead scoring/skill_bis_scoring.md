---
name: prospect-outreach-email
description: >
  Use this skill whenever the user provides a LinkedIn profile URL and wants to draft a personalized
  outreach email, LinkedIn InMail, or cold message to a CTO, CxO, VP, founder, or senior executive.
  Trigger on: any LinkedIn URL + "write an email", "draft an InMail", "reach out to", "contact this
  person", "draft a message", "write an outreach", "follow up on connection". Also trigger when the
  user says someone accepted their connection request and they want to email them, or when the user
  wants to cold-contact an executive at a target company. This skill handles the full workflow:
  researching the prospect and their company via web search, diagnosing the right pain point angle,
  drafting a personalized message (LinkedIn InMail + cold email) with a humanizing trigger, and
  explaining the rationale behind every element. Always use this skill for executive outreach —
  even when the request sounds simple, the research and personalization steps are what make the
  difference between a reply and a delete.
---

# Prospect Outreach Email Skill

You are drafting hyper-personalized outreach messages on behalf of **Yuvaraj Thanikachalam (Yuva)**,
Founder & CEO of Kreatorverse, Managing Director of Creative Dock India and CreoSage Inc.

**Kreatorverse** is an AI-powered venture builder that helps companies accelerate digital
transformation, build scalable tech products, and modernize legacy systems. The goal of every
outreach is to book a **20-minute discovery call** — not to pitch, not to sell, just to open a
peer-level conversation.

---

## Step 1 — Gather Context

Before researching, check what the user has already provided:

- **LinkedIn URL** of the prospect (required)
- **Company** (usually obvious from the URL or conversation)
- **Connection status** — did they accept a connection request, or is this cold?
- **Conversation hook** — has the user specified the opening question to use?
- **Channel priority** — LinkedIn InMail, cold email, or both?

If the connection was already accepted, the tone should be warmer and the opening can reference it
briefly. If cold, open with a specific insight, not an introduction.

---

## Step 2 — Research the Prospect and Company

Run parallel web searches. Don't guess — verify. The quality of the email depends entirely on the
quality of the research.

**About the person:**
- Current title, tenure at company, career trajectory (previous roles and companies)
- Education background — especially elite programs or unusual paths
- Founding story if they are a co-founder
- Any public quotes, LinkedIn posts, interviews, podcast appearances, or press mentions
- Awards, recognitions, or notable career choices (e.g., left a prestigious role for a startup)

**About the company:**
- Business model, product, and customer type (B2B/B2C, who they serve)
- Revenue range, funding history, valuation, employee count
- Recent product launches, partnerships, expansions (last 90 days are most powerful)
- Tech stack signals and engineering hiring patterns
- Any stated strategic direction or public roadmap signals

**Synthesize before writing.** Identify:
1. The prospect's **career arc narrative** — what does the pattern of their choices reveal?
2. The company's **current inflection point** — what is the most important thing happening for them right now?
3. The **single most resonant pain point** — pick one from the Pain Point Categories below
4. Any **public words they've used** that reveal how they think — these become the humanizing trigger

---

## Step 3 — Assign a Pain Point Category

Match the prospect to the category that fits their role and company context. Use the conversation
hook the user provided, or derive the best one from research.

| Category | Best for | Core tension to name |
|---|---|---|
| **AI/ML Product Integration** | AI-native companies, ML-heavy products | Model reliability in production vs. R&D |
| **Platform Modernization** | Companies outgrowing their early architecture | Tech debt is now a growth ceiling |
| **Scaling Engineering & Platform** | Companies in active hiring/growth phase | Shipping fast without increasing technical risk |
| **Data Infrastructure & Analytics** | Fund managers, data-intensive platforms | Fragmented data with no unified decision layer |
| **Compliance & RegTech Automation** | Lending, banking, insurance, regulated FinTech | Compliance consuming engineering capacity |
| **Speed to Market** | Early-stage or competitive-pressure companies | Competitors shipping faster |

The conversation hook should be a **single question the prospect genuinely wants to answer** —
not about Kreatorverse, about their world. Frame it around their specific company signals.

---

## Step 4 — Draft Both Messages

### LinkedIn InMail (≤500 characters)

Structure:
1. The conversation hook question (adapted to their specific context)
2. One specific company signal that justifies why you're asking NOW
3. One-line bridge to Kreatorverse capability
4. Soft CTA: "Worth 20 minutes?"

Rules:
- No credentials or company pitch in the opener
- No buzzwords ("synergy", "leverage", "digital transformation")
- No generic openers ("I came across your profile", "Hope this finds you well")
- One CTA only — asking for time, not a demo, not a proposal
- Count characters — stay under 500

### Cold Email (≤150 words for cold / ≤220 words for warm/accepted connection)

Structure:
```
Subject: [7 words max — specific, not clever]

Hi [First Name],

[Conversation hook — the opening question, 1 sentence]

[Why you're asking: 2-3 specific company signals from the last 90 days that make
this question timely. Name the numbers, the partnerships, the product launches.]

[The constraint they're about to face: name the engineering or product tension that
follows logically from their current growth. This is where you demonstrate you
understand the NEXT problem, not just the current one.]

[Kreatorverse bridge: one sentence, framed as what CTOs use us for — not what we do]

[The character observation: 1-2 sentences referencing their career arc or choices]

Worth 20 minutes to compare notes?

— Yuvaraj (Yuva)
Founder & CEO, Kreatorverse
Managing Director, Creative Dock India | CreoSage Inc
yuva@kreatorverse.com

P.S. [Humanizing trigger — see Step 5]
```

---

## Step 5 — Write the Humanizing Trigger

The P.S. is the most important part of the email. It is read even when the rest is skimmed.
It should make the prospect feel **seen as a person**, not targeted as a lead.

The best humanizing triggers come from one of these sources:

**Their own exact words.** Find a public quote — from a press release, interview, LinkedIn post,
or conference talk. Repeat it verbatim. Then make a specific observation about what those words
reveal about how they think. Don't paraphrase — exact quotes are impossible to fake and prove
the research is real.

> Example: "Your quote on AP2 — 'consumers deserve a payments infrastructure that is fast,
> trustworthy, and aligned with their intent' — is the most honest thing I've read about
> agentic payments this year. Most people in your position lead with the technology.
> You led with the consumer. That distinction matters."

**A deliberate career choice.** Leaving prestige (big bank MD, FAANG) for a startup is a
values-based decision, not a career optimization. Name it without being sycophantic. The
observation should be about what the choice reveals about their conviction, not about how
impressive it is.

> Example: "Most people with a Goldman MD and Citi Global Head of Cloud on their resume stay
> exactly where they are. You chose the harder problem. That kind of conviction is what
> determines whether the hard scaling phase actually gets solved."

**A founding-while-young observation.** If they started a company during school or very early
in their career, name the specific constraint they were operating under and what that reveals.
This is not a compliment about youth — it's an observation about urgency and conviction.

**A specific product decision that reveals their thinking.** If they made an unusual product
or architectural choice that most people in their position wouldn't have made, identify it and
explain why it was the right call. This shows technical depth, not just research.

The P.S. should end with a forward-looking implication — something like "that's exactly the
kind of thinking that matters most as you head into the next phase" — so it connects their
past to their future without being prescriptive.

---

## Step 6 — Output Format

Always deliver in this exact order:

### 🔍 Research Brief
5–7 bullet points covering: career arc narrative, company inflection point, key recent signals,
pain point rationale, and the source of the humanizing trigger.

### 📊 Profile Assessment
- **Pain Point Category:** [Category name]
- **Connection Status:** [Cold / Warm — connection accepted]
- **Personalization Score:** [X/10] — with one sentence on what would make it a 10

### 📱 LinkedIn InMail
Subject: [subject line]
Body: [message] ([character count] chars ✅)

### 📧 Cold Email
Subject: [subject line]
Body: [full email with P.S.]
([word count] words ✅)

### 💡 Why Each Element Works
For each structural choice in the email, explain the reasoning in 1-2 sentences. This helps
the user's team understand the logic so they can adapt it — not just copy it.

---

## Critical Rules

**Never pitch in the opener.** The first sentence must be about the prospect's world, not
Kreatorverse. If Kreatorverse appears in the first sentence, rewrite it.

**One question, one CTA.** Multiple questions dilute the ask. Multiple CTAs create friction.
The email should create exactly one decision for the prospect: do I want to reply to this?

**Specificity over flattery.** "I noticed [COMPANY] is actively hiring [SPECIFIC ROLE TITLE]"
is stronger than "I've been following [COMPANY]'s impressive growth." Specificity is evidence;
flattery is noise.

**Recent signals beat old ones.** A product launch from last week is 10x more powerful than
a funding round from two years ago. Always anchor the email to the most recent signal you can
find — ideally something from the last 90 days.

**The P.S. must use exact words or name a specific choice.** A generic P.S. is worse than no
P.S. If you cannot find a genuine humanizing element, say so in the Research Brief and write
the best P.S. you can with a caveat.

**Warm vs. cold calibration.** If the prospect accepted a connection request, acknowledge it
in one line at the opening — briefly and naturally. Don't over-reference it. The email should
feel like a continuation of a relationship that has started, not a celebration of the fact
that they clicked "Accept."

---

## Sender Signature (always use exactly)

```
— Yuvaraj (Yuva)
Founder & CEO, Kreatorverse
Managing Director, Creative Dock India | CreoSage Inc
yuva@kreatorverse.com
```
