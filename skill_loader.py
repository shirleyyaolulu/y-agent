from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path("skills")

@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    path: Path


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    content: str

def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    
    raw_meta = parts[1].strip()
    body = parts[2].strip()

    meta = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body

def discover_skill_metadata(skills_dir=SKILLS_DIR):
    if not skills_dir.exists():
        return []
    
    metas = []
    for path in sorted(skills_dir.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(text)

        metas.append(SkillMeta(
            name=meta.get("name", path.parent.name),
            description=meta.get("description", ""),
            path=str(path),
        ))
    return metas

def load_skills(meta):
    path = Path(meta.path)
    text = path.read_text(encoding="utf-8")
    parsed_meta, body = parse_frontmatter(text)

    return Skill(
        name=parsed_meta.get("name", meta.name),
        description=parsed_meta.get("description", meta.description),
        path=str(path),
        content=body,
    )
 