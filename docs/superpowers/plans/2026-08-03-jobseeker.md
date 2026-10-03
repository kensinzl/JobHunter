# jobSeeker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local job-hunting system: scrape Seek + LinkedIn per user preferences, store CV/cover-letter knowledge, generate ATS-optimized customized CV + cover letter per job via GLM API.

**Architecture:** Single FastAPI backend (`server.py`) + single-page frontend (`index.html`) + SQLite. Scrapers hit public JSON/guest endpoints with browser headers (no headless browser — gets blocked). GLM (Zhipu, OpenAI-compatible) does generation.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, httpx, beautifulsoup4, python-dotenv, vanilla JS.

## Global Constraints

- No Playwright/headless browsers. Scrapers use httpx + browser User-Agent only.
- GLM endpoint: `https://open.bigmodel.cn/api/paas/v4/chat/completions`, key from `.env` `OPEN_AI_KEY`, model from `GLM_MODEL` (default `glm-4.6`).
- Generation red line: prompt must forbid fabricating experience — only rewording/reordering/keyword alignment.
- Everything lives in repo root: `server.py`, `index.html`, `test_smoke.py`. Keep it to these files.
- `.env`, `../../../JobHunter.db` never committed.
- External network calls never run in `test_smoke.py` (manual `--test-scrape` flag instead).

---

### Task 1: Scaffold, DB, kv + jobs storage API

**Files:**
- Create: `requirements.txt`, `.gitignore`, `.env.example`, `server.py`
- Test: `test_smoke.py`

**Interfaces:**
- Produces: `db()` → sqlite3 conn (row_factory=Row, schema ensured); `upsert_job(conn, source, title, company, location, url, listed_at)` → job id (dedup on company+title); HTTP: `GET/PUT /api/kv/{key}` (body `{"value": str}`), `GET /api/jobs`, `PATCH /api/jobs/{id}` (body may contain `status` and/or `jd`), `POST /api/jobs` (manual add: `{title, company, location?, url?, jd?}`), `GET /` serves index.html.

- [ ] **Step 1: Write scaffolding files**

`requirements.txt`:
```
fastapi
uvicorn
httpx
beautifulsoup4
python-dotenv
```

`.gitignore`:
```
.env
jobseeker.db
__pycache__/
```

`.env.example`:
```
OPEN_AI_KEY=your-key-here
GLM_MODEL=glm-4.6
```

- [ ] **Step 2: Write failing tests**

`test_smoke.py`:

```python
import os, tempfile

os.environ["JOBSEEKER_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
import main


def test_kv_roundtrip():
    with main.db() as conn:
        main.kv_set(conn, "cv_master", "my cv text")
        assert server.kv_get(conn, "cv_master") == "my cv text"
        server.kv_set(conn, "cv_master", "v2")
        assert main.kv_get(conn, "cv_master") == "v2"
        assert main.kv_get(conn, "missing") == ""


def test_upsert_job_dedup():
    with server.db() as conn:
        a = server.upsert_job(conn, "seek", "Data Analyst", "Acme", "Sydney", "http://x/1", "2026-08-01")
        b = main.upsert_job(conn, "linkedin", "Data Analyst", "Acme", "Sydney NSW", "http://y/2", "2026-08-02")
        assert a == b  # same company+title = same job
        c = main.upsert_job(conn, "seek", "Data Engineer", "Acme", "Sydney", "http://x/3", "2026-08-01")
        assert c != a
```

- [ ] **Step 3: Run tests, verify fail** — `python -m pytest test_smoke.py -v` → FAIL (no server module attrs).

- [ ] **Step 4: Implement `server.py` base**

