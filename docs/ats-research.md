# ATS / AI 简历筛选机制调研（2026-08）

本系统生成 CV 的规则依据。结论已硬编码进 `server.py` 的 `ATS_RULES`。

## 筛选管线实际是怎么工作的

1. **解析（Parsing）**：ATS 把你的 PDF/DOCX 解析成纯文本和结构化字段。表格、多栏、图标、页眉页脚、扫描图片都会导致解析错乱——解析失败等于没投。
2. **淘汰题（Knockout questions）**：工作签证、最低年限、地点等申请表问题在简历被读之前就先淘汰一批人。这些要如实填，但要注意别因表述随意被误杀。
3. **关键词/语义打分**：2020-2023 年主流是精确关键词匹配；2024-2026 年 Workday、iCIMS、Greenhouse 等已升级为语义匹配（"project management" 也能匹配 "program management"），但置信度不同——**用 JD 原词仍然得分最高**。
4. **LLM 层（新，关键）**：越来越多雇主（2025 年约 83% 的公司在筛选中用 AI）在关键词层之上叠加 LLM：它通读解析后的文本，给招聘官写一段"匹配度总结"和评分。这意味着简历不仅要命中关键词，还要**让一个 AI 读者能快速找到"JD 每条核心要求 → 你的对应证据"**。
5. **人**：92% 的美国招聘官确认 ATS 并不自动拒人——真正的门槛是：分数太低，你不会出现在招聘官筛选后的视图里。优化过关键词的简历到达招聘官桌面的概率约为未优化的 3 倍。

## 会被惩罚的行为

- **关键词堆砌**：Workday 2026 算法明确标记密度异常的简历（两页出现 15 次 "project management" 会被标记为操纵）。关键词要自然出现在成果句里。
- **白字隐藏关键词**：解析后现原形，直接进黑名单。
- **虚构经历**：LLM 层会交叉比对时间线和职责合理性，且面试一问就穿帮。

## 落地策略（生成规则的依据）

1. 单栏、倒序、标准节标题（Professional Summary / Skills / Experience / Education / Certifications），无表格无图形无页眉页脚，导出为文字可选中的原生 PDF。
2. 从 JD 提取硬技能、工具、资质、职位名，属实的用 **JD 原始拼写**自然写入。
3. 缩写与全称成对出现一次："Search Engine Optimisation (SEO)"。
4. 顶部 Summary 出现与目标职位一致的职位名（title alignment 是打分大项）。
5. 每条经历 = 动词开头 + 量化结果；技能不裸列，要有上下文和成果（LLM 层看的是证据，不是清单）。
6. JD 的每条核心要求，简历里都应有一条明确对应的证据句——这是给 LLM 打分层"喂答案"。
7. 日期格式统一（MMM YYYY），时间线无断档解释不清的空白。
8. 保留人类技能证据（判断力、stakeholder 管理、跨团队协作）——2026 年的 AI 筛选 rubric 普遍包含这类维度。

## 各平台打分机制（2026-08 二次调研，评分模拟器的依据）

### Workday（HiredScore，2024 年被 Workday 收购后的官方 AI 筛选）
- 给候选人打 **A–D 等级**，A 为最匹配；每个职位单独对照自己的 JD 打分。
- 简历被解析重建为结构化档案：职位、教育、技能分别入字段——解析质量直接决定下限。
- 能**从上下文推断技能**（没明写也可能被识别），语义匹配为主。
- 惩罚关键词密度异常（堆砌被标记为操纵）。

### iCIMS（Copilot "Role Fit" 评分）
- **关键词频次加权**：同一技能出现在 Summary + 经历句 + Skills 区，比只出现一次排名显著更高。
- **对精确用词最敏感的平台**：JD 写 "JavaScript" 而简历写 "JS"，匹配分降低。
- ML 层考虑年限、职业轨迹（进步性）、前职相关度。
- 简历被评估两次：解析器建档 → Copilot 对照 JD 打分并与其他候选人排名。

### Greenhouse
- **没有自动简历评分算法**——人工优先。唯一的自动淘汰是 knockout 问题（工作权利等）。
- 招聘官按结构化 **scorecard**（从 JD 定义的必备属性清单）逐项找证据打分。
- 对策：简历要让每条必备属性都有一句显式证据；模拟评分 = scorecard 属性覆盖率。

### SEEK（澳洲）
- SEEK 自有 candidate matching 算法：职位名相似度、技能重叠、地点匹配、经历新旧度，对 profile 和上传 CV 都打分。
- **大多数 SEEK 申请最终转发进雇主自己的 ATS**——澳洲主流是 PageUp（政府/大学/大企业）、JobAdder（招聘中介）、Workday（跨国企业）。

