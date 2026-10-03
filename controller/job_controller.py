from fastapi.responses import Response

from main import app
from service.ai_service import *
from service.cv_cl import *
from service.job_service import *
from service.service import *

"""
Fetch the Jobs info(Position - Company) from Seek + LinkedIn button's results

Build the Has and Miss dict from CV and JD when JD is available

If there is the Generated CV, then show the ✓已生成
"""
@app.get("/api/jobs")
def api_jobs():
    with db() as conn:
        # ponytail: 只回 JD 长度不回正文——全量 JD 是 200×4k，列表每次都拖这么多没意义，
        # 要看正文时再单独取那一条。jd 取出来只在服务端用来算技能匹配。
        # 技能名直接内联进每一行：51 条有 JD 时 payload 124KB，全部抓满约 500KB。
        # 真嫌大就改成回技能在 SKILLS 里的下标，前端拿常量表还原。
        rows = conn.execute("""
        SELECT j.id,
               j.source,
               j.title,
               j.company,
               j.location,
               j.url,
               j.listed_at,
               j.status,
               j.applied_at,
               j.notes,
               j.jd,
               g.job_id IS NOT NULL AS generated
        FROM   jobs j
        LEFT JOIN generations g ON g.job_id = j.id
        ORDER  BY j.id DESC 
        """).fetchall()
        cv = fact_base(conn)
        out = []
        for r in rows:
            d = dict(r)
            jd = d.pop("jd") or ""
            d["jd_len"] = len(jd)
            if jd and cv:
                have, miss = skill_match(jd, cv)
                d["have"], d["miss"] = list(have), list(miss)
            out.append(d)
        return out



"""
Fetch selected Job description and match with uploaded CV to build the Has and Miss dict _ Generate Match Status Button
"""
@app.get("/api/jobs/{job_id}/match")
def api_match(job_id: int):
    with db() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "job not found")
        jd = fetch_jd_if_not_exist(conn, job)
        if not jd:
            raise HTTPException(422, "抓不到 JD，请在职位列表里手动粘贴 JD 后重试")
        if not profile_or_master(conn):
            raise HTTPException(422, "Profile 和 CV 原文都是空的，先在 Profile 页维护或上传 CV")
        have, miss = skill_match(jd, fact_base(conn))
        return {"have": list(have), "miss": list(miss)}



"""
After you select the missing skills, 
click the AI button to generate the draft description for your selected skill

out - example:

{
  "drafts" : [ {
    "skill" : "Generative AI",
    "text" : "在 Reserve Bank Of Australia 的工作中，我开发了基于 Tool Calling、Agent Skills、MCP Servers、Conversational Memory 和 RAG 的 LLM 应用，并结合实时检索与事实核验机制提升生成内容的准确性和可用性。"
  }, {
    "skill" : "Generative AI",
    "text" : "在 NIWA 的项目中，我与 stakeholders 一起推进数据清洗、模型构建和分析结果呈现，结合 R Shiny 将文本分析与聚类等能力整合为可交互的分析应用，支持面向业务的智能内容生成与洞察输出。"
  } ]
}
"""
@app.post("/api/jobs/{job_id}/draft")
def api_draft(job_id: int, body: dict = None):
    """为勾选的缺失技能逐条起草补充描述。用户逐条 ✓/✗ 审核，采纳的只随本次生成使用，不入知识库。"""
    skills = [s.strip() for s in (body or {}).get("skills", []) if isinstance(s, str) and s.strip()]
    if not skills:
        raise HTTPException(422, "没有勾选任何技能")
    with db() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "job not found")
        jd = fetch_jd_if_not_exist(conn, job)
        if not jd:
            raise HTTPException(422, "抓不到 JD，请在职位列表里手动粘贴 JD 后重试")
        cv = fact_base(conn)
        if not cv:
            raise HTTPException(422, "Profile 和 CV 原文都是空的，先在 Profile 页维护或上传 CV")
    out = parse_json_response(glm_chat(build_draft_prompt(jd, cv, skills)))
    return {
            "drafts": [
                        {
                            "skill": str(d.get("skill", "")),
                            "text": str(d.get("text", ""))
                        } for d in out.get("drafts", []) if d.get("text")
                      ]
            }



