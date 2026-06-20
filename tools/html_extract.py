"""
html_extract — HTML 内容提取。
用 BeautifulSoup + lxml 从 HTML 中提取文本、链接、表格。
"""

import re

from ._helpers import proposal_reply


def _get_soup(html: str, parser: str = "lxml"):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None, parser
    try:
        return BeautifulSoup(html, parser), parser
    except Exception:
        try:
            return BeautifulSoup(html, "html.parser"), "html.parser"
        except Exception:
            return None, "html.parser"


def extract(html: str, what: str = "text", selector: str = "") -> dict:
    """从 HTML 提取结构化内容。

    Args:
        html: HTML 字符串
        what:  提取类型
               text   — 纯文本（去标签，保留段落结构）
               links  — 所有链接 [{text, href}]
               tables — 所有表格 [{headers, rows}]
               query  — CSS 选择器结果（需 selector）
        selector: CSS 选择器，如 "div.content p"、"#main"

    Returns:
        {"ok": True, "data": ...} 或 {"ok": False, "error": ...}
    """
    try:
        soup, parser = _get_soup(html)
        if soup is None:
            if parser == "lxml":
                return {"ok": False, "error": "beautifulsoup4 未安装。请运行: pip install beautifulsoup4 lxml"}
            return {"ok": False, "error": "HTML 解析器初始化失败"}
    except Exception as e:
        return {"ok": False, "error": f"HTML 解析器初始化失败: {e}"}

    try:
        if what == "text":
            # 仅移除脚本和样式，保留语义标签中的正文
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            # 合并多余空行
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            return {
                "ok": True,
                "data": {"text": "\n".join(lines), "line_count": len(lines)},
            }

        elif what == "links":
            links = []
            for a in soup.find_all("a", href=True):
                links.append(
                    {
                        "text": a.get_text(strip=True)[:100],
                        "href": a["href"],
                    }
                )
            return {"ok": True, "data": {"links": links, "count": len(links)}}

        elif what == "tables":
            tables = []
            for t in soup.find_all("table"):
                headers = [th.get_text(strip=True) for th in t.find_all("th")]
                rows = []
                for tr in t.find_all("tr"):
                    # 跳过已作为 headers 捕获的表头行
                    if tr.find("th") and not rows:
                        continue
                    cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if cols:
                        rows.append(cols)
                tables.append(
                    {"headers": headers, "rows": rows, "row_count": len(rows)}
                )
            return {"ok": True, "data": {"tables": tables, "count": len(tables)}}

        elif what == "query":
            if not selector:
                return {"ok": False, "error": "what='query' 需要 selector 参数"}
            elements = soup.select(selector)
            if not elements:
                return {
                    "ok": True,
                    "data": {"results": [], "count": 0},
                    "proposal": f"CSS 选择器 '{selector}' 未匹配任何元素",
                    "evidence": {"selector": selector},
                    "options": ["简化选择器(去掉层级)", "尝试 what='text' 提取全文"],
                }
            results = [el.get_text(strip=True)[:200] for el in elements]
            html_snippets = []
            for el in elements[:5]:
                pretty = el.prettify()
                first_line = pretty.split("\n")[0] if "\n" in pretty else pretty[:300]
                html_snippets.append(first_line[:300])
            return {
                "ok": True,
                "data": {
                    "selector": selector,
                    "results": results,
                    "count": len(elements),
                    "html_preview": html_snippets,
                },
            }

        else:
            return {
                "ok": False,
                "error": f"未知提取类型: {what}，可选 text/links/tables/query",
            }

    except Exception as e:
        return proposal_reply(
            False,
            "HTML 解析失败——lxml 和 html.parser 均无法解析",
            error=f"HTML 解析失败: {e}",
            evidence={"html_preview": html[:200]},
            options=[
                "检查输入是否为完整 HTML",
                "尝试手动提取纯文本",
                "可能非 HTML 格式",
            ],
        )
