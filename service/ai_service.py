import json
import os
import re
from typing import cast

from fastapi import HTTPException
from openai import OpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)


SCORER_RUBRICS = """
                Scoring mechanisms for the five platforms (based on the research in docs/ats-research.md; each platform must be scored according to its own methodology):

                1. Workday (HiredScore): Output an A/B/C/D grade + 0–100 score. 
                Methodology: 
                    Treat the resume as if it were a parsed, structured profile (separate fields for job titles, education, skills, etc.), then perform semantic matching against the JD. 
                    Skills not explicitly stated may be inferred from context. 
                    Heavily penalise difficult-to-parse structures (e.g. tables or multi-column formatting).
                    Heavily penalise abnormal keyword density (e.g. excessive repetition of the same term). 
                    Job-title alignment and relevance of recent experience carry significant weight.
                
                2. iCIMS (Copilot Role Fit): Output an A/B/C/D grade + 0–100 score. 
                Methodology: 
                    Weight keyword frequency — core skills from the JD that appear multiple times across the Summary + experience statements + Skills section receive higher scores; skills mentioned only once receive lower scores. 
                    Terminology must match the JD precisely (e.g. "JS" ≠ "JavaScript").
                    Synonyms receive only half credit. 
                    Then assess whether the required years of experience are met, career progression, and relevance of previous roles.
                
                3. Greenhouse (scorecard coverage): Output an A/B/C/D grade + 0–100 score = coverage rate. 
                Methodology: 
                    First extract the list of required attributes that a recruiter/hiring manager would likely put into the scorecard (hard skills, years of experience, qualifications, and soft requirements). 
                    Check each item against the resume for an explicit evidence statement. 
                    Merely listing a skill in the Skills section is not sufficient evidence and receives only partial credit. List all uncovered attributes.
                    
                4. SEEK (Australian candidate matching): Output an A/B/C/D grade + 0–100 score.
                Methodology: 
                    Consider job-title similarity, skill overlap, location match, and recency of relevant experience, with greater weight given to relevant experience from the past three years.
                    
                5. PageUp (Australian government): Output an A/B/C/D grade + 0–100 score.
                Methodology: 
                    Assess parseability + skill/job-title/years-of-experience matching. 
                    If the JD contains selection-criteria-style requirements, check whether each criterion is addressed individually. 
                    Also check whether spelling matches the JD's Australian English conventions (e.g. organisation / specialise).
                """


"""
The AI prompt for scoring the resume compared with JD via ATS five platforms.
"""
def build_score_prompt(jd, cv):
    return f"""
        You are an ATS screening simulator. 
        For the resume below, evaluate it from the employer's perspective and score it separately according to the actual mechanisms of each of the five platforms. 
        Be strict—underestimate rather than be generous.
        
        {SCORER_RUBRICS}
        
        # Full Job Description(JD)
        {jd}
        
        # Full Resume
        {cv}
        
        Output only a single JSON object. 
        Do not use a Markdown code block and do not provide any explanation. 
        Each platform may have a maximum of 3 deductions and 3 fixes, with each item limited to one sentence. 
        Use the following structure:
        {{
            "platforms": [{{"name": "Workday (HiredScore)", "grade": "A-D 或 null", "score": 0-100, "deductions": ["Reason for deduction, specific to a location/section in the resume"], "fixes": ["Actionable modification suggestion"]}}, ...5 platforms total...],
            "keyword_gaps": ["Keywords required by the Job Description(JD) that are missing from the resume or use inconsistent terminology"],
            "summary": "One-sentence overall assessment"
        }}
        """


