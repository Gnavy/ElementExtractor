import zipfile
from pathlib import Path


def _is_safe_path(base: Path, target: Path) -> bool:
    try:
        base_res = base.resolve()
        target_res = target.resolve()
        return str(target_res).startswith(str(base_res))
    except OSError:
        return False


def _decode_zip_name(raw: str) -> str:
    """Try to fix mojibake from cp437-zipped UTF-8 names (common on Windows)."""
    try:
        return raw.encode("cp437").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return raw


def extract_zip_archive(zip_path: Path, dest_dir: Path) -> None:
    """
    Extract zip to dest_dir, skipping __MACOSX and .DS_Store.
    Best-effort UTF-8 filename repair for garbled Chinese paths.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if "__MACOSX" in name or name.startswith("._"):
                continue
            parts = name.replace("\\", "/").split("/")
            if any(p == ".DS_Store" for p in parts):
                continue

            decoded_parts = []
            for p in parts:
                if p == "":
                    continue
                decoded_parts.append(_decode_zip_name(p))
            rel = "/".join(decoded_parts)
            if not rel or rel.endswith("/"):
                continue

            target = (dest_dir / rel).resolve()
            if not _is_safe_path(dest_dir.resolve(), target):
                continue

            if name.endswith("/") or (hasattr(info, "is_dir") and info.is_dir()):
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())
