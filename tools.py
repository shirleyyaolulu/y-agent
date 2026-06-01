import time
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup
import json
from pathlib import Path
from memory import save_memory

MAX_TOOL_CHARS = 4000
NOTES_DIR = Path("notes")

def tool_success(data):
    return json.dumps({"success": True, "data": data}, ensure_ascii=False)

def tool_error(message, error_type="tool_error"):
    return json.dumps({"success": False, "error_type": error_type, "message": message}, ensure_ascii=False)

def truncate_text(text, max_chars=MAX_TOOL_CHARS):
    if len(text) <= max_chars:
        return text

    return (
        text[:max_chars]
        + f"\n\n[TRUNCATED: original length={len(text)} chars, returned first {max_chars} chars]"
    )


def get_time(args):
    # return time.strftime("%Y-%m-%d %H:%M:%S")
    return tool_success({"result": time.strftime("%Y-%m-%d %H:%M:%S")})

def calculator(args):
    expr = args.get("expression", "")
    # return str(eval(expr))
    return tool_success({"result": str(eval(expr))})


def search_web(args):
    query = args["query"]
    limit = args.get("limit", 5)
    
    url = "https://duckduckgo.com/html/?q=" + quote_plus(query)
    try:
        resp = requests.get(
            url,
            timeout = 10,
            headers = {"User-Agent":"Mozilla/5/0"}
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for result in soup.select(".result__body")[:limit]:
            title_el = result.select_one(".result__title")
            link_el = result.select_one(".result__a") 
            snippet_el = result.select_one(".result__snippet")

            title = title_el.get_text(strip=True) if title_el else ""
            link = link_el["href"] if link_el else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            if title and link:
                results.append({"title": title, "link": link, "snippet": snippet})

        return tool_success({
            "query": query,
            "results": results
        })
    except Exception as e:
        return tool_error(f"Web search failed: {e}", error_type="web_search_error")
    

def read_url(args):
    url = args["url"]
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        title = soup.title.get_text(strip=True) if soup.title else ""
        text = soup.get_text("\n", strip=True)
        text = truncate_text(text)

        return tool_success({
            "url": url,
            "title": title,
            "content": text,
        })

    except Exception as e:
        return tool_error(str(e), error_type="read_url_failed")
    
def save_note(args):
    title = args["title"]
    content = args["content"]

    try:
        NOTES_DIR.mkdir(exist_ok=True)

        safe_title  = "".join(
            c if c.isalnum() or c in ("-", "_") else "_"
            for c in title.strip()
        )
        if not safe_title:
            safe_title = f"note_{int(time.time())}"

        path = NOTES_DIR / f"{safe_title}.md"
        path.write_text(content, encoding="utf-8")

        return tool_success({
            "title": title,
            "path": str(path),
            "chars": len(content),
        })
    
    except Exception as e:
        return tool_error(str(e), error_type="save_note_failed")
    


def remember_fact(args):
    memory_type = args.get("type", "fact")
    content = args.get("content")
    if not content:
        return tool_error("Missing required memory content.", error_type="invalid_memory")

    item = save_memory(memory_type, content)

    return tool_success({
        "type": item["type"],
        "content": item["content"],
        "created_at": item["created_at"],
    })