"""
skills = ["Python", "FastAPI", "SQL"]
# chr(10) is the newline character, which is equivalent to "\n".
text = chr(10).join(skills)
print(text)

The AI prompt for constructing supplementary missing skills' descriptions based on a candidate's CV.
Only for user selected skills
"""
def build_draft_prompt(jd, cv, skills):
    return f"""
            You are a career consultant.
            The candidate confirms that they genuinely possess the following skills, but they are not mentioned in the main resume. 
            For each skill, draft one supplementary experience description (1–2 sentences), using language consistent with the job description (JD).
            
            Requirements:
            
            - Each description must be grounded in a real role or project already present in the resume, and describe where and how the skill was used in that experience.
            - You may reasonably infer how the skill could have been used within the context of those roles or projects (the candidate will review and modify each item before using it).
            - Red lines: Do not invent new employers, job titles, dates, educational qualifications, or certifications. Do not fabricate specific numbers.
            - Each item must stand alone as an independent sentence and must not refer to any other item.

            # Full Job Description(JD)
            {jd}

            # Candidate's resume (real roles/projects must be taken only from this resume)
            {cv}

            # Skills to draft
            {chr(10).join(skills)}

            Output only a single JSON object. 
            Do not use a Markdown code block and do not provide any explanation. 
            Use the following structure:
            {{"drafts": [{{"skill": "skill name", "text": "drafted description"}}]}}
        """


ATS_RULES = """
            ATS/AI Screening Optimisation Rules (must all be followed; evidence: `docs/ats-research.md`):
            
            1. Extract hard skills, tool names, qualifications, job titles, and other keywords from the JD. 
            If genuinely supported, include them naturally in the CV using the JD's exact spelling.
            
            2. No keyword stuffing: the same keyword should normally appear only 2–3 times, embedded naturally in achievement statements.
            
            3. The first sentence of the Professional Summary must use the exact or closest matching target job title. 
            Do not use phrases such as “aspiring,” “eager to transition,” or “looking to break into.”
            
            4. Use only standard section headings: Professional Summary / Skills / Experience / Education / Certifications.
            
            5. Use a single-column plain-text layout. No tables, multiple columns, icons, images, headers/footers, or progress bars.
            
            6. Start every experience bullet with an action verb and include a quantified result (%, amount, scale, or time).
            
            7. Every core JD requirement must have a clearly corresponding evidence statement in the CV.
            
            8. Use reverse chronological order. 
            Dates may only be copied from the resume, with formatting standardised to “MMM YYYY” (e.g. “April.2025” → “Apr 2025”). 
            Never change the year or month or move experiences to fill timeline gaps.
            
            9. The Skills section should list only JD-relevant skills, separated by commas. Unrelated skills and experience points may be condensed or omitted.
            
            10. Spell out abbreviations and include the abbreviation once, e.g. “Search Engine Optimisation (SEO).”
            
            11. Preserve evidence of judgment, stakeholder management, cross-team collaboration, and other human skills.
            
            12. **Absolute red lines:** Employer names, job titles, dates, educational institutions/degrees, and all numerical metrics may only be copied exactly from the resume. 
            Do not change, invent, or infer them. 
            If experience is insufficient or the timeline has gaps, present it as-is. 
            If the original resume contains corrupted text (e.g. “producQon”), it may be restored to the correct spelling without changing the underlying fact.
            
            13. Do not add skills yourself. If a JD-required skill has no evidence in the resume or supplementary material, do not include it. 
            Skills explicitly confirmed by the user before generation may be added. 
            The `===ADDED SKILLS===` section must still be included: normally write “None”; if any unsupported skill was actually added, list each one.
            
            14. **Screen-out information must be preserved exactly:** Any statements in the resume about work visa/work rights/PR/citizenship, preferred location, and availability must remain unchanged directly below the contact information. 
            LinkedIn, GitHub, and portfolio links must also be retained.
            
            15. The cover letter's opening paragraph must state the job title and company name, the middle section must use 1–2 quantified achievements to address 2–3 core JD requirements, and the closing paragraph must include a call to action.
            """


