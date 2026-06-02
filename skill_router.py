import json

def select_skill_name(user_input, skill_metas, skill_router_llm):
    if not skill_metas:
        return None, "No skills available"
    
    available_skills = [ {
        "name": meta.name,
        "description": meta.description,
        }
        for meta in skill_metas
        ]
    
    messages = [
        {
            "role": "system",
            "content": (
                "You are a skill router. "
                "Your only job is to decide whether one skill should be loaded "
                "for the user's request. "
                "Do not answer the user's request. "
                "Choose based only on the available skill names and descriptions. "
                "Return JSON only: "
                '{"skill": null, "reason": "..."} or {"skill": "one-available-skill-name", "reason": "..."}.'
                "Choose at most one skill. "
                "Only choose a name from available_skills. "
                "Use null if no skill clearly applies. "
                "Prefer the most specific clearly relevant skill. "
                "If multiple skills seem possible, choose the one that best matches "
                "the user's main intent. "
                "If the match is weak or uncertain, choose null."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_input": user_input,
                    "available_skills": available_skills,
                },
                ensure_ascii=False,
            ),
        },
    ]

    message = skill_router_llm(messages)
    try:
        data = json.loads(message.content or "{}")
        if not isinstance(data, dict):
            return None, "skill router returned non-object JSON"
    except json.JSONDecodeError:
        return None, "skill router returned invalid JSON"
    
    selected_name = data.get("skill")
    reason = data.get("reason", "")

    if selected_name is None:
        return None, reason
    
    allowed_names = {skill.name for skill in skill_metas}
    if selected_name not in allowed_names:
        return None, f"skill router selected invalid skill name: {selected_name}"
    
    return selected_name, reason