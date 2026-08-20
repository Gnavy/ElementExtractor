import zipfile
from pathlib import Path
from typing import Iterable, Tuple

# 固定时间戳，相同内容打出相同 MD5，历史任务的解压与 OCR 结果才能复用
FIXED_ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def zip_entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=name, date_time=FIXED_ZIP_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


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
            zf.writestr(zip_entry(Path(name).name), data)
        for name, data in sorted(extras, key=lambda pair: Path(pair[0]).name):
            safe = Path(name).name
            zf.writestr(zip_entry(f"{extras_prefix}/{safe}"), data)