### PageUp（澳洲政府、大学、大企业主流）
- 解析 + 技能/职位名/年限匹配排名，无公开的激进 AI 评分。
- 澳洲语境特点：政府和大学职位常要求显式回应 selection criteria；用澳式英语拼写（organisation, specialise）与 JD 保持一致。

## 措辞层的两条硬规定（2026-08 加入 `ATS_RULES` / 输出格式）

**Summary 里禁止 "aspiring" 类限定词。** 实测生成结果写过 `Data Analyst and aspiring AI/ML Architect`。两个问题：一是 iCIMS/Workday 的职位名相似度按简历里第一个职位名 token 算，"aspiring" 前面的 `Data Analyst` 才是被匹配的那个，目标职位名等于白写；二是 LLM 打分层把"aspiring X"读成"此人不是 X"，规则 3 的 title alignment 直接反向。够不上目标职位名时写最接近的**真实**职位名，不加限定词——这不是包装，是让匹配层拿到正确的输入。

**Cover letter 不带任何 Markdown 标记。** 输出格式里"量化数字用 `**加粗**`"只针对 CV，早期版本泄漏到求职信，生成出 `processing over **2M+** rows daily`。求职信是散文，加粗数字既不是求职信的写法，打印出来也一眼是模板生成的。

## 技能缺口的处理方式（`SKILLS` / `skill_match`）

职位列表里每条岗位显示"技能 N/M"：M 是词表在 JD 里点到的技能数，N 是同一批技能在知识库（`cv_master` + `cv_extra`）里能找到证据的数量。**用词表匹配而不是调模型**——列表几百条，每条一次 LLM 调用不可接受；词表漏了就往 `SKILLS` 里加一行别名。

短的全大写别名（SQL / AWS / ML / AKS / R）大小写敏感，否则 `sap`、`r` 会满篇误命中；三字符以上的别名允许尾随复数 `s`（JD 里 stakeholder / dashboard / microservice 基本都是复数形式）。

缺口列表有两个去处：给用户（勾选"我实际会、只是履历漏写"的项，写进 `cv_extra`），也**直接喂进 prompt**。第二条是关键——模型原本得自己猜哪些技能没证据，猜错就是编；现在缺口是服务端算好的确定答案，模型只需要按名单办事。

## 事实完整性：为什么改成"申报制"而不是"禁止"（2026-08-07）

一次真实生成（AI Engineer @ Publicis Sapient）同时出现三个问题，追下去发现是同一个缺陷的三个方向：

| 问题 | 破坏方式 |
|---|---|
| 华为的起止日期整体前移一年（填掉时间线空档） | **改**了不可变事实 |
| Skills 区多出 CrewAI / GitHub Copilot / Unit·Integration·E2E Testing | **加**了不可变事实 |
| "full working rights, no sponsor required" 整行消失 | **删**了不可变事实 |

根因：prompt 把履历当成一坨可以整体重写的素材交给一次生成，而履历里其实混着两类内容——**不可变事实**（姓名、雇主、日期、学历、地点、工作权利、数字指标）只能选和删，**可变表述**（措辞、组织、排序）才能重写。两者共用一次调用、一个 temperature，只靠一条否定规则兜底，而否定规则兜不住生成任务：前 11 条都在说"改写、对齐、重排"，第 12 条说"别编"，梯度是反的。

三处具体的规则缺陷：

- **日期是我们自己发的许可证**。旧规则 8 写"日期格式统一 MMM YYYY"，主动把日期放进了可改写那一桶。一旦模型认为日期归它管，改格式和改年份就是同一类操作。
- **Skills 是全篇摩擦最低的说谎面**。旧规则 9（"罗列 JD 匹配的技能关键词"）不带任何真实性限定，而在 Experience 里编一项技能要配一整句带场景的谎，在逗号列表里编只要一个 token。编造行为必然往摩擦最小处聚集。
- **调研结论只落地了一半**。本文第 2 节的 knockout questions（签证/年限/地点在打分之前先淘汰）从来没写进 `ATS_RULES`，13 条全在讲怎么拿高分，没有一条讲怎么别在打分前出局。模型按给定规则判断，工作权利不是技能不是成果，删得完全合逻辑。

改法（用户决定）：