def build_prompt(jd, title, company, cv, cl_sample, cl_format, extra="", miss=()):
    extra = extra.strip()
    extra_block = (f"\n# Additional confirmed experience and skills that are genuine but not included in the original resume (these are also approved factual sources and may be used) "
                   f"\n{extra}\n"
                   "Usage: Integrate each item into the bullet points under the relevant role in the resume—rewrite or merge it into an existing bullet, "
                   "or replace the least JD-relevant bullet under that role. Do not create a separate section or list them at the end."
                   "The overall CV length must not increase as a result of these additions. \n"
                   if extra else "")
    if miss:
        gap_block = ("\n# System-identified skill gaps (required by the JD but with no evidence found in the resume above) \n" + ", ".join(miss)
                     + "\nUnder Rule 13, none of these may be added. Leave them as-is and output ===ADDED SKILLS=== as None.\n")
    else:
        gap_block = ""
    return f"""
            You are a senior career consultant. 
            Tailor a CV and a cover letter for the position below. 
            
            {ATS_RULES}
            
            # Target Position: {title} @ {company}
            # Job Description
            {jd}
            
            # My Complete Resume (Factual Sources. Employers/Dates/Education/Numbers can only be copied verbatim from here)
            {cv}
            {extra_block}{gap_block}
            # My cover letter sample (mimicking its style)
            {cl_sample}
            
            # My preferred cover letter format
            {cl_format}
            
            Output format (strictly adhere to):
            - First output the complete CV, using Markdown to mark the structure: `# Name` on one line, followed by one line of contact information (City | Email | Phone); each standard section title uses `## ` (e.g. `## Professional Summary`); each experience title uses `### Position — Company, Location (MMM YYYY - MMM YYYY)`; responsibilities and achievements use `- ` unordered lists; quantified numbers/key metrics use `**bold**`.
            - Do not use tables, multiple columns, images, code blocks, or horizontal rules.
            - Then write ===COVER LETTER=== on a separate line, followed by the complete cover letter (body paragraphs only; do not add a title). 
            The cover letter should be in prose format without any Markdown formatting, especially no bolding of numbers—the bolding rules above apply only to the CV.
            - Finally, write ===ADDED SKILLS=== on a separate line. 
            List, one per line, any skills you included in the CV or cover letter that are not supported by any of the factual sources above (the resume and the “additional confirmed experience and skills”). 
            List only the skill name, with no explanation. 
            Skills explicitly confirmed by the user are supported evidence and must not be listed. If there are none, write None.
            - Do not output any other explanation.
            """



def glm_chat(prompt):
    key = os.environ.get("OPEN_AI_KEY")
    if not key:
        raise HTTPException(500, "cant find OPEN_AI_KEY in environment variables")

    client = OpenAI(api_key=f"{key}")

    messages: list[ChatCompletionMessageParam] = [
        cast(ChatCompletionSystemMessageParam,
             cast(object, {"role": "system", "content": "You are an ATS screening simulator. "})),
        cast(ChatCompletionUserMessageParam, cast(object, {"role": "user", "content": prompt})),
    ]

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=messages,
    )

    return response.choices[0].message.content


def parse_json_response(text):
    text = text.strip()
    # match the ``` json ... ``` block if present
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in response: {text[:200]}")
    return json.loads(text[start:end + 1])

def local_checks(cv):
    low = cv.lower()
    heads = [h for h in ("experience", "education", "skills") if h in low]
    bullets = [l for l in cv.splitlines() if l.strip().startswith(("-", "*", "•"))]
    # find the rows with number in the content
    quant = sum(1 for b in bullets if re.search(r"\d", b))
    # ponytail: 前 5 行是联系方式区，"a | b | c" 是 ATS 安全惯例；只有正文里多竖线的行才算表格
    table_lines = [l for l in cv.splitlines()[:5] if l.count("|") >= 2]
    """
    value_if_true IF condition ELSE value_if_false
    value_if_true IF condition ELSE value_if_false FOR item IN collection
    value_if_true FOR item IN collection IF condition ELSE value_if_false
    """
    return [
        {
            "name": "Essential Sections",
            "pass": len(heads) == 3,
            "detail": "Experience/Education/Skills Exist" if len(heads) == 3 else f"Only found {len(heads)}/3 essential section."
        },
        {
            "name": "No Table Structure",
            "pass": not table_lines,
            "detail": "No table structure detected" if not table_lines else f"{len(table_lines)} lines suspected to be tables (multiple '|'), most ATS parsers would be confused"
        },
        {
            "name": "Quantified Achievements",
            "pass": bool(bullets) and quant >= len(bullets) * 0.5,
            "detail": f"{quant}/{len(bullets)} experience entries contain numbers" if bullets else "No experience entries detected"
        },
    ]