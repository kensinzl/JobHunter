from main import app
from service.ai_service import *
from repository.db_repository import db


"""
Using AI to score the generate CV with the following
- ATS score
- ATS feel the Gap keywords between JD and CV
- ATS one sentence summary
- CV Basic Check Info
"""
@app.post("/api/score")
def api_score(body: dict):
    with db() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (body.get("job_id"),)).fetchone()
        if not job:
            raise HTTPException(404, "job not found")
        if not job["jd"]:
            raise HTTPException(422, "There is no job description (JD) available for this position yet. ")
        cv = (body.get("cv_text") or "").strip()
        if not cv:
            row = conn.execute("SELECT cv FROM generations WHERE job_id=?", (job["id"],)).fetchone()
            if not row:
                raise HTTPException(422, "There is no generated CV available for this position yet. Please generate one first or manually paste the CV text.")
            cv = row["cv"]
    out = glm_chat(build_score_prompt(job["jd"], cv))
    try:
        result = parse_json_response(out)
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(500, f"评分结果解析失败，GLM 返回: {out[:300]}")
    result["local_checks"] = local_checks(cv)
    return result