1. **红线收窄但加硬**（规则 12）：雇主 / 职位名 / 起止日期 / 学校学位 / 所有数字指标只能原样复制，年限不够、时间线有洞一律照实。乱码还原（`producQon` → `production`）允许，改变所指的事实不允许。
2. **日期移出可改写桶**（规则 8）：只允许统一写法，不允许改年月，不允许挪经历填空档。
3. **技能改成申报制**（规则 13）：允许补 JD 要求而履历没证据的技能，但每一项必须在 `===ADDED SKILLS===` 区块逐条列出，前端把清单直接展示给用户，并提供一键「不虚构技能，重新生成」（`no_invent=True`，prompt 里换成禁止句）。判断留不留是用户对自己简历的决定，工具的职责是不让它悄悄发生。
4. **补 knockout 规则**（规则 14）：签证/工作权利/PR/到岗地点时间的原句，以及 LinkedIn / GitHub 链接，必须原样保留在联系方式行下方。

### 申报制改为勾选制（2026-08-09）

申报制的前提是用户没有事前把关的入口——模型先补、用户事后删。生成前匹配预检上线后（勾选缺失技能 → AI 按真实履历起草 → 逐条 ✓/✗ 审批），用户的意愿在生成之前就是明确的：**勾了的进补充材料，没勾的就是不要**。于是规则 13 反转为禁止句：无证据技能一律不许写，`no_invent` 参数删除（禁止成为唯一行为）。`===ADDED SKILLS===` 区块保留，但语义从"申报补了什么"变成**违规绊线**——正常输出「无」，模型越界时前端把泄漏清单标红展示并提供重新生成。实测动机（触发本次修改）：模型一次自行补了 14 项无证据技能，事后逐项删的负担远大于事前勾选。

同日补充——**精简告知制**（规则 9 扩展）：与 JD 无关的技能和经历允许模型精简甚至整段省略（聚焦比大而全得分高），但省略不靠模型申报（ADDED SKILLS 的教训：LLM 自报不可靠），而是生成后由 `compute_dropped` 确定性比对——SKILLS 词表跑一遍"履历有证据、CV 没出现"的技能，公司名前缀查缺失的整段经历——前端以中性信息展示，与红色的违规区分开。延续既定分工：**代码验证省略与不变量，模型只负责生成**。

## 生成后校验（`verify_generation`）

`local_checks` 查格式，`verify_generation` 查"不该变的变没变"，两者都是**纯字符串比对，不调模型**——确定性检查比在 prompt 里求模型别犯错可靠得多，而且免费。四项：

| 检查 | 实现 |
|---|---|
| 日期未被改动 | 生成 CV 里的 (月, 年) 集合减去履历里的，非空即失败 |
| 雇主未被改动 | `### 职位 — 公司` 里的公司名，去掉非字母后取前 5 个字符在履历里找 |
| 工作权利信息保留 | 履历命中 visa/working rights/PR/sponsor 而生成没命中 |
| LinkedIn / GitHub 保留 | 同上，匹配 `linkedin.com` / `github.com` |

雇主用前缀匹配是刻意的：履历原文可能有抽取乱码（`VenturelyVc`），模型还原成 `Venturelytic` 属于规则 12 允许的乱码修复，前缀能对上；真换成另一家公司前缀就对不上。

虚构技能不走这套比对——`SKILLS` 词表不认识 CrewAI 这种新框架，比对必然漏。那一项靠模型自己申报，两条路互补：**代码验证不该变的，模型申报自己加的**。

## 排版模板的 ATS 安全边界

前端提供 4 个 CV 模板：Jake's Resume（`tpl-jake`）、Awesome-CV（`tpl-awesome`）、Harshibar（`tpl-harsh`）、Madrid（`tpl-madrid`）。实现上只是 `#preview` 上的一组 CSS class，正文 DOM 结构完全相同：单栏、`h1/h2/h3/p/ul` 语义标签，没有表格、多栏、文本框、图标、图片、页眉页脚。打印成 PDF 后文本流顺序 = 阅读顺序，解析器拿到的内容与纯文本版一致。

刻意没有做 Deedy CV —— 它是双栏的，双栏是已知的 ATS 解析风险（解析器会把两栏文字交错拼接）。

### 复刻原版模板时刻意丢掉的东西

后两个模板照着用户提供的 PDF 复刻，但原 PDF 用 LaTeX 生成，抽取出来的文本有硬伤，这些**只还原视觉，不还原做法**：

| 原版做法 | 抽取后的实际结果 | 我们的替代 |
|---|---|---|
| FontAwesome 图标（Harshibar 联系方式行） | `Phone-Alt 555.555.5555 \| Envelope hello@email.com` —— 图标被抽成字形名混进正文 | 纯文字联系方式行 |
| `\href` 超链接装饰 | `@harshibar` 重复 17 次、视频标题各重复 40 次 —— 会被判 keyword stuffing，触犯规则 2 | HTML 里就是一个文本节点，不重复 |
| pdfLaTeX OT1 编码（Madrid） | `Tel´efono`、`EDUCACI ´ON`、`Espa˜nol` —— 重音被拆成两个字符 | UTF-8，`Renée/Müller/Peña` 原样抽出 |
| 左标签右值双栏（Madrid 个人信息块） | 三个标签先抽出、三个值再抽出，标签和值配不上 | 改成 `标签: 值` 单行 |
| `\hfill` 右对齐日期（Madrid） | `Periodo` 漂到所有 bullets 之后，ATS 会把日期配错职位 | 日期写在 `### 职位 — 公司 (日期)` 同一行内 |

