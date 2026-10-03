# jobSeeker

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

本地求职系统：按偏好抓取 Seek + LinkedIn 职位，基于你的 CV/cover letter 知识库，用 GLM 生成能通过 AI/ATS 筛选的定制 CV 和 cover letter。

## 安装

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env   # 填入你的LLM API_KEY（open.bigmodel.cn 获取）
```

## 运行

```bash
venv/bin/python main.py
```

浏览器打开 http://127.0.0.1:8000

## 使用流程

1. **求职偏好**：填关键词、地点（如 `Sydney NSW`）、排除词，保存。
2. **知识库**：粘贴你的完整 CV 原文（生成时的唯一事实来源）、cover letter 范文、格式偏好（语气/结构/称呼），保存。
3. **职位列表**：点"搜索 Seek + LinkedIn"，结果自动去重入库；可标记状态（感兴趣/已投/忽略）；抓不到的职位可手动添加并粘贴 JD。
4. **生成**：选职位 → 生成 → 预览（可直接点击编辑）→ "打印 / 存 PDF"。

ATS/AI 筛选优化策略见 [docs/ats-research.md](docs/ats-research.md)，规则已内置于生成 prompt。

## 故障排查

- **LinkedIn 抓取失败（404/429）**：被限流，稍后再试或手动添加职位；Seek 结果不受影响。
- **Seek 抓取失败**：接口版本可能变动，跑 `venv/bin/python server.py --test-scrape` 验证，改 `server.py` 里 `scrape_seek` 的 URL 版本号。
- **生成报 422**：说明缺 JD 或知识库没存 CV，按提示补齐。
- **生成报 GLM 错误**：检查 `.env` 的 key 与余额；模型可用 `GLM_MODEL` 环境变量换。
