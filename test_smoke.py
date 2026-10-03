# import os, tempfile
# import pytest
#
# os.environ["JOBSEEKER_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
# import main
#
#
# def test_kv_roundtrip():
#     with main.db() as conn:
#         main.kv_set(conn, "cv_master", "my cv text")
#         assert main.kv_get(conn, "cv_master") == "my cv text"
#         main.kv_set(conn, "cv_master", "v2")
#         assert main.kv_get(conn, "cv_master") == "v2"
#         assert main.kv_get(conn, "missing") == ""
#
#
# def test_upsert_job_dedup():
#     with main.db() as conn:
#         a = main.upsert_job(conn, "seek", "Data Analyst", "Acme", "Sydney", "http://x/1", "2026-08-01")
#         b = main.upsert_job(conn, "linkedin", "Data Analyst", "Acme", "Sydney NSW", "http://y/2", "2026-08-02")
#         assert a == b  # same company+title = same job
#         c = main.upsert_job(conn, "seek", "Data Engineer", "Acme", "Sydney", "http://x/3", "2026-08-01")
#         assert c != a
#
#
# LINKEDIN_FIXTURE = """
# <ul><li><div class="base-card">
# <a class="base-card__full-link" href="https://au.linkedin.com/jobs/view/data-analyst-at-acme-4012345678?refId=x">link</a>
# <h3 class="base-search-card__title"> Data Analyst </h3>
# <h4 class="base-search-card__subtitle"><a>Acme Corp</a></h4>
# <span class="job-search-card__location">Sydney, NSW</span>
# <time class="job-search-card__listdate" datetime="2026-07-30"></time>
# </div></li></ul>
# """
#
#
# def test_parse_linkedin_cards():
#     jobs = server.parse_linkedin_cards(LINKEDIN_FIXTURE)
#     assert jobs == [{"title": "Data Analyst", "company": "Acme Corp",
#                      "location": "Sydney, NSW",
#                      "url": "https://au.linkedin.com/jobs/view/data-analyst-at-acme-4012345678",
#                      "listed_at": "2026-07-30"}]
#
#
# def test_exclude_filter():
#     assert main.excluded("Senior PHP Developer", "php, wordpress") is True
#     assert server.excluded("Data Analyst", "php, wordpress") is False
#     assert main.excluded("Data Analyst", "") is False
#
#
# def test_level_excluded():
#     assert server.level_excluded("Senior Data Analyst", "") is False          # 不限
#     assert server.level_excluded("Senior Data Analyst", "junior") is True     # 其他等级
#     assert server.level_excluded("Senior Data Analyst", "mid_senior") is False
#     assert main.level_excluded("Data Analyst", "junior") is False           # 无标记保留
#     assert main.level_excluded("Graduate / Junior Engineer", "junior") is False  # 命中已选即保留
#     assert main.level_excluded("Sr. Software Engineer", "junior") is True   # sr. 也算 senior
#     assert main.level_excluded("Leadership Coach", "junior") is False       # lead 不误伤 leadership
#     assert server.level_excluded("Staff Nurse", "junior") is False            # staff 刻意不收
#
#
# def test_levels_fe():
#     assert main.levels_fe("") == ""
#     assert server.levels_fe("junior,mid_senior") == "2,3,4"
#     assert main.levels_fe("intern,bogus") == "1"
#
#
# def test_render_profile():
#     p = {"basic": {"name": "Jane Chen", "email": "j@x.com", "location": "Sydney NSW"},
#          "summary": "Analyst with 4 years experience",
#          "skills": ["Python", "SQL"],
#          "experience": [{"title": "Data Analyst", "company": "Big4", "location": "Sydney",
#                          "start": "Jul 2023", "end": "Present", "bullets": ["Built dashboards"]}],
#          "education": [{"degree": "BSc", "school": "UNSW", "year": "2020"}],
#          "other": "AWS Certified"}
#     out = server.render_profile(p)
#     assert out.startswith("# Jane Chen")
#     assert "Sydney NSW | j@x.com" in out
#     assert "## Skills\nPython, SQL" in out
#     assert "### Data Analyst — Big4, Sydney (Jul 2023 - Present)" in out
#     assert "- Built dashboards" in out
#     assert "- BSc — UNSW (2020)" in out
#     assert "AWS Certified" in out
#     assert main.render_profile({}) == ""
#
#
# def test_profile_fallback():
#     with main.db() as conn:
#         main.kv_set(conn, "cv_master", "raw cv text")
#         main.kv_set(conn, "profile", "")
#         assert main.profile_or_master(conn) == "raw cv text"      # profile 空 → 回落
#         main.kv_set(conn, "profile", '{"basic": {"name": "Jane"}}')
#         assert main.profile_or_master(conn) == "# Jane"           # profile 有货 → 用渲染文本
#         server.kv_set(conn, "profile", "")                          # 还原，别污染后面的测试
#
#
# def test_fix_broken_ligatures():
#     fix = server.fix_broken_ligatures
#     assert fix("SoKware Engineer in producQon") == "Software Engineer in production"
#     assert fix("integraQng operaQonal systems") == "integrating operational systems"
#     assert fix("heps://github.com and hep://old.site") == "https://github.com and http://old.site"
#     # 合法的 Q/K 不能被误修
#     assert fix("jQuery and Kubernetes at McKinsey") == "jQuery and Kubernetes at McKinsey"
#     assert fix("Qantas MacKenzie") == "Qantas MacKenzie"
#
#
# def test_build_profile_prompt():
#     p = main.build_profile_prompt("my raw resume")
#     assert "my raw resume" in p
#     assert '"experience"' in p and '"basic"' in p
#     assert "不许推断" in p
#
#
# def test_build_draft_prompt():
#     p = main.build_draft_prompt("We need Docker and Kubernetes", "My CV: Python dev at Acme",
#                                 ["Docker", "Kubernetes"])
#     assert "Docker" in p and "Kubernetes" in p
#     assert "My CV: Python dev at Acme" in p
#     assert "不许发明新的雇主" in p          # 红线必须在 prompt 里
#     assert '"drafts"' in p                  # 输出结构约定
#
#
# def test_merge_extra():
#     assert main.merge_extra("", "a\nb") == "a\nb"
#     assert main.merge_extra("a", "a") == "a"                # 重复行不再追加
#     assert server.merge_extra("a", "a\nb") == "a\nb"
#     assert main.merge_extra("a\nb", "  a  ") == "a\nb"      # 两侧空白不影响判重
#
#
# def test_normalize_salary():
#     assert server.normalize_salary("100000") == "100000"
#     assert server.normalize_salary("100k") == "100000"
#     assert server.normalize_salary("100,000") == "100000"
#     assert main.normalize_salary("$1.5k") == "1500"
#     assert server.normalize_salary("abc") == ""
#     assert main.normalize_salary("") == ""
#
#
# def test_normalize_profile():
#     p = server.normalize_profile({"basic": {"name": "J", "email": None}, "summary": None,
#                                   "skills": ["a", 1, None], "education": "bogus",
#                                   "experience": [{"title": "T", "bullets": ["x", 2, None]}, "junk"]})
#     assert p["basic"]["name"] == "J" and p["basic"]["email"] == ""
#     assert p["skills"] == ["a", "1"]
#     assert p["experience"][0]["title"] == "T" and p["experience"][0]["bullets"] == ["x", "2"]
#     assert p["education"] == [] and p["summary"] == ""
#     assert main.normalize_profile("junk")["skills"] == []
#
#
# def test_compute_dropped():
#     base = "I use Python and Docker and Kubernetes daily"
#     gen = "## Skills\nPython\n\n### Engineer — Acme, Sydney (Jan 2020 - Present)"
#     prof = {"experience": [{"title": "Engineer", "company": "Acme"},
#                            {"title": "Analyst", "company": "OldCorp"}]}
#     d = main.compute_dropped(base, gen, prof)
#     assert "Docker" in d["skills"] and "Kubernetes" in d["skills"]
#     assert "Python" not in d["skills"]
#     assert d["experiences"] == ["Analyst — OldCorp"]
#     assert main.compute_dropped(base, gen, {}) ["experiences"] == []
#
#
# def test_render_pdf_endpoint():
#     from fastapi.testclient import TestClient
#     client = TestClient(main.app)
#     html = "<h1>Jane</h1><div><p>Sydney | j@x.com</p></div><ul><li>Built <b>12</b> dashboards</li></ul>"
#     r = client.post("/api/render_pdf", json={"html": html})
#     assert r.status_code == 200
#     assert r.content.startswith(b"%PDF")
#     assert client.post("/api/render_pdf", json={"html": ""}).status_code == 422
#
#
# def test_match_endpoint():
#     from fastapi.testclient import TestClient
#     client = TestClient(main.app)
#     with main.db() as conn:
#         jid = main.upsert_job(conn, "manual", "ML Engineer", "MatchCo", "", "", "")
#         conn.execute("UPDATE jobs SET jd=? WHERE id=?",
#                      ("Requires Python and Docker experience", jid))
#         main.kv_set(conn, "cv_master", "I write Python daily")
#         conn.commit()
#     r = client.get(f"/api/jobs/{jid}/match")
#     assert r.status_code == 200
#     assert "Python" in r.json()["have"] and "Docker" in r.json()["miss"]
#     assert client.get("/api/jobs/999999/match").status_code == 404
#
#
# def test_build_prompt_contains_everything():
#     p = server.build_prompt("JD text here", "Analyst", "Acme", "my cv", "my sample", "short and punchy")
#     for chunk in ("JD text here", "Analyst", "Acme", "my cv", "my sample", "short and punchy",
#                   "===COVER LETTER===", "===ADDED SKILLS==="):
#         assert chunk in p
#     assert "不许改、不许编" in p          # 雇主/日期/学历的红线还在
#     assert "缺口" not in p                # 没算出缺口时不该凭空多一段
#
#
# def test_score_prompt_and_json_parse():
#     p = server.build_score_prompt("the jd", "the cv")
#     for chunk in ("Workday", "iCIMS", "Greenhouse", "SEEK", "PageUp", "the jd", "the cv"):
#         assert chunk in p
#     assert server.parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
#     assert main.parse_json_response('前置废话 {"a": [1, 2]} 后置废话') == {"a": [1, 2]}
#
#
# def test_local_checks():
#     good = "Name\nCity | email | phone\n\nExperience\n- Grew revenue 30%\n- Led team of 5\nEducation\nSkills"
#     assert all(c["pass"] for c in server.local_checks(good))  # header pipes are fine
#     bad = "line\n" * 6 + "col1 | col2 | col3\n"
#     results = {c["name"]: c["pass"] for c in main.local_checks(bad)}
#     assert results["无表格结构"] is False
#     assert results["标准节标题"] is False
#
#
# def test_split_output():
#     cv, cl, added = server.split_output(
#         "CV BODY\n===COVER LETTER===\nCL BODY\n===ADDED SKILLS===\n- CrewAI\n* GitHub Copilot")
#     assert cv == "CV BODY" and cl == "CL BODY"
#     assert added == ["CrewAI", "GitHub Copilot"]      # 列表符号要剥掉，不然显示成 "- CrewAI"
#     assert main.split_output("CV\n===COVER LETTER===\nCL\n===ADDED SKILLS===\n无")[2] == []
#     assert server.split_output("CV\n===COVER LETTER===\nCL")[2] == []   # 旧格式不能炸
#     cv2, cl2, _ = server.split_output("no delimiter at all")
#     assert cv2 == "no delimiter at all" and cl2 == ""
#
#
# def test_verify_generation():
#     base = ("Zihan Wang | linkedin.com/in/zihan | github.com/zihan\n"
#             "Full working rights, no sponsor required.\n"
#             "Huawei  April.2025- April 2026\nVenturelyVc  July.2023-July.2024")
#     good = ("# Zihan Wang\nMelbourne | a@b.c | linkedin.com/in/zihan\nFull working rights.\n"
#             "### AI Engineer — Huawei, Nanjing (Apr 2025 - Apr 2026)\n"
#             "### Developer — Venturelytic, Rotterdam (Jul 2023 - Jul 2024)")
#     assert all(c["pass"] for c in main.verify_generation(good, base))  # 乱码还原成 Venturelytic 不算改雇主
#
#     moved = good.replace("Apr 2025 - Apr 2026", "Apr 2024 - Apr 2025")
#     r = {c["name"]: c for c in main.verify_generation(moved, base)}
#     assert r["日期未被改动"]["pass"] is False and "Apr 2024" in r["日期未被改动"]["detail"]
#     # 淘汰题信息和个人主页链接被丢掉必须报出来
#     stripped = "\n".join(l for l in good.splitlines() if "rights" not in l and "linkedin" not in l)
#     r2 = {c["name"]: c["pass"] for c in main.verify_generation(stripped, base)}
#     assert r2["工作权利信息保留"] is False and r2["LinkedIn / GitHub 保留"] is False
#     assert main.verify_generation(good.replace("Huawei", "Google"), base)[1]["pass"] is False
#
#
# def test_extract_upload():
#     import io, zipfile
#     assert server.extract_upload("Hello\n\n\n\nWorld".encode(), "cv.txt") == "Hello\n\nWorld"
#     # 连字必须还原，否则 workflow 存进知识库后 ATS 永远匹配不上
#     assert server.extract_upload("workﬂow oﬀer eﬃcient".encode(), "cv.md") == "workflow offer efficient"
#
#     buf = io.BytesIO()
#     with zipfile.ZipFile(buf, "w") as z:
#         z.writestr("word/document.xml",
#                    "<w:document><w:body><w:p><w:r><w:t>Jane &amp; Co</w:t></w:r></w:p>"
#                    "<w:p><w:r><w:t>Data Analyst</w:t></w:r></w:p></w:body></w:document>")
#     assert server.extract_upload(buf.getvalue(), "cv.docx") == "Jane & Co\nData Analyst"
#
#     with pytest.raises(Exception):
#         server.extract_upload(b"whatever", "cv.pages")
#
#
# def test_clean_extracted():
#     # 拆开的重音要合回去，但 don´t 这种撇号用法不能误伤
#     assert main.clean_extracted("Tel´efono EDUCACI ´ON Espa˜nol An´alisis") == "Teléfono EDUCACIÓN Español Análisis"
#     assert main.clean_extracted("don´t") == "don´t"
#     # 同一行被 PDF 重复绘制 4 次以上，只留第一次
#     assert server.clean_extracted("A\nlink\nlink\nlink\nlink\nB") == "A\nlink\nB"
#     # 合理的重复（同一雇主出现两三次）必须保住
#     assert main.clean_extracted("Big4\nx\nBig4\ny\nBig4") == "Big4\nx\nBig4\ny\nBig4"
#     # 图标字形名只清联系方式块；Github/link 这类同时是真词的一律不碰
#     out = main.clean_extracted("Envelope a@b.com | Map-marker-alt Sydney | Github me\n\nBuilt a Github Action")
#     assert out.startswith("a@b.com | Sydney | Github me") and "Github Action" in out
#
#
# def test_jd_text():
#     from bs4 import BeautifulSoup
#     html = ("<div><p>JB Hi-Fi is the perfect place to <b>power your career</b>, and we're excited.</p>"
#             "<ul><li>Fast paced <em>environment</em></li><li>Great <a href='#'>discounts</a></li></ul>"
#             "<p>Line one<br>Line two</p></div>")
#     out = server.jd_text(BeautifulSoup(html, "html.parser"))
#     lines = out.split("\n")
#     # 内联标签不能把一句话切开
#     assert "JB Hi-Fi is the perfect place to power your career, and we're excited." in lines
#     # li 保留项目符号，且整条在一行
#     assert "• Fast paced environment" in lines and "• Great discounts" in lines
#     # <br> 才换行
#     assert "Line one" in lines and "Line two" in lines
#
#
# def test_skill_match():
#     jd = ("Hands-on experience with Azure Machine Learning, Large Language Models (LLMs) "
#           "and Azure Kubernetes Service (AKS). Familiarity with Redis is desirable. "
#           "Strong SQL and Power BI skills, excellent stakeholder communication.")
#     cv = "Data Analyst. Wrote SQL pipelines on Azure, built PowerBI dashboards for senior stakeholders."
#     have, miss = main.skill_match(jd, cv)
#     assert set(have) == {"Azure", "SQL", "Power BI", "Stakeholder Management"}
#     for gap in ("Azure Machine Learning", "LLM", "AKS", "Redis"):
#         assert gap in miss
#     # 短缩写必须大小写敏感，否则 "sap"/"r" 会满篇误命中；长词照样不区分大小写
#     assert "SAS" not in main.skill_match("we use sas-like tooling", cv)[0] + server.skill_match("we use sas-like tooling", cv)[1]
#     assert "Excel" not in main.skill_match("an excellent candidate", cv)[1]
#     assert "Docker" in main.skill_match("DOCKER required", cv)[1]
#
#
# def test_build_prompt_extra_facts():
#     p = main.build_prompt("jd", "T", "C", "my cv", "s", "f", extra="我会 Docker")
#     assert "我会 Docker" in p and "原履历里没写到" in p
#     assert "原履历里没写到" not in server.build_prompt("jd", "T", "C", "my cv", "s", "f")
#
#
# def test_build_prompt_gap_is_forbidden():
#     p = main.build_prompt("jd", "T", "C", "cv", "s", "f", miss=("CrewAI", "Redis"))
#     assert "CrewAI、Redis" in p and "一项都不许补" in p
#     assert "技能缺口" not in main.build_prompt("jd", "T", "C", "cv", "s", "f", miss=())
#
#
# def test_search_key_only_tracks_search_fields():
#     base = {"keywords": "data analyst", "location": "Sydney", "exclude": "php"}
#     assert main.search_key(base) == server.search_key(dict(base, some_ui_setting="x"))
#     assert server.search_key(base) != main.search_key(dict(base, keywords="data engineer"))
#     assert main.search_key(base) != server.search_key(dict(base, exclude=""))
#     assert server.search_key(base) != server.search_key(dict(base, levels="junior"))
