import collections, functools, json, os, re, sys
from configure.configure import SKILLS, UA, BLOCK_TAGS
import httpx
from bs4 import BeautifulSoup



# least-recently-used
@functools.lru_cache(maxsize=512)
def _pat(alias):
    # 短的全大写别名（SQL/AWS/ML/R…）必须大小写敏感，否则 "sap"、"r" 会满篇误命中；
    # 边界不用 \b，因为 C++ / C# / CI/CD 里的符号会让 \b 落在错的位置
    flags = 0 if alias.isupper() and len(alias) <= 3 else re.I
    plural = "s?" if len(alias) >= 3 else ""  # stakeholder/dashboard/microservice 在 JD 里基本都是复数
    return re.compile(r"(?<![A-Za-z0-9+#.])" + re.escape(alias) + plural + r"(?![A-Za-z0-9+#])", flags)

# tuple is immutable list
@functools.lru_cache(maxsize=1024)
def skill_match(jd, cv):
    """JD 里出现的技能，按履历里有没有对应证据分成两堆。返回 (命中, 缺失)。"""
    have, miss = [], []
    for name, aliases in SKILLS.items():
        if any(_pat(a).search(jd) for a in aliases):
            (have if any(_pat(a).search(cv) for a in aliases) else miss).append(name)
    return tuple(have), tuple(miss)