"""
Generate the changed CV and CL and save into generation table
"""
@app.post("/api/jobs/{job_id}/generate")
def api_generate(job_id: int, body: dict = None):
    """body.extra: 用户确认属实、但主履历里漏写的经历，会先并进知识库再参与生成。
    body.extra_once: 用户逐条采纳的起草描述，只对本次生效。未经用户勾选的技能一律不补。"""
    with db() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "job not found")
        jd = fetch_jd_if_not_exist(conn, job)
        if not jd:
            raise HTTPException(422, "抓不到 JD，请在职位列表里手动粘贴 JD 后重试")
        if not profile_or_master(conn):
            raise HTTPException(422, "Profile 和 CV 原文都是空的，先在 Profile 页维护或上传 CV")
        # extra: user directly type for the supplementary experience and skill
        new = ((body or {}).get("extra") or "").strip()
        if new:
            kv_set(conn, "cv_extra", merge_extra(kv_get(conn, "cv_extra"), new))
        # extra_once: 用户逐条采纳的 AI 起草描述，只对本次生成生效，不并入知识库
        once = ((body or {}).get("extra_once") or "").strip()
        base = (fact_base(conn) + "\n" + once).strip()
        have, miss = skill_match(jd, base)
        out = glm_chat(build_prompt(jd,
                                    job["title"],
                                    job["company"],
                                    profile_or_master(conn),
                                    kv_get(conn, "cl_sample"),
                                    kv_get(conn, "cl_format"),
                                    (kv_get(conn, "cv_extra") + "\n" + once).strip(),
                                    miss
                                    )
                       )
        gen_cv, gen_cl, added = split_output(out)
        # If there is already a row with the same job_id, then DO update,
        # and the excluded.* means “the value that was attempted in the INSERT”.
        conn.execute("INSERT INTO generations(job_id,cv,cover_letter,added) VALUES(?,?,?,?) "
                     "ON CONFLICT(job_id) DO UPDATE SET cv=excluded.cv, "
                     "cover_letter=excluded.cover_letter, added=excluded.added",
                     (job_id, gen_cv, gen_cl, "\n".join(added)))
        conn.commit()
        try:
            prof = json.loads(kv_get(conn, "profile") or "{}")
        except ValueError:
            prof = {}
        return {
                "cv": gen_cv,
                "cover_letter": gen_cl,
                "have": list(have),
                "miss": list(miss),
                "added": added,
                "checks": verify_generation(gen_cv, base),
                "dropped": compute_dropped(base, gen_cv, prof)
                }



"""
show the generated CV and CL for the job_id
"""
@app.get("/api/jobs/{job_id}/generation")
def api_get_generation(job_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM generations WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "not generated yet")
        # 校验是纯比对，每次现算就行，不用存
        return {
                "cv": row["cv"],
                "cover_letter": row["cover_letter"],
                "added": [l for l in (row["added"] or "").splitlines() if l],
                "checks": verify_generation(row["cv"], fact_base(conn))
                }







@app.get("/api/jobs/{job_id}/jd")
def api_job_jd(job_id: int):
    """点开某条职位时才去抓它的 JD，抓到就存下来，下次直接命中。"""
    with db() as conn:
        row = conn.execute("SELECT id, jd, url FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "job not found")
        return {"jd": fetch_jd_if_not_exist(conn, row)}



@app.patch("/api/jobs/{job_id}")
def api_job_patch(job_id: int, body: dict):
    with db() as conn:
        for field in ("status", "jd", "notes"):
            if field in body:
                conn.execute(f"UPDATE jobs SET {field}=? WHERE id=?", (body[field], job_id))
        if body.get("status") == "applied":
            # 第一次标成已投时记下日期，之后改来改去都不覆盖
            conn.execute("UPDATE jobs SET applied_at=date('now','localtime') "
                         "WHERE id=? AND (applied_at IS NULL OR applied_at='')", (job_id,))
        conn.commit()
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def api_job_delete(job_id: int):
    """Delete a job and its associated generated documents from both jobs and generations tables."""
    with db() as conn:
        # Delete from generations table first (has foreign key relationship)
        conn.execute("DELETE FROM generations WHERE job_id=?", (job_id,))
        # Delete from jobs table
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.commit()
    return {"ok": True}





@app.post("/api/jobs")
def api_job_add(body: dict):
    if not body.get("title") or not body.get("company"):
        raise HTTPException(422, "title and company required")
    with db() as conn:
        jid = upsert_job(conn,
                         "manual",
                         body["title"],
                         body["company"],
                         body.get("location", ""),
                         body.get("url", ""),
                         ""
                         )
        if body.get("jd"):
            conn.execute("UPDATE jobs SET jd=? WHERE id=?", (body["jd"], jid))
            conn.commit()
    return {"id": jid}


"""
draw the pdf is not good
"""
@app.post("/api/render_pdf")
def api_render_pdf(body: dict = None):
    """预览区 HTML → 文本型 PDF（文字层完整，ATS 可解析）。只认 md() 会产出的标签，其余剥掉。"""
    from fpdf import FPDF
    html = ((body or {}).get("html") or "").strip()
    if not html:
        raise HTTPException(422, "没有可保存的内容")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        if tag.name not in PDF_TAGS:
            tag.unwrap()
    pdf = FPDF(format="A4")
    pdf.set_margins(18, 16)
    pdf.set_auto_page_break(True, margin=16)
    # ponytail: Arial 家族只覆盖拉丁系；中文 CV 会缺字形，到时换 Arial Unicode.ttf
    for style, f in (("", "Arial.ttf"), ("B", "Arial Bold.ttf"), ("I", "Arial Italic.ttf")):
        pdf.add_font("resume", style, os.path.join(PDF_FONT_DIR, f))
    pdf.add_page()
    pdf.write_html(str(soup), font_family="resume")
    return Response(bytes(pdf.output()), media_type="application/pdf")














