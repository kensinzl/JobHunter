# jobSeeker 设计文档

日期：2026-08-03 · 方案：本地服务器 + 浏览器界面（方案 A，已确认）

## 目标

一个跑在本机的求职系统：按偏好抓取 Seek 和 LinkedIn 职位，基于用户的 CV/cover letter 知识库，为选中职位生成能通过 AI/ATS 筛选的定制 CV 和 cover letter。

## 架构

- `server.py`：FastAPI 单文件后端。职责：抓取、SQLite 存取、调 GLM API 生成。
- `index.html`：单页前端（原生 JS，无框架），4 个标签页。
- `../../../JobHunter.db`：SQLite（stdlib sqlite3）。
- `.env`：`OPEN_AI_KEY`（不进 git）。
- 依赖：fastapi、uvicorn、httpx、beautifulsoup4、python-dotenv。不用 Playwright（headless 会被反爬拦截；见"升级路径"）。

## 功能

### 1. 求职偏好（标签页 1）
字段：关键词、地点、薪资下限、工作类型（全职/合同/兼职）、排除关键词（逗号分隔）。存 SQLite 单行。

### 2. 知识库（标签页 2）
三个大文本框，各存一条记录：
- CV 原文（完整经历，master resume）
- cover letter 范文
- cover letter 格式偏好（自由文本：语气、结构、称呼等）——满足需求 3

### 3. 职位搜索（标签页 3）
点搜索 → 后端并发抓两站 → 按 (公司+职位名) 去重 → 存表 → 前端列表展示（职位、公司、地点、链接、来源、发布时间、状态）。状态可标记：新 / 感兴趣 / 已投 / 忽略。

抓取实现：
- **Seek**：前端公开 JSON 搜索接口（chalice-search API，无需登录），带正常浏览器 User-Agent。
- **LinkedIn**：guest 职位接口 `linkedin.com/jobs-guest/jobs/api/seeJobPostings/search`（无需登录，HTML 片段，bs4 解析）。有速率限制，失败时降级：只显示 Seek 结果 + 界面提示。
- **手动兜底**：支持粘贴任意职位链接/JD 文本直接入库。
- **升级路径**（本期不做）：若接口失效，接本机 Chrome 的有头 Playwright（headed + 真实用户 profile 规避反爬）。

### 4. 生成（标签页 4）
选中职位 → 后端抓 JD 全文（Seek/LinkedIn 详情页；失败则用户粘贴）→ 组 prompt 调 GLM（OpenAI 兼容接口，`open.bigmodel.cn`，模型 glm-4.6 可配）→ 返回定制 CV + cover letter → 前端预览（ATS 友好排版：单栏、无表格、无图标、标准节标题）→ 可编辑 → 浏览器打印为 PDF。生成结果存库，避免重复生成。

## ATS/AI 筛选策略（核心）

实现前先联网调研 2025-2026 最新 ATS 与 LLM 简历筛选机制（Workday/Greenhouse/Lever/SEEK 自带 AI、招聘方用 GPT 类模型打分的常见 rubric），结论产出两份东西：
1. 硬编码进生成 prompt 的规则（关键词自然嵌入、职位名对齐、量化成果、标准节标题、无表格图形、文件命名等）。
2. `docs/ats-research.md`：调研结论说明文档，给用户看。

生成 prompt 必须包含：JD 全文、从 JD 提取的关键词清单、用户 master CV、cover letter 范文与格式偏好、ATS 规则。红线：不得虚构经历，只做措辞对齐与重点重排。

## 错误处理

- LinkedIn 限流/被封：降级 Seek-only，界面黄条提示。
- GLM 失败：显示状态码与原始错误。
- 抓取详情页失败：提示用户手动粘贴 JD。

## 测试

`test_smoke.py`：去重逻辑、JD 关键词提取、DB 读写各一个断言级测试。抓取器提供 `python server.py --test-scrape` 手动冒烟（外部接口不进自动化测试）。

## 不做（YAGNI）

登录态抓取、自动投递、多用户、DOCX 导出（打印 PDF 够用）、定时任务。
