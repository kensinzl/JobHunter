from repository.db_repository import db, kv_get, kv_set, upsert_job
import collections, functools, json, os, re, sys
from configure.configure import SKILLS, UA, BLOCK_TAGS
import httpx
from bs4 import BeautifulSoup


def fact_base(conn):
    """生成和技能匹配共用的事实来源：主履历（Profile 优先）+ 用户后来补充确认的经历。"""
    return (profile_or_master(conn) + "\n" + kv_get(conn, "cv_extra")).strip()

def profile_or_master(conn):
    """主事实源：Profile 非空用渲染文本，否则回落到 cv_master 原文（老数据不用迁移）。"""
    try:
        rendered = _render_profile(json.loads(kv_get(conn, "profile") or "{}"))
    except ValueError:
        rendered = ""
    return rendered or kv_get(conn, "cv_master")

def _render_profile(p):
    """结构化 Profile → 生成 prompt 要求的 markdown 履历结构。空字段跳过。"""
    if not p:
        return ""
    b = p.get("basic") or {}
    lines = [f"# {b['name']}"] if b.get("name") else []
    contact = " | ".join(x for x in (b.get("location"), b.get("email"), b.get("phone"), b.get("links")) if x)
    if contact:
        lines.append(contact)
    if p.get("summary"):
        lines += ["", "## Professional Summary", p["summary"]]
    if p.get("skills"):
        lines += ["", "## Skills", ", ".join(p["skills"])]
    if p.get("experience"):
        lines += ["", "## Experience"]
        for e in p["experience"]:
            head = e.get("title") or ""
            if e.get("company"):
                head += f" — {e['company']}"
            if e.get("location"):
                head += f", {e['location']}"
            dates = " - ".join(x for x in (e.get("start"), e.get("end")) if x)
            if dates:
                head += f" ({dates})"
            lines += ["", f"### {head}"] + [f"- {x}" for x in e.get("bullets") or [] if x]
    if p.get("education"):
        lines += ["", "## Education"]
        for e in p["education"]:
            row = " — ".join(x for x in (e.get("degree"), e.get("school")) if x)
            if e.get("year"):
                row += f" ({e['year']})"
            lines.append(f"- {row}")
    if p.get("other"):
        lines += ["", "## Other", p["other"]]
    return "\n".join(lines).strip()



def fetch_jd_if_not_exist(conn, job):
    """有就直接给，没有就现抓一次并存下来。抓不到返回空串，由调用方决定怎么提示。"""
    if job["jd"]:
        return job["jd"]
    if not job["url"]:
        return ""
    try:
        jd = _fetch_jd(job["url"])
    except Exception:
        jd = ""
    if jd:
        conn.execute("UPDATE jobs SET jd=? WHERE id=?", (jd, job["id"]))
        conn.commit()
    return jd

def _fetch_jd(url):
    r = httpx.get(url, headers=UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    node = (soup.select_one('[data-automation="jobAdDetails"]')
            or soup.select_one(".show-more-less-html__markup")
            or soup.select_one(".description__text"))
    return _jd_text(node) if node else ""

def _jd_text(node):
    """
    把 JD 的 HTML 压成纯文本，只在块级元素处换行。

    get_text("\\n") 会在每个内联标签处也断行，一句话被 <b>/<a> 切成三行；
    换行只按块级来，句子才完整——前端排版和喂给模型的 JD 都靠这个。
    """
    for li in node.select("li"):
        if li.find(["ul", "ol"]):
            continue  # 嵌套列表交给里层的 li，别把子列表压没了
        li.string = "• " + li.get_text(" ", strip=True)  # 项目符号是 JD 里的要求清单，必须留
    for br in node.find_all("br"):
        br.replace_with("\n")
    for tag in node.find_all(BLOCK_TAGS):
        tag.append("\n")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", node.get_text(""))).strip()


