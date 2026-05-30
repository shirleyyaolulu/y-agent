import time
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup
import json
from pathlib import Path

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

TOOLS = {
    "get_time": get_time,
    "calculator": calculator,
    "search_web": search_web,
    "read_url": read_url,
    "save_note": save_note,

}



OPENAI_TOOLS = [
    {
        "type": "function",
        "function":{
            "name": "search_web",
            "description": "Search the web for recent information. Use this when the answer is not known or needs to be up-to-date.",
            "parameters": {
                "type": "object",
                "properties":{
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "The maximum number of search results to return.",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
            "required": ["query"],
            "additionalProperties": False
            },
        },
    },
    {
        "type": "function",
        "function":{
            "name": "read_url",
            "description": "Read the content of a web page. Use this when you need to extract information from a specific URL.",
            "parameters": {
                "type": "object",
                "properties":{
                    "url": {
                        "type": "string",
                        "description": "The URL of the web page to read.",
                    },
                },
            "required": ["url"],
            "additionalProperties": False
            },
        },
    },
    {
        "type": "function",
        "function":{
            "name": "calculator",
            "description": "Calculates the mathematical expression provided in the 'expression' argument and returns the result.",
            "parameters": {
                "type": "object",
                "properties":{
                    "expression": {
                        "type": "string",
                        "description": "The mathematical expression to calculate, e.g. '2 + 2 * (3 - 1)'.",
                    },
                },
            "required": ["expression"],
            "additionalProperties": False
            },
        },
    },
    {
        "type": "function",
        "function":{
            "name": "get_time",
            "description": "Returns the current time in the format YYYY-MM-DD HH:MM:SS.",
            "parameters": {
                "type": "object",
                "properties":{},
            },
        },
    },
    {
        "type": "function",
        "function":{
            "name": "save_note",
            "description": "Saves a note with the given title and content. The note will be saved as a markdown file in the notes directory.",
            "parameters": {
                "type": "object",
                "properties":{
                    "title": {
                        "type": "string",
                        "description": "The title of the note.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content of the note.",
                    },
                },
            "required": ["title", "content"],
            "additionalProperties": False
            },
        },
    },
]