```python
import json, os, re, sys
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import sqlite3

load_dotenv()
ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("JOBSEEKER_DB", os.path.join(ROOT, "JobHunter.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, title TEXT, company TEXT, location TEXT, url TEXT,
  listed_at TEXT, status TEXT DEFAULT 'new', jd TEXT DEFAULT '',
  UNIQUE(company, title)
);
CREATE TABLE IF NOT EXISTS generations (
  job_id INTEGER PRIMARY KEY, cv TEXT, cover_letter TEXT
);
"""

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

def kv_get(conn, key):
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else ""

def kv_set(conn, key, value):
    conn.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()

def upsert_job(conn, source, title, company, location, url, listed_at):
    conn.execute("""INSERT INTO jobs(source,title,company,location,url,listed_at)
        VALUES(?,?,?,?,?,?) ON CONFLICT(company,title) DO NOTHING""",
        (source, title.strip(), company.strip(), location, url, listed_at))
    conn.commit()
    return conn.execute("SELECT id FROM jobs WHERE company=? AND title=?",
                        (company.strip(), title.strip())).fetchone()["id"]

app = FastAPI()

@app.get("/")
def home():
    return FileResponse(os.path.join(ROOT, "index.html"))

@app.get("/api/kv/{key}")
def api_kv_get(key: str):
    with db() as conn:
        return {"value": kv_get(conn, key)}

@app.put("/api/kv/{key}")
def api_kv_put(key: str, body: dict):
    with db() as conn:
        kv_set(conn, key, body.get("value", ""))
    return {"ok": True}

@app.get("/api/jobs")
def api_jobs():
    with db() as conn:
        rows = conn.execute("""SELECT j.*, g.job_id IS NOT NULL AS generated
            FROM jobs j LEFT JOIN generations g ON g.job_id=j.id
            ORDER BY j.id DESC""").fetchall()
        return [dict(r) for r in rows]

@app.patch("/api/jobs/{job_id}")
def api_job_patch(job_id: int, body: dict):
    with db() as conn:
        for field in ("status", "jd"):
            if field in body:
                conn.execute(f"UPDATE jobs SET {field}=? WHERE id=?", (body[field], job_id))
        conn.commit()
    return {"ok": True}

@app.post("/api/jobs")
def api_job_add(body: dict):
    if not body.get("title") or not body.get("company"):
        raise HTTPException(422, "title and company required")
    with db() as conn:
        jid = upsert_job(conn, "manual", body["title"], body["company"],
                         body.get("location", ""), body.get("url", ""), "")
        if body.get("jd"):
            conn.execute("UPDATE jobs SET jd=? WHERE id=?", (body["jd"], jid))
            conn.commit()
    return {"id": jid}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

- [ ] **Step 5: Run tests, verify pass** — `python -m pytest test_smoke.py -v` → 2 PASS.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: scaffold server with sqlite storage and kv/jobs API"`

---

### Task 2: Seek + LinkedIn scrapers, search endpoint

**Files:**
- Modify: `server.py` (append scraper section before `app = FastAPI()` line is fine anywhere at module level)
- Test: `test_smoke.py` (append)

**Interfaces:**
- Consumes: `db()`, `upsert_job()` from Task 1.
- Produces: `parse_linkedin_cards(html) -> list[dict]` (keys: title, company, location, url, listed_at); `scrape_seek(prefs) -> list[dict]` (same keys); `scrape_linkedin(prefs) -> list[dict]`; HTTP `POST /api/search` → `{"added": int, "warnings": [str]}`. prefs dict keys: `keywords, location, salary_min, worktype, exclude` (all str). CLI: `python server.py --test-scrape`.

- [ ] **Step 1: Write failing test for LinkedIn HTML parsing** (append to `test_smoke.py`):

