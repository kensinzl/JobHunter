import collections, functools, json, os, re, sys
from fastapi import FastAPI, HTTPException, Request


"""
PDF and DOCX extraction
"""

# PDF 里的 fi/fl 连字必须还原成普通字母，否则 "workﬂow" 存进知识库，
# 后面 CV 里所有 workflow 关键词对 ATS 都是无效的（详见 docs/ats-research.md）
# ı/ȷ 是 LaTeX 拆重音时用的无点 i/j，还原后才能和下面的重音合成 í/ĵ
LIGATURES = {0xFB00: "ff", 0xFB01: "fi", 0xFB02: "fl", 0xFB03: "ffi", 0xFB04: "ffl",
             0xFB05: "st", 0xFB06: "st", 0x00A0: " ", 0x2019: "'", 0x0131: "i", 0x0237: "j"}

# pdfLaTeX 的 OT1 编码会把 é 拆成「´ + e」两个字符，抽出来是 Tel´efono / EDUCACI ´ON。
# 只对真正会带该重音的字母合成，避免把 don´t 误合成 donT́。
ACCENTS = [("´", "́", "aeiouyncAEIOUYNC"), ("`", "̀", "aeiouAEIOU"),
           ("¨", "̈", "aeiouyAEIOUY"), ("˜", "̃", "anoANO"),
           ("ˆ", "̂", "aeiouAEIOU"), ("¸", "̧", "csCS")]

# FontAwesome 图标在 PDF 里会被抽成字形名，混进联系方式行。
# 只列不可能是正常英文词的：phone/home/link/at/medium/github 这些同时也是真词，
# 删错了等于篡改履历，宁可留着让人自己删。
ICON_NAMES = {"phone-alt", "mobile-alt", "map-marker", "map-marker-alt", "envelope", "envelope-o",
              "linkedin-in", "x-twitter", "stack-overflow", "address-book", "paper-plane"}

def extract_upload(data: bytes, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        from io import BytesIO
        from pdfminer.high_level import extract_text
        text = extract_text(BytesIO(data))
    elif ext == ".docx":
        # ponytail: docx 就是个 zip，正文在 word/document.xml，段落边界是 </w:p>——用不着 python-docx
        import html, zipfile
        from io import BytesIO
        with zipfile.ZipFile(BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        text = html.unescape(re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n")))
    elif ext in (".txt", ".md"):
        text = data.decode("utf-8", "replace")
    else:
        raise HTTPException(400, f"不支持 {ext or '这种'} 格式，只接受 PDF / DOCX / TXT / MD")
    return re.sub(r"\n{3,}", "\n\n", _clean_extracted(text.translate(LIGATURES))).strip()


def _clean_extracted(text: str) -> str:
    """修掉 PDF 抽取的四类硬伤：坏连字映射、拆开的重音、重复绘制的行、混进来的图标字形名。"""
    import unicodedata
    text = _fix_broken_ligatures(text)
    for mark, comb, letters in ACCENTS:
        # 抽取器常在重音符号两侧插空格（EDUCACI ´ON），词中间的那个空格要一起吞掉。
        # ponytail: 靠「前面是字母」判断词中间，行首独立的 ´Elena 会留下空格——人工在文本框里能看见
        text = re.sub(f"(?:(?<=[A-Za-z]) )?[{re.escape(mark)}] ?([{letters}])",
                      lambda m: unicodedata.normalize("NFC", m.group(1) + comb), text)

    # 同一行出现 4 次以上 = PDF 把带链接的文字重复画了，只留第一次。
    # ponytail: 阈值 4 是为了保住真实简历里合理的重复（同一雇主出现两三次）；
    #           非相邻的循环重复（A B C A B C）也靠这条兜住，相邻重复再单独去一次。
    lines = [l.rstrip() for l in text.split("\n")]
    counts = collections.Counter(l.strip() for l in lines if l.strip())
    out, emitted = [], set()
    for l in lines:
        s = l.strip()
        if s and counts[s] > 3:
            if s in emitted:
                continue
            emitted.add(s)
        if s and out and out[-1].strip() == s:
            continue
        # 上一行的碎片重画（"Creator (@handle" 后面又跟一行 "@handle)"）：
        # 去掉标点后被上一行包含、且很短，就丢掉
        # ponytail: 30 字上限是怕误删真内容；碰到更长的重画就得改成按坐标去重
        if s and len(s) < 30 and out and _core(s) and _core(s) in _core(out[-1]):
            continue
        out.append(l)

    # 图标字形名只在开头的联系方式块里剔除，正文里的 GitHub/YouTube 是真内容，不动
    for i, l in enumerate(out[:6]):
        if l.strip():
            out[i] = " ".join(w for w in l.split() if w.lower().strip(":") not in ICON_NAMES)
    return "\n".join(out)

def _fix_broken_ligatures(text: str) -> str:
    """Word 导出的 Calibri 系 PDF 常带坏的 ToUnicode 映射，连字变成错的 ASCII：
    ti→Q（producQon）、ft→K（SoKware）、tt→e（https→heps）。
    e 没法通用还原，只修 URL 协议头；Q/K 只在小写字母之间还原。"""
    text = re.sub(r"\bheps(?=://)", "https", text)
    text = re.sub(r"\bhep(?=://)", "http", text)
    # Q 后面是 u 的不动（jQuery）；K 前面是 Mc/Mac 的不动（McKinsey）
    # ponytail: 拼音驼峰名（XiaoQing）这类词中大写会被误修——真碰到再加白名单
    text = re.sub(r"(?<=[a-z])Q(?!u)(?=[a-z])", "ti", text)
    text = re.sub(r"(?<!Mc)(?<!Mac)(?<=[a-z])K(?=[a-z])", "ft", text)
    return text

def _core(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", s.lower())