### 验证方法

改完模板要重跑一遍真实链路的抽取测试（和 ATS 拿到的是同一份 PDF）：

```bash
venv/bin/pip install pdfminer.six                      # 仅验证用，不进 requirements.txt
# 把 index.html 的 <style> + 一份样例内容拼成 <div id="preview" class="paper tpl-XXX">，然后：
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --no-pdf-header-footer --print-to-pdf=out.pdf file://.../p.html
venv/bin/python -c "from pdfminer.high_level import extract_text; print(extract_text('out.pdf'))"
```

要检查的六项：连字（U+FB00-FB06）、游离组合重音（`´\`¨˜ˆ`）、字母间被插空格（`S K I L L S`）、异常重复词、节标题顺序、日期是否还跟在对应职位标题同一行。四个模板当前全部通过。

注意：`text-transform: uppercase` 会让抽取出的节标题变成全大写（`PROFESSIONAL SUMMARY`），这是预期且安全的——大写节标题本身就是 ATS 常见写法，匹配不区分大小写。

改模板时必须守住的三条：

1. **不要用 `float` / `position` / 多列布局改变视觉顺序**——PDF 抽取按内容流输出，视觉位置和文本顺序一旦不一致，解析结果就会串行。
2. **`letter-spacing` 不超过 .08em**——字距接近空格宽度时，PDF 文本抽取器（pdfminer/Tika 一类）会在字母之间插入空格，`SKILLS` 变成 `S K I L L S`，节标题识别直接失效。
3. **必须保留 `font-variant-ligatures: none`**——浏览器打印时会把 `fi`/`fl`/`ff` 合成连字（U+FB01 等），`workflow` 在 PDF 里就不是 `workflow`，ATS 关键词匹配直接落空。这是唯一一个我们自己管线里真实存在的同类风险，`.paper` 上已全局关掉。
4. **信息只能承载在文字里，不能承载在样式里**——颜色、边框、加粗都会在解析时丢掉，所以任何靠视觉表达的内容（如用色块表示熟练度）都不允许。进度条/评分条是明确禁止项（见规则 5）。

`text-transform: uppercase` 是安全的（大写节标题本身就是 ATS 常见写法），衬线/无衬线字体、配色、分隔线也不影响解析。但**不要用 `font-variant-caps: small-caps`**——系统字体大多没有真正的 smcp 字形，浏览器会合成，合成小型大写在 PDF 里同样会出现拆字。Jake's 原版的 `\scshape` 在这里统一用 `uppercase` + 缩小字号模拟。

## Sources

- [ATS Filtering and Keyword Screening Statistics 2026](https://onehour.digital/blog/ats-filtering-and-keyword-screening-statistics)
- [ATS Resume Keywords: What Actually Works in 2026](https://www.uppl.ai/ats-resume-keywords)
- [AI Resume Screening in 2026: How It Works & How to Pass](https://atsverification.com/blog/ai-resume-screening-2026/)
- [AI-Proof Resume Guide 2026](https://resumevera.com/blogs/ai-proof-resume-ai-screening-2026)
- [Resume screening: AI-powered guide for HR leaders (2026)](https://mihcm.com/resources/blog/resume-screening-in-2026-a-guide-to-ai-powered-screening-ats-integration-bias-governance/)
- [Jobscan: 500+ Resume Keywords for the ATS](https://www.jobscan.co/blog/top-resume-keywords-boost-resume/)
- [HiredScore AI for Recruiting | Workday](https://www.workday.com/en-us/products/talent-management/ai-recruiting.html)
- [Jobscan: iCIMS ATS What Job Seekers Need to Know](https://www.jobscan.co/blog/icims-ats/)
- [iCIMS Resume Format Guide: Parser Rules, AI Scoring](https://resumeoptimizerpro.com/blog/icims-resume-format-guide)
- [Jobscan: Greenhouse ATS & the Recruiter Scorecard](https://www.jobscan.co/blog/greenhouse-ats-what-job-seekers-need-to-know/)
- [ATS-Friendly Resume Tips (Australia, 2026)](https://www.tursa.com.au/articles/beat-ai-resume-screening/)
- [ATS Resume Australia 2026](https://www.resumeadapter.com/blog/ats-resume-australia)