```python
LINKEDIN_FIXTURE = """
<ul><li><div class="base-card">
<a class="base-card__full-link" href="https://au.linkedin.com/jobs/view/data-analyst-at-acme-4012345678?refId=x">link</a>
<h3 class="base-search-card__title"> Data Analyst </h3>
<h4 class="base-search-card__subtitle"><a>Acme Corp</a></h4>
<span class="job-search-card__location">Sydney, NSW</span>
<time class="job-search-card__listdate" datetime="2026-07-30"></time>
</div></li></ul>
"""

def test_parse_linkedin_cards():
    jobs = server.parse_linkedin_cards(LINKEDIN_FIXTURE)
    assert jobs == [{"title": "Data Analyst", "company": "Acme Corp",
                     "location": "Sydney, NSW",
                     "url": "https://au.linkedin.com/jobs/view/data-analyst-at-acme-4012345678",
                     "listed_at": "2026-07-30"}]


def test_exclude_filter():
    assert server.excluded("Senior PHP Developer", "php, wordpress") is True
    assert server.excluded("Data Analyst", "php, wordpress") is False
    assert server.excluded("Data Analyst", "") is False
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement scrapers** (add to `server.py`):

```python
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-AU,en;q=0.9"}

def excluded(title, exclude_csv):
    words = [w.strip().lower() for w in exclude_csv.split(",") if w.strip()]
    return any(w in title.lower() for w in words)

def scrape_seek(prefs):
    params = {"siteKey": "AU-Main", "sourcesystem": "houston",
              "keywords": prefs.get("keywords", ""), "where": prefs.get("location", ""),
              "pageSize": "50", "sortmode": "ListedDate"}
    if prefs.get("salary_min"):
        params["salaryrange"] = f"{prefs['salary_min']}-"
        params["salarytype"] = "annual"
    if prefs.get("worktype"):
        params["worktype"] = prefs["worktype"]
    r = httpx.get("https://www.seek.com.au/api/jobsearch/v5/search",
                  params=params, headers=UA, timeout=30)
    r.raise_for_status()
    jobs = []
    for d in r.json().get("data", []):
        loc = d.get("locations") or []
        jobs.append({"title": d.get("title", ""),
                     "company": (d.get("advertiser") or {}).get("description", ""),
                     "location": loc[0].get("label", "") if loc else "",
                     "url": f"https://www.seek.com.au/job/{d.get('id')}",
                     "listed_at": (d.get("listingDate") or "")[:10]})
    return jobs

def parse_linkedin_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.base-card"):
        a = card.select_one("a.base-card__full-link")
        title = card.select_one("h3.base-search-card__title")
        company = card.select_one("h4.base-search-card__subtitle")
        loc = card.select_one("span.job-search-card__location")
        t = card.select_one("time")
        if not (a and title and company):
            continue
        jobs.append({"title": title.get_text(strip=True),
                     "company": company.get_text(strip=True),
                     "location": loc.get_text(strip=True) if loc else "",
                     "url": (a.get("href") or "").split("?")[0],
                     "listed_at": t.get("datetime", "") if t else ""})
    return jobs

