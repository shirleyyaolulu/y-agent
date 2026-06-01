from dataclasses import dataclass

from tools import (
    get_time,
    calculator,
    save_note,
    read_url,
    search_web,
    remember_fact,

)
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: callable
    capability: str = "read"


TOOL_SPECS = [
    ToolSpec(
        name="get_time",
        description="Get the current local time. Use this when the user asks for the current time or date.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=get_time,
        capability="read",
    ),
    ToolSpec(
        name="calculator",
        description="Perform a calculation. Use this when the user asks to calculate a mathematical expression.",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The mathematical expression to calculate.",
                },
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
        handler=calculator,
        capability="read", 
    ),
    ToolSpec(
        name="search_web",
        description="Search the web for recent information. Use this when the answer is not known or needs to be up-to-date.",
        parameters={
            "type": "object",
            "properties": {
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
            "additionalProperties": False,
        },
        handler=search_web,
        capability="network",
    ),
    ToolSpec(
        name="read_url",
        description="Read the content of a web page. Use this when you need to extract information from a specific URL.",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the web page to read.",
                },
            },
            "required": ["url"],
            "additionalProperties": False,  
        },
        handler=read_url,
        capability="network",
    ),
    ToolSpec(
        name="save_note",
        description="Save a note. Use this when the user wants to save some information for later retrieval.",
        parameters={
            "type": "object",   
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title of the note.",
                },
                "content": {
                    "type": "string",
                    "description": "The content of the note to save.",
                },
            },
            "required": ["title", "content"],
            "additionalProperties": False,  
        },
        handler=save_note,  
        capability="write",
    ),
    ToolSpec(
        name="remember_fact",
        description="Save a long-term memory. Use this when the user expicitly asks you to remember something.",
        parameters={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum":["preference", "profile", "project", "fact"],
                    "description": "The type of the fact to remember.",
                },
                "content": {
                    "type": "string",
                    "description": "The fact to remember.",
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
        handler=remember_fact,
        capability="write",
    ),
]

TOOL_REGISTRY = { tool.name: tool for tool in TOOL_SPECS}

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": tool_spec.name,
            "description": tool_spec.description,
            "parameters": tool_spec.parameters,
        },
    }
    for tool_spec in TOOL_SPECS
]