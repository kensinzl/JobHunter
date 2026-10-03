# 经验等级筛选（Seniority Filter）设计

日期：2026-08-09 · 状态：待实现

## 目标

搜索偏好里新增「经验等级」多选，按等级过滤抓取结果。**与排除关键词并存**，不替换——排除关键词继续负责技术栈等非等级排除。

## 等级档位

四档，存入 prefs 的新键 `levels`（CSV 字符串，与其他 prefs 字段同为字符串，如 `"junior,mid_senior"`；空串 = 不限）：

| key | 界面文案 | LinkedIn `f_E` 码 | 本地标题词（词边界匹配，不区分大小写） |
|-----|---------|------------------|--------------------------------------|
| `intern` | 实习 | 1 | intern, internship |
| `junior` | 初级·毕业生 | 2,3 | junior, jnr, graduate, grad, entry, trainee, cadet |
| `mid_senior` | 中高级 | 4 | senior, sr |
| `director_plus` | 总监及以上 | 5,6 | lead, principal, head, director, chief, executive, vp |

注：不收 `staff`（澳洲医疗岗 Staff Nurse 会误伤）、不收 `manager`（太泛）。词表是保守启发式，宁可漏排不误杀。

## 过滤机制

**LinkedIn（原生）**：`scrape_linkedin` 把所选等级映射成 `f_E` 参数（逗号拼接，如勾初级+中高级 → `f_E=2,3,4`），由 LinkedIn 服务端按招聘方标注的等级过滤。未选任何等级则不传该参数。

**本地兜底（两个源都跑）**：新增 `level_excluded(title, levels_csv)`，紧挨现有 `excluded()`。规则：

- 未选任何等级 → 不过滤（返回 False）。
- 标题命中某个**未选**档位的词，且未命中任何**已选**档位的词 → 排除。
- 标题不含任何等级词（如 "Data Analyst"）→ 保留。**无标记职位一律保留**，这是已确认的决定。

`api_search` 里在现有 `excluded()` 判断旁并列调用。

## 缓存键

`search_key` 的字段元组加入 `"levels"`——等级变了视为搜索条件变化，走现有的清列表确认流程（409 → confirm）。

## 前端

偏好页（`#prefs`）在排除关键词一行下方加四个 checkbox（一行排开，label「经验等级」）。`loadPrefs`/`savePrefs` 按 CSV 拆装 `levels`。无新依赖、无新文件。

## 测试（test_smoke.py，纯逻辑，不碰网络）

- `level_excluded`：无选择不过滤；"Senior Data Analyst" 在只选 junior 时被排除、在选 mid_senior 时保留；"Data Analyst"（无标记）任何选择下都保留；同时命中已选与未选档位（如 "Graduate / Junior Engineer" 选 junior）保留。
- `f_E` 映射：选集 → 参数串（含空选 → 不传）。
- `search_key` 包含 `levels`：改等级后 key 变化。

## 不做的事

- Seek 端不找隐藏的等级参数（其 API 无此维度）。
- 不做 JD 正文的经验年限解析（JD 是生成时才懒加载的，搜索阶段拿不到）。