def scrape_linkedin(prefs):
    jobs = []
    for start in (0, 25):
        r = httpx.get("https://www.linkedin.com/jobs-guest/jobs/api/seeJobPostings/search",
                      params={"keywords": prefs.get("keywords", ""),
                              "location": prefs.get("location", ""), "start": start},
                      headers=UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        batch = parse_linkedin_cards(r.text)
        jobs += batch
        if len(batch) < 25:
            break
    return jobs

@app.post("/api/search")
def api_search():
    with db() as conn:
        prefs = json.loads(kv_get(conn, "prefs") or "{}")
        added, warnings = 0, []
        for name, fn in (("Seek", scrape_seek), ("LinkedIn", scrape_linkedin)):
            try:
                for j in fn(prefs):
                    if excluded(j["title"], prefs.get("exclude", "")):
                        continue
                    before = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
                    upsert_job(conn, name.lower(), j["title"], j["company"],
                               j["location"], j["url"], j["listed_at"])
                    after = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
                    added += after - before
            except Exception as e:
                warnings.append(f"{name} 抓取失败: {e}")
        return {"added": added, "warnings": warnings}
```

And in the `__main__` block, before uvicorn:
```python
    if "--test-scrape" in sys.argv:
        prefs = {"keywords": "data analyst", "location": "Sydney NSW"}
        print("Seek:", len(scrape_seek(prefs)), "jobs")
        print("LinkedIn:", len(scrape_linkedin(prefs)), "jobs")
        sys.exit(0)
```

- [ ] **Step 4: Run tests, verify pass** — `python -m pytest test_smoke.py -v` → 4 PASS.

- [ ] **Step 5: Manual smoke** — `python server.py --test-scrape`. Expect both counts > 0. If Seek returns 404/400, the API version moved: fetch `https://www.seek.com.au/data-analyst-jobs` HTML, check DevTools-visible XHR path (try `v4`/`chalice-search/v4` variants), adjust URL, re-run. If LinkedIn returns 429, that's the documented degrade path — fine, note it works intermittently.

- [ ] **Step 6: Commit** — `git commit -am "feat: seek + linkedin scrapers and search endpoint"`

---

### Task 3: ATS/AI screening research → rules doc + prompt rules

**Files:**
- Create: `docs/ats-research.md`
- Modify: `server.py` (add `ATS_RULES` constant)

**Interfaces:**
- Produces: `ATS_RULES: str` module-level constant in `server.py`, consumed by Task 4's `build_prompt`.

- [ ] **Step 1: Research.** Use WebSearch (this step needs the orchestrator or a subagent with WebSearch). Queries: "how ATS resume screening works 2026 Workday Greenhouse", "AI resume screening LLM how recruiters use 2025 2026", "resume optimization pass AI screening best practices", "SEEK application AI screening how it works". Read 3-5 solid sources.

- [ ] **Step 2: Write `docs/ats-research.md`** (中文, for the user): how keyword-matching ATS works (parse → index → recruiter keyword search / knockout questions), how newer LLM-based screeners score (relevance to JD, evidence of impact, title alignment), what kills a resume in parsing (tables, columns, graphics, headers/footers, nonstandard headings), and the resulting strategy list. Cite sources.

- [ ] **Step 3: Add `ATS_RULES` to `server.py`.** Start from this baseline, refine with research findings:

```python
ATS_RULES = """ATS/AI 筛选优化规则（必须全部遵守）:
1. 从 JD 提取硬技能、工具名、资质、职位名等关键词，凡属实的都要自然地写进 CV（用 JD 的原始拼写，如 "PowerBI" vs "Power BI" 按 JD 写法）。
2. CV 顶部 Professional Summary 中出现与目标职位一致或最接近的职位名。
3. 只用标准节标题: Professional Summary / Skills / Experience / Education / Certifications。
4. 单栏纯文本结构：禁止表格、多栏、图标、图片、页眉页脚。
5. 每条经历用动词开头 + 量化结果（%、金额、规模、时间）。
6. 倒序时间排列，日期格式统一 "MMM YYYY"。
7. Skills 区罗列 JD 匹配的技能关键词（逗号分隔，便于关键词命中）。
8. 缩写与全称成对出现一次，如 "Search Engine Optimization (SEO)"。
9. 红线：绝不虚构经历、技能、雇主、时间。只做措辞对齐、重点重排、真实技能补写。
10. Cover letter 首段点明职位名与公司名，中段用 1-2 个量化成果对应 JD 的 2-3 个核心要求，尾段行动号召。"""
```

- [ ] **Step 4: Verify** — `python -c "import server; assert len(server.ATS_RULES) > 200"`, tests still pass.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: ATS research doc and generation rules"`

---

### Task 4: JD fetch + GLM generation

**Files:**
- Modify: `server.py`
- Test: `test_smoke.py` (append)

**Interfaces:**
- Consumes: `ATS_RULES` (Task 3), `db()`, `kv_get` (Task 1).
- Produces: `build_prompt(jd, title, company, cv, cl_sample, cl_format) -> str`; `split_output(text) -> (cv, cover_letter)`; `fetch_jd(url) -> str`; HTTP `POST /api/jobs/{id}/generate` → `{"cv": str, "cover_letter": str}` (422 if no JD obtainable — user must paste; 500 with detail on GLM error); `GET /api/jobs/{id}/generation` → same shape or 404.

- [ ] **Step 1: Write failing tests** (append):

```python
def test_build_prompt_contains_everything():
    p = server.build_prompt("JD text here", "Analyst", "Acme", "my cv", "my sample", "short and punchy")
    for chunk in ("JD text here", "Analyst", "Acme", "my cv", "my sample", "short and punchy", "===COVER LETTER==="):
        assert chunk in p
    assert "虚构" in p or "fabricat" in p.lower()


def test_split_output():
    cv, cl = server.split_output("CV BODY\n===COVER LETTER===\nCL BODY")
    assert cv == "CV BODY" and cl == "CL BODY"
    cv2, cl2 = server.split_output("no delimiter at all")
    assert cv2 == "no delimiter at all" and cl2 == ""
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** (add to `server.py`):

```python
def build_prompt(jd, title, company, cv, cl_sample, cl_format):
    return f"""你是资深求职顾问。为下面这个职位定制一份 CV 和一份 cover letter，输出语言与 JD 语言一致（英文 JD 就输出英文）。

{ATS_RULES}

# 目标职位: {title} @ {company}
# JD 全文
{jd}

# 我的完整履历（唯一事实来源，不得虚构其外的内容）
{cv}

# 我的 cover letter 范文（模仿其风格）
{cl_sample}

# 我要求的 cover letter 格式偏好
{cl_format}

输出格式（严格遵守）：先输出完整 CV（Markdown，单栏结构），然后单独一行写 ===COVER LETTER===，再输出完整 cover letter。不要输出任何其他解释。"""

def split_output(text):
    parts = text.split("===COVER LETTER===")
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")

def fetch_jd(url):
    r = httpx.get(url, headers=UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    node = (soup.select_one('[data-automation="jobAdDetails"]')
            or soup.select_one(".show-more-less-html__markup")
            or soup.select_one(".description__text"))
    return node.get_text("\n", strip=True) if node else ""

def glm_chat(prompt):
    key = os.environ.get("OPEN_AI_KEY")
    if not key:
        raise HTTPException(500, "OPEN_AI_KEY 未配置，请在 .env 中设置")
    r = httpx.post("https://open.bigmodel.cn/api/paas/v4/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": os.environ.get("GLM_MODEL", "glm-4.6"),
                         "messages": [{"role": "user", "content": prompt}],
                         "temperature": 0.4},
                   timeout=300)
    if r.status_code != 200:
        raise HTTPException(500, f"GLM API 错误 {r.status_code}: {r.text[:500]}")
    return r.json()["choices"][0]["message"]["content"]

@app.post("/api/jobs/{job_id}/generate")
def api_generate(job_id: int):
    with db() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "job not found")
        jd = job["jd"]
        if not jd and job["url"]:
            try:
                jd = fetch_jd(job["url"])
            except Exception:
                jd = ""
            if jd:
                conn.execute("UPDATE jobs SET jd=? WHERE id=?", (jd, job_id))
                conn.commit()
        if not jd:
            raise HTTPException(422, "抓不到 JD，请在职位列表里手动粘贴 JD 后重试")
        cv = kv_get(conn, "cv_master")
        if not cv:
            raise HTTPException(422, "知识库里还没有你的 CV 原文")
        out = glm_chat(build_prompt(jd, job["title"], job["company"], cv,
                                    kv_get(conn, "cl_sample"), kv_get(conn, "cl_format")))
        gen_cv, gen_cl = split_output(out)
        conn.execute("INSERT INTO generations(job_id,cv,cover_letter) VALUES(?,?,?) "
                     "ON CONFLICT(job_id) DO UPDATE SET cv=excluded.cv, cover_letter=excluded.cover_letter",
                     (job_id, gen_cv, gen_cl))
        conn.commit()
        return {"cv": gen_cv, "cover_letter": gen_cl}

