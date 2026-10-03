import json, re
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from configure.configure import UA
from bs4 import BeautifulSoup
from service.job_service import _fetch_jd


# 搜索条件变了就把上一轮的结果清掉，只留下你已经处理过的——那是求职历史，删了不可恢复。
# 「已挂」也留着：不留的话下次搜索它又冒出来，你还得重新判断一遍。
# 只有「新」和「忽略」会被清，列表才跟当前搜索条件对得上。
KEEP_ON_CLEAR = ("interested", "applied", "interviewing", "offer", "rejected")

# 经验等级：LinkedIn f_E 码 + 本地标题词。Seek 无原生等级参数，只能靠标题兜底。
# 词表刻意保守：不收 staff（误伤 Staff Nurse）、不收 manager（太泛），宁可漏排不误杀。
LEVELS = {
    "intern": ("1", ("intern", "internship")),
    "junior": ("2,3", ("junior", "jnr", "graduate", "grad", "entry", "trainee", "cadet")),
    "mid_senior": ("4", ("senior", "sr")),
    "director_plus": ("5,6", ("lead", "principal", "head", "director", "chief", "executive", "vp")),
}


def search_key(prefs):
    """只有影响搜索结果的字段算数，改个不相干的键不该清空列表�����"""
    return json.dumps({k: prefs.get(k, "") for k in
                       ("keywords", "location", "salary_min", "worktype", "exclude", "levels")},
                      sort_keys=True)


def scrape_seek_all_jobs(prefs):
    keyword_values = [k.strip().lower() for k in str(prefs.get("keywords", "")).split(",") if k.strip()]
    jobs = []
    for keyword in keyword_values:
        params = {"siteKey": "AU-Main", "sourcesystem": "houston", "keywords": keyword, "sortmode": "ListedDate",
                    "dateRange": "7", "where": "All Australia", "worktype": "242%2C244", "salaryrange": "120000-200000"}

        with httpx.Client(headers=UA, timeout=30) as client:
            for page in range(0, 100):
                r = client.get("https://www.seek.com.au/api/jobsearch/v5/search", params={**params, "page": page, "pageSize": 100})
                r.raise_for_status()
                payload = r.json()
                items = payload.get("data", [])

                if not items:
                    print(f"Keyword={keyword} - SEEK page {page} is last page ...")
                    break

                # only for Sydney and Melbourne
                syd_mel_items = [job
                            for job in items
                                if any(loc.lower() in (job.get("locations") or [])[0].get("label", "").lower() for loc in ["Sydney", "Melbourne"])
                         ]

                with ThreadPoolExecutor(max_workers=30) as pool:
                    for job, jd in zip(syd_mel_items, pool.map(_fetch_jd, [f"https://www.seek.com.au/job/{d.get('id')}" for d in syd_mel_items])):
                        loc = (job.get("locations") or [])[0].get("label", "") if (job.get("locations") or []) else ""
                        title = job.get("title", "")
                        if _whole_word_in(jd, "spring") or _whole_word_in(jd, "java") or _whole_word_in(title, "ai") or _whole_word_in(title, "forward"):
                            jobs.append(
                                {
                                    "title": title,
                                    "company": (job.get("advertiser") or {}).get("description", ""),
                                    "location": loc,
                                    "url": f"https://www.seek.com.au/job/{job.get('id')}",
                                    "listed_at": (job.get("listingDate") or "")[:10]
                                }
                            )

                print(f"Keyword={keyword} - SEEK page {page} with {len(items)}, Total Jobs {len(jobs)} ...")
    return jobs



