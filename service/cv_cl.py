import re
from configure.configure import *
from service.service import *


# match Jan 2024 or Jan. 2024 or january 2024
MONTH_YEAR = re.compile(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(\d{4})")
KNOCKOUT = re.compile(r"(?i)(visa|work(ing)? right|permanent resident|\bPR\b|citizen|sponsor|relocat)")
PROFILE_URL = re.compile(r"(?i)(linkedin\.com|github\.com)")

def _months(text):
    return {(month.lower(), year) for month, year in MONTH_YEAR.findall(text)}

def verify_generation(gen_cv, base):
    """
    生成后对着知识库做确定性比对。查的是"不该变的变没变"，和 local_checks 的格式检查互补。

    ponytail: 纯字符串比对，不调模型——日期漂移、雇主改名、淘汰题信息丢失这三类
    都能靠比对抓到，比在 prompt 里求模型别犯错可靠得多。
    """
    # Take the set of month-year pairs in the generated CV, subtract the set of month-year pairs in the base CV, and sort the remaining ones.
    bad = sorted(_months(gen_cv) - _months(base))
    firms = [f.strip() for f in re.findall(r"(?m)^###\s+.*?—\s*([^,(]+)", gen_cv) if f.strip()]
    # 前 5 个字母匹配就算同一家：履历原文可能有乱码（VenturelyVc → Venturelytic），
    # 那种还原是允许的；真换了一家公司前缀对不上
    flat = re.sub(r"[^a-z]", "", base.lower())
    unknown = [f for f in firms if re.sub(r"[^a-z]", "", f.lower())[:5] not in flat]
    checks = [
        {"name": "日期未被改动",
         "pass": not bad,
         "detail": "所有起止日期都能在履历里找到" if not bad else
                   "履历里没有这些日期：" + "、".join(f"{m.title()} {y}" for m, y in bad)},
        {"name": "雇主未被改动",
         "pass": not unknown,
         "detail": f"{len(firms)} 段经历的公司名都对得上" if not unknown else
                   "履历里找不到这些公司：" + "、".join(unknown)},
    ]
    if KNOCKOUT.search(base):
        ok = bool(KNOCKOUT.search(gen_cv))
        checks.append({"name": "工作权利信息保留", "pass": ok,
                       "detail": "签证/工作权利信息还在" if ok else
                                 "履历里写了签证/工作权利，生成的 CV 里没有——澳洲岗位这是淘汰题，会被直接筛掉"})
    if PROFILE_URL.search(base):
        ok = bool(PROFILE_URL.search(gen_cv))
        checks.append({"name": "LinkedIn / GitHub 保留", "pass": ok,
                       "detail": "个人主页链接还在" if ok else "履历里的 LinkedIn / GitHub 链接被丢掉了"})
    return checks


def build_profile_prompt(cv_text):
    return f"""从下面的简历原文中抽取结构化信息。所有内容必须原样来自简历文本，不许推断、补全或改写；找不到的字段给空字符串或空数组。

            只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释，结构：
            {{"basic": {{"name": "", "email": "", "phone": "", "location": "", "links": "个人主页/LinkedIn/GitHub，空格分隔"}},
            "summary": "个人总结原文",
            "skills": ["技能1", "技能2"],
            "experience": [{{"title": "", "company": "", "location": "", "start": "MMM YYYY", "end": "MMM YYYY 或 Present", "bullets": ["职责/成果原句"]}}],
            "education": [{{"degree": "", "school": "", "year": ""}}],
            "other": "证书、奖项、志愿活动等剩余内容"}}
            
            # 简历原文
            {cv_text}"""


def _str(v):
    return str(v) if isinstance(v, (str, int, float)) else ""

def normalize_profile(p):
    """GLM 返回的形状强制归位：错型的字段替换成空值，坏一个字段不该坏掉整个 profile。"""
    if not isinstance(p, dict):
        p = {}
    basic = p.get("basic") if isinstance(p.get("basic"), dict) else {}
    exps = []
    for e in (p.get("experience") if isinstance(p.get("experience"), list) else []):
        if not isinstance(e, dict):
            continue
        bullets = e.get("bullets") if isinstance(e.get("bullets"), list) else []
        exps.append({"title": _str(e.get("title")), "company": _str(e.get("company")),
                     "location": _str(e.get("location")), "start": _str(e.get("start")),
                     "end": _str(e.get("end")), "bullets": [_str(b) for b in bullets if _str(b)]})
    edus = []
    for e in (p.get("education") if isinstance(p.get("education"), list) else []):
        if isinstance(e, dict):
            edus.append({"degree": _str(e.get("degree")), "school": _str(e.get("school")),
                         "year": _str(e.get("year"))})
    skills = p.get("skills") if isinstance(p.get("skills"), list) else []
    return {"basic": {k: _str(basic.get(k)) for k in ("name", "email", "phone", "location", "links")},
            "summary": _str(p.get("summary")), "skills": [_str(s) for s in skills if _str(s)],
            "experience": exps, "education": edus, "other": _str(p.get("other"))}




def merge_extra(old, new):
    """按行去重地追加：生成失败后重试、或重复勾选同一批技能，不该把同一句在知识库里堆多次。"""
    seen = {l.strip() for l in old.splitlines()}
    add = [l for l in new.splitlines() if l.strip() and l.strip() not in seen]
    if not add:
        return old
    return (old + "\n" + "\n".join(add)).strip()






def split_output(text):
    # (before separator, separator itself, after separator)
    body, _, added = text.partition("===ADDED SKILLS===")
    cv, _, cl = body.partition("===COVER LETTER===")
    items = [re.sub(r"^[-*•\d.\s]+", "", l).strip() for l in added.strip().splitlines()]
    items = [i for i in items if i and i not in ("None", "none", "N/A")]
    return cv.strip(), cl.strip(), items

def compute_dropped(base, gen_cv, profile):
    """履历里有、生成 CV 里没写的技能与整段经历。为贴合 JD 精简是规则允许的，但必须如实告知。
    ponytail: 技能走 SKILLS 词表比对（表外的技能名测不到）；经历按公司名前 5 字母找，与 verify 同款。"""
    _, skills = skill_match(base, gen_cv)
    flat = re.sub(r"[^a-z]", "", gen_cv.lower())
    exps = []
    for e in (profile or {}).get("experience") or []:
        comp = (e.get("company") or "").strip()
        key = re.sub(r"[^a-z]", "", comp.lower())[:5]
        if key and key not in flat:
            exps.append(" — ".join(x for x in (e.get("title"), comp) if x))
    return {"skills": list(skills), "experiences": exps}