@app.get("/api/jobs/{job_id}/generation")
def api_get_generation(job_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM generations WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "not generated yet")
        return {"cv": row["cv"], "cover_letter": row["cover_letter"]}
```

- [ ] **Step 4: Run tests, verify pass** — all 6 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: JD fetch and GLM generation endpoint"`

---

### Task 5: Frontend (index.html)

**Files:**
- Create: `index.html`

**Interfaces:**
- Consumes: all HTTP endpoints from Tasks 1/2/4. kv keys used: `prefs` (JSON string), `cv_master`, `cl_sample`, `cl_format`.

- [ ] **Step 1: Write `index.html`** — 4 tabs (偏好 / 知识库 / 职位 / 生成), vanilla JS, minimal CSS, print stylesheet that shows only the preview pane. Full file:

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>jobSeeker</title>
<style>
  body { font-family: -apple-system, sans-serif; margin: 0; background: #f5f5f7; }
  nav { display: flex; gap: 4px; padding: 12px 16px 0; background: #fff; border-bottom: 1px solid #ddd; }
  nav button { border: 1px solid #ddd; border-bottom: none; background: #eee; padding: 8px 20px; border-radius: 8px 8px 0 0; cursor: pointer; font-size: 14px; }
  nav button.active { background: #fff; font-weight: 600; }
  main { padding: 20px; max-width: 1000px; margin: 0 auto; }
  section { display: none; } section.active { display: block; }
  label { display: block; margin: 12px 0 4px; font-size: 13px; color: #555; }
  input[type=text], select, textarea { width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #ccc; border-radius: 6px; font-size: 14px; }
  textarea { min-height: 160px; font-family: inherit; }
  button.primary { margin-top: 14px; padding: 9px 22px; background: #0a66c2; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
  button.primary:disabled { opacity: .5; }
  table { width: 100%; border-collapse: collapse; background: #fff; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; }
  .warn { background: #fff3cd; border: 1px solid #ffe08a; padding: 8px 12px; border-radius: 6px; margin: 10px 0; font-size: 13px; }
  .ok { color: #1a7f37; font-size: 13px; margin-left: 10px; }
  #preview { background: #fff; border: 1px solid #ddd; padding: 40px 48px; margin-top: 16px; line-height: 1.5; }
  #preview[contenteditable] { outline: none; }
  #preview h1 { font-size: 22px; margin: 0 0 4px; } #preview h2 { font-size: 15px; border-bottom: 1px solid #333; padding-bottom: 2px; margin: 18px 0 8px; }
  #preview ul { margin: 4px 0; padding-left: 20px; }
  .status-new { color: #0a66c2; } .status-interested { color: #9a6700; } .status-applied { color: #1a7f37; } .status-ignored { color: #999; }
  @media print { body * { visibility: hidden; } #preview, #preview * { visibility: visible; } #preview { position: absolute; left: 0; top: 0; width: 100%; border: none; margin: 0; } }
</style>
</head>
<body>
<nav>
  <button data-tab="prefs" class="active">求职偏好</button>
  <button data-tab="knowledge">知识库</button>
  <button data-tab="jobs">职位列表</button>
  <button data-tab="gen">生成</button>
</nav>
<main>
<section id="prefs" class="active">
  <label>职位关键词</label><input type="text" id="p-keywords" placeholder="data analyst">
  <label>地点</label><input type="text" id="p-location" placeholder="Sydney NSW">
  <label>年薪下限 (AUD)</label><input type="text" id="p-salary">
  <label>工作类型</label>
  <select id="p-worktype"><option value="">不限</option><option value="242">全职</option><option value="244">合同/临时</option><option value="243">兼职</option></select>
  <label>排除关键词（逗号分隔，命中职位名即忽略）</label><input type="text" id="p-exclude" placeholder="senior, php">
  <button class="primary" onclick="savePrefs()">保存</button><span id="p-saved" class="ok"></span>
</section>

<section id="knowledge">
  <label>CV 原文（完整履历，事实来源）</label><textarea id="k-cv_master"></textarea>
  <label>Cover letter 范文（模仿风格）</label><textarea id="k-cl_sample"></textarea>
  <label>Cover letter 格式偏好（语气 / 段落结构 / 称呼等）</label><textarea id="k-cl_format"></textarea>
  <button class="primary" onclick="saveKnowledge()">保存</button><span id="k-saved" class="ok"></span>
</section>

<section id="jobs">
  <button class="primary" onclick="runSearch()" id="search-btn">搜索 Seek + LinkedIn</button>
  <div id="warnings"></div>
  <table><thead><tr><th>职位</th><th>公司</th><th>地点</th><th>来源</th><th>日期</th><th>状态</th><th></th></tr></thead>
  <tbody id="job-rows"></tbody></table>
  <details style="margin-top:16px"><summary>手动添加职位</summary>
    <label>职位名</label><input type="text" id="m-title">
    <label>公司</label><input type="text" id="m-company">
    <label>链接（可选）</label><input type="text" id="m-url">
    <label>JD 全文（可选，抓不到时粘贴）</label><textarea id="m-jd"></textarea>
    <button class="primary" onclick="addManual()">添加</button>
  </details>
</section>

<section id="gen">
  <label>选择职位</label><select id="g-job"></select>
  <button class="primary" id="g-btn" onclick="generate()">生成定制 CV + Cover Letter</button>
  <span id="g-status" class="ok"></span>
  <div style="margin-top:12px">
    <button onclick="showDoc('cv')">看 CV</button>
    <button onclick="showDoc('cl')">看 Cover Letter</button>
    <button onclick="window.print()">打印 / 存 PDF</button>
    <span style="font-size:12px;color:#888">预览可直接点击编辑</span>
  </div>
  <div id="preview" contenteditable="true"></div>
</section>
</main>

<script>
const $ = id => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then(async r => {
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
});

document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button, section").forEach(e => e.classList.remove("active"));
  b.classList.add("active"); $(b.dataset.tab).classList.add("active");
  if (b.dataset.tab === "jobs") loadJobs();
  if (b.dataset.tab === "gen") loadJobOptions();
});

// prefs
async function loadPrefs() {
  const p = JSON.parse((await api("/api/kv/prefs")).value || "{}");
  for (const k of ["keywords","location","salary","worktype","exclude"])
    $("p-" + k).value = p[k === "salary" ? "salary_min" : k] || "";
}
async function savePrefs() {
  const p = { keywords: $("p-keywords").value, location: $("p-location").value,
              salary_min: $("p-salary").value, worktype: $("p-worktype").value, exclude: $("p-exclude").value };
  await api("/api/kv/prefs", { method: "PUT", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ value: JSON.stringify(p) }) });
  flash("p-saved");
}

// knowledge
async function loadKnowledge() {
  for (const k of ["cv_master","cl_sample","cl_format"])
    $("k-" + k).value = (await api("/api/kv/" + k)).value;
}
async function saveKnowledge() {
  for (const k of ["cv_master","cl_sample","cl_format"])
    await api("/api/kv/" + k, { method: "PUT", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ value: $("k-" + k).value }) });
  flash("k-saved");
}
function flash(id) { $(id).textContent = "已保存 ✓"; setTimeout(() => $(id).textContent = "", 2000); }

// jobs
const STATUSES = { new: "新", interested: "感兴趣", applied: "已投", ignored: "忽略" };
async function loadJobs() {
  const jobs = await api("/api/jobs");
  $("job-rows").innerHTML = jobs.map(j => `<tr>
    <td><a href="${j.url}" target="_blank">${j.title}</a></td><td>${j.company}</td>
    <td>${j.location}</td><td>${j.source}</td><td>${j.listed_at || ""}</td>
    <td><select onchange="setStatus(${j.id}, this.value)">${Object.entries(STATUSES).map(([v,t]) =>
      `<option value="${v}" ${v===j.status?"selected":""}>${t}</option>`).join("")}</select></td>
    <td>${j.jd ? "" : `<button onclick="pasteJD(${j.id})">贴JD</button>`}</td></tr>`).join("");
}
async function runSearch() {
  $("search-btn").disabled = true; $("search-btn").textContent = "搜索中…";
  try {
    const r = await api("/api/search", { method: "POST" });
    $("warnings").innerHTML = r.warnings.map(w => `<div class="warn">${w}</div>`).join("");
    await loadJobs();
  } catch (e) { alert(e.message); }
  $("search-btn").disabled = false; $("search-btn").textContent = "搜索 Seek + LinkedIn";
}
async function setStatus(id, status) {
  await api(`/api/jobs/${id}`, { method: "PATCH", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ status }) });
}
async function pasteJD(id) {
  const jd = prompt("粘贴 JD 全文：");
  if (jd) { await api(`/api/jobs/${id}`, { method: "PATCH", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ jd }) }); loadJobs(); }
}
async function addManual() {
  await api("/api/jobs", { method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ title: $("m-title").value, company: $("m-company").value, url: $("m-url").value, jd: $("m-jd").value }) });
  loadJobs();
}