def scrape_seek(prefs):
    params = {
                "siteKey": "AU-Main",
                "sourcesystem": "houston",
                "keywords": prefs.get("keywords", ""),
                "where": prefs.get("location", ""),
                "pageSize": "50",
                "sortmode": "ListedDate"
            }
    salary = _normalize_salary(prefs.get("salary_min"))
    if salary:
        params["salaryrange"] = f"{salary}-"
        params["salarytype"] = "annual"
    if prefs.get("worktype"):
        params["worktype"] = prefs["worktype"]
    r = httpx.get("https://www.seek.com.au/api/jobsearch/v5/search",
                  params = params,
                  headers = UA,
                  timeout = 30)
    r.raise_for_status()
    jobs = []
    for d in r.json().get("data", []):
        loc = d.get("locations") or []
        jobs.append(
                    {
                     "title": d.get("title", ""),
                     "company": (d.get("advertiser") or {}).get("description", ""),
                     "location": loc[0].get("label", "") if loc else "",
                     "url": f"https://www.seek.com.au/job/{d.get('id')}",
                     "listed_at": (d.get("listingDate") or "")[:10] # first 10 chars of "2024-06-01T12:34:56Z"
                     }
        )
    return jobs





def scrape_linkedin(prefs):
    keyword_values = [k.strip().lower() for k in str(prefs.get("keywords", "")).split(",") if k.strip()]

    jobs = []
    for keyword in keyword_values:
        # ponytail: guest API 返回 404（被封），改抓公��搜��页 SSR HTML，单页 ~60 条够用
        params = {
                  "keywords": keyword,
                  "location": prefs.get("location", "")
        }
        # fe = _levels_fe(prefs.get("levels", ""))
        # if fe:
        #     params["f_E"] = fe
        r = httpx.get("https://www.linkedin.com/jobs/search", params=params,
                      headers=UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        temp_jobs = _parse_linkedin_cards(r.text)
        jobs.extend(temp_jobs)

    return jobs


def _normalize_salary(s):
    """宽进严出："100k" / "100,000" / "$100000" 都归一成 "100000"；解析不出来就丢弃，别把垃圾传给 Seek。"""
    m = re.fullmatch(r"\$?\s*(\d+(?:[.,]\d+)*)\s*([kK])?", str(s or "").strip())
    if not m:
        return ""
    num = float(m.group(1).replace(",", ""))
    return str(int(num * 1000 if m.group(2) else num))


def level_excluded(title, levels_csv):
    selected = {k for k in levels_csv.split(",") if k in LEVELS}
    if not selected:
        return False
    tokens = set(re.findall(r"[a-z]+", title.lower()))
    hit = {k for k, (_, words) in LEVELS.items() if tokens & set(words)}
    # 无等级词的标题一律保留：大量职位就叫 "Data Analyst"，漏筛好过��职位
    return bool(hit) and not (hit & selected)


def _levels_fe(levels_csv):
    return ",".join(LEVELS[k][0] for k in levels_csv.split(",") if k in LEVELS)


def _parse_linkedin_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for card in soup.select("div.base-card"):
        a = card.select_one("a.base-card__full-link")
        title = card.select_one("h3.base-search-card__title")
        company = card.select_one("h4.base-search-card__subtitle")
        loc = card.select_one("span.job-search-card__location")
        t = card.select_one("time")
        if not (a and title and company):
            continue

        job_url = (a.get("href") or "").split("?")[0]
        if not job_url:
            continue

        cards.append({
            "url": job_url,
            "title": title.get_text(strip=True),
            "company": company.get_text(strip=True),
            "location": loc.get_text(strip=True) if loc else "",
            "listed_at": t.get("datetime", "") if t else "",
        })

    #max_workers = min(8, max(1, len(cards)))
    jobs = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        for card, jd in zip(cards, pool.map(_fetch_jd, [card["url"] for card in cards])):
            try:
                match = _whole_word_in(jd, "spring") or _whole_word_in(jd, "ai")
            except Exception:
                match = False
            if match:
                jobs.append({
                    "title": card["title"],
                    "company": card["company"],
                    "location": card["location"],
                    "url": card["url"],
                    "listed_at": card["listed_at"],
                })
    return jobs

def excluded(title, exclude_csv):
    words = [w.strip().lower() for w in exclude_csv.split(",") if w.strip()]
    return any(w in title.lower() for w in words)

def _whole_word_in(text, word):
    """Return True only when `word` appears as a standalone word, not as part of a larger token."""
    if not text:
        return False
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", text, flags=re.I))
