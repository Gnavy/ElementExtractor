import shutil
from pathlib import Path


def copy_skills_to_extract(
    repo_skills: Path,
    extract_root: Path,
    *,
    only_skill: str | None = None,
) -> Path:
    """
    Copy bundled skills into Claude Code project skills directory.
    only_skill: 若指定则仅复制该子目录（如 business-review-case1）。
    """
    dest = extract_root / ".claude" / "skills"
    dest.mkdir(parents=True, exist_ok=True)
    if not repo_skills.exists():
        return dest
    for child in repo_skills.iterdir():
        if only_skill and child.is_dir() and child.name != only_skill:
            continue
        if only_skill and child.is_file():
            continue
        if child.is_dir():
            target = dest / child.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)
        elif child.is_file():
            shutil.copy2(child, dest / child.name)
    return dest