// generation
let docs = { cv: "", cl: "" };
async function loadJobOptions() {
  const jobs = await api("/api/jobs");
  $("g-job").innerHTML = jobs.filter(j => j.status !== "ignored")
    .map(j => `<option value="${j.id}">${j.title} — ${j.company}${j.generated ? " ✓已生成" : ""}</option>`).join("");
}
async function generate() {
  $("g-btn").disabled = true; $("g-status").textContent = "生成中，约 1-2 分钟…";
  try {
    docs = normalize(await api(`/api/jobs/${$("g-job").value}/generate`, { method: "POST" }));
    showDoc("cv"); $("g-status").textContent = "完成 ✓";
  } catch (e) { $("g-status").textContent = ""; alert(e.message); }
  $("g-btn").disabled = false;
}
function normalize(r) { return { cv: r.cv, cl: r.cover_letter }; }
async function showDoc(which) {
  if (!docs.cv) {
    try { docs = normalize(await api(`/api/jobs/${$("g-job").value}/generation`)); }
    catch { alert("还没生成过"); return; }
  }
  $("preview").innerHTML = md(docs[which]);
}
// minimal markdown: headers, bold, bullets, paragraphs
function md(t) {
  const esc = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;");
  return esc(t).split(/\n{2,}/).map(block => {
    const lines = block.split("\n");
    if (lines.every(l => /^\s*[-*] /.test(l)))
      return "<ul>" + lines.map(l => "<li>" + inline(l.replace(/^\s*[-*] /,"")) + "</li>").join("") + "</ul>";
    return lines.map(l => {
      const h = l.match(/^(#{1,3}) (.*)/);
      if (h) return `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`;
      return `<p>${inline(l)}</p>`;
    }).join("");
  }).join("");
  function inline(s) { return s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); }
}

loadPrefs(); loadKnowledge();
</script>
</body>
</html>
```

- [ ] **Step 2: Manual verify** — `python server.py`, open `http://127.0.0.1:8000`: save prefs → reload page → values persist; save knowledge → persists; search populates table (or shows warn banners); manual add works; generate flow errors cleanly without GLM key.

- [ ] **Step 3: Commit** — `git add index.html && git commit -m "feat: single-page frontend"`

---

### Task 6: README + end-to-end smoke

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`** (中文): setup (`python3 -m venv venv && venv/bin/pip install -r requirements.txt`, copy `.env.example` → `.env`, fill GLM key), run (`venv/bin/python server.py`, open localhost:8000), usage flow (偏好 → 知识库 → 搜索 → 生成 → 打印 PDF), troubleshooting (LinkedIn 429 → 稍后再试或手动粘贴; Seek API 版本变动 → 见 `--test-scrape`), link to `docs/ats-research.md`.

- [ ] **Step 2: Full smoke** — with real `.env`: run server, walk all 4 tabs, generate for one real job, print preview. Fix anything broken.

- [ ] **Step 3: Commit** — `git add -A && git commit -m "docs: README"`
