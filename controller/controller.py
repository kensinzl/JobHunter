from fastapi.responses import FileResponse
from main import ROOT, app
from service.ai_service import *
from service.file_service import *
from service.seek_linkin_service import *
from service.job_service import *
from service.cv_cl import *
from configure.configure import FILE_MAX_UPLOAD




@app.get("/")
def home():
    return FileResponse(os.path.join(ROOT, "index.html"))

@app.get("/assets/{name}")
def asset(name: str):
    path = os.path.join(ROOT, "assets", os.path.basename(name))  # basename 挡路径穿越
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    return FileResponse(path)

@app.get("/api/kv/{key}")
def api_kv_get(key: str):
    with db() as conn:
        return {"value": kv_get(conn, key)}

@app.put("/api/kv/{key}")
def api_kv_put(key: str, body: dict):
    with db() as conn:
        kv_set(conn, key, body.get("value", ""))
    return {"ok": True}



"""
Upload PDF CV and parse into txt
"""
@app.post("/api/extract")
async def api_extract(request: Request, name: str = ""):
    data = await request.body()
    if not data:
        raise HTTPException(400, "文件是空的")
    if len(data) > FILE_MAX_UPLOAD:
        raise HTTPException(413, f"文件超过 {FILE_MAX_UPLOAD // 1_000_000}MB")
    text = extract_upload(data, name)
    if not text:
        raise HTTPException(422, "没抽出任何文字。如果是扫描件或图片版 PDF，请手动粘贴内容。")
    return {"text": text, "chars": len(text)}


"""
Take the extracted text from the uploaded PDF
Use AI to nomalize into JSON
Save into KV table
"""
@app.post("/api/profile/from_cv")
def api_profile_from_cv(body: dict = None):
    """CV 原文 → GLM 抽取 → 存进 profile。body.text 不传就用知识库里已保存的 cv_master。"""
    text = ((body or {}).get("text") or "").strip()
    if not text:
        with db() as conn:
            text = kv_get(conn, "cv_master")
    if not text:
        raise HTTPException(422, "没有可解析的 CV 原文，先上传或粘贴 CV")
    p = normalize_profile(parse_json_response(glm_chat(build_profile_prompt(text))))
    with db() as conn:
        kv_set(conn, "profile", json.dumps(p, ensure_ascii=False))
        conn.commit()
    return p


"""
Accord to your job preferences, search jobs from Seek and LinkedIn, save into DB - Job Table
"""
@app.post("/api/search")
def api_search(confirm: bool = False):
    with db() as conn:
        #conn.execute("DELETE FROM jobs")
        # "" or "{}" -> or return the first truth str, so this case will be "{}" because "" mean not true
        prefs = json.loads(kv_get(conn, "prefs") or "{}")
        cleared = 0
        added, warnings = 0, []
        try:
            jobs = scrape_linkedin(prefs);

            # for j in jobs:
            #     upsert_job(conn,
            #                "Seek",
            #                j["title"],
            #                j["company"],
            #                j["location"],
            #                j["url"],
            #                j["listed_at"]
            #                )
            # added = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
            # print(f"Total Searching Jobs {len(jobs)} ...")
        except Exception as e:
            warnings.append(f"Seek 抓取失败: {e}")

        return {"added": added, "cleared": cleared, "warnings": warnings}

# """
# Accord to your job preferences, search jobs from Seek and LinkedIn, save into DB - Job Table
# """
# @app.post("/api/search")
# def api_search(confirm: bool = False):
#     with db() as conn:
#         # "" or "{}" -> or return the first truth str, so this case will be "{}" because "" mean not true
#         prefs = json.loads(kv_get(conn, "prefs") or "{}")
#         key = search_key(prefs)
#         # changed = key != kv_get(conn, "last_search_key")
#         placeholders = ",".join("?" * len(KEEP_ON_CLEAR))
#         # stale = conn.execute(f"SELECT COUNT(*) c FROM jobs WHERE status NOT IN ({placeholders})",
#         #                      KEEP_ON_CLEAR).fetchone()["c"]
#         # if changed and stale and not confirm:
#         #     kept = conn.execute(f"SELECT COUNT(*) c FROM jobs WHERE status IN ({placeholders})",
#         #                         KEEP_ON_CLEAR).fetchone()["c"]
#         #     raise HTTPException(409, f"搜索条件变了。继续会清掉 {stale} 条未处理的职位，"
#         #                              f"保留 {kept} 条跟进中的（感兴趣 / 已投 / 面试中 / 已offer / 已挂）。")
#         cleared = 0
#         # if changed:
#         #     conn.execute(f"""DELETE FROM generations WHERE job_id IN
#         #                      (SELECT id FROM jobs WHERE status NOT IN ({placeholders}))""", KEEP_ON_CLEAR)
#         #     cleared = conn.execute(f"DELETE FROM jobs WHERE status NOT IN ({placeholders})",
#         #                            KEEP_ON_CLEAR).rowcount
#         #     conn.commit()
#         # kv_set(conn, "last_search_key", key)
#         added, warnings = 0, []
#         for name, fn in (("Seek", scrape_seek_all_jobs), ("LinkedIn", scrape_linkedin)):
#             try:
#                 for j in fn(prefs):
#                     if excluded(j["title"], prefs.get("exclude", "")) \
#                             or level_excluded(j["title"], prefs.get("levels", "")):
#                         continue
#                     before = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
#                     upsert_job(conn, name.lower(), j["title"], j["company"],
#                                j["location"], j["url"], j["listed_at"])
#                     after = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
#                     added += after - before
#             except Exception as e:
#                 warnings.append(f"{name} 抓取失败: {e}")
#         return {"added": added, "cleared": cleared, "warnings": warnings}


















