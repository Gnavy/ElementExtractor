import zipfile
from pathlib import Path
from typing import Iterable, Tuple


def build_zip_from_pairs(
    dest_zip: Path,
    *,
    root_file: Tuple[str, bytes] | None = None,
    extras: Iterable[Tuple[str, bytes]] = (),
    extras_prefix: str = "supplements",
) -> None:
    """
    通用 ZIP 构建：
    - root_file: 放在 ZIP 根目录（如 case1 的主 docx）
    - extras: 其余文件放到 extras_prefix/ 下
    """
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if root_file is not None:
            name, data = root_file
            zf.writestr(Path(name).name, data)
        for name, data in extras:
            safe = Path(name).name
            zf.writestr(f"{extras_prefix}/{safe}", data)
