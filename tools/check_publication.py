"""Check the explicit public-file boundary and recognizable credential patterns.

This is a local publication check, not a guarantee of business-data clearance.
PNG pixels require visual review; PNG text/EXIF metadata is not permitted.
"""
import ast
import os
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRECTORIES = {".git", ".venv", "venv", "__pycache__", ".cache"}
PATTERNS = {
    "GitHub token": rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
    "Cloud access key": rb"AKIA[A-Z0-9]{16}",
    "Google API key": rb"AIza[A-Za-z0-9_-]{30,}",
    "Private key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "Private IPv4 address": rb"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b",
}


def check_png(data, name):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("INVALID_PNG: " + name)
    offset = 8
    allowed = {b"IHDR", b"sRGB", b"gAMA", b"pHYs", b"IDAT", b"IEND"}
    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        if kind not in allowed or offset + size + 12 > len(data):
            raise ValueError("UNREVIEWED_PNG_METADATA_OR_CHUNK: " + name)
        offset += size + 12
        if kind == b"IEND":
            if size or offset != len(data):
                raise ValueError("UNEXPECTED_PNG_TRAILER: " + name)
            return
    raise ValueError("INCOMPLETE_PNG: " + name)


def check():
    allowlist = (ROOT / "publication-files.txt").read_text().splitlines()
    if len(allowlist) != len(set(allowlist)):
        raise ValueError("DUPLICATE_ALLOWLIST_PATH")
    actual = set()
    for directory, subdirectories, files in os.walk(ROOT):
        subdirectories[:] = [name for name in subdirectories if name not in IGNORED_DIRECTORIES]
        actual.update((Path(directory) / name).relative_to(ROOT).as_posix() for name in files)
    if actual != set(allowlist):
        raise ValueError("FILE_ALLOWLIST_MISMATCH: " + repr(sorted(actual ^ set(allowlist))))
    total = 0
    for name in allowlist:
        path = ROOT / name
        if path.is_symlink() or any(p == ".." for p in Path(name).parts):
            raise ValueError("UNSAFE_PATH")
        data = path.read_bytes()
        total += len(data)
        if len(data) > 100_000:
            raise ValueError("UNEXPECTED_LARGE_FILE: " + name)
        if path.suffix == ".png":
            check_png(data, name)
            continue
        text = data.decode("utf-8")
        for label, pattern in PATTERNS.items():
            if re.search(pattern, data):
                raise ValueError(label + " pattern found in " + name)
        if path.suffix == ".py":
            ast.parse(text, filename=name)
        if path.suffix == ".md":
            if text.count("```") % 2:
                raise ValueError("UNBALANCED_CODE_FENCE: " + name)
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if "://" not in target and not (path.parent / target).is_file():
                    raise ValueError("BROKEN_DOCUMENT_LINK: " + name)
        if any(line.rstrip() != line for line in text.splitlines()):
            raise ValueError("TRAILING_WHITESPACE: " + name)
    print(f"PASS: {len(allowlist)} allowlisted files, {total} bytes; text syntax, links, credential patterns and PNG metadata checked")


if __name__ == "__main__":
    check()
