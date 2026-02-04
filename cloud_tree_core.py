#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_EXCLUDED_EXTS = {
    "udsmesh", "uds", "obj", "fbx", "stl", "gltf", "glb", "ply",
    "las", "laz", "e57", "rcp", "rcs",
}
DEFAULT_EXCLUDED_BASENAMES = {".ds_store"}
DEFAULT_EXCLUDED_DIRNAMES = {"mesh", "meshes"}
DEFAULT_EXCLUDED_DIR_PREFIXES = ("pointcloud", "point cloud")


def parse_exclude_exts(text: str | None) -> set[str]:
    if not text:
        return set()
    parts = re.split(r"[\s,;]+", text.strip())
    return normalize_exclude_exts(parts)


def parse_exclude_words(text: str | None) -> set[str]:
    if not text:
        return set()
    parts = re.split(r"[,;\n]+", text)
    return normalize_exclude_words(parts)


def normalize_exclude_exts(items: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for item in items:
        s = str(item).strip().lower()
        if not s:
            continue
        if s.startswith("."):
            s = s[1:]
        if s:
            out.add(s)
    return out


def normalize_exclude_words(items: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for item in items:
        s = str(item).strip().lower()
        if s:
            out.add(s)
    return out


def default_exclude_exts_text() -> str:
    return ", ".join(sorted(DEFAULT_EXCLUDED_EXTS))


def default_exclude_exts_list() -> list[str]:
    return sorted(DEFAULT_EXCLUDED_EXTS)


@dataclass(frozen=True)
class Filters:
    excluded_exts: set[str]
    excluded_basenames: set[str]
    excluded_dirnames: set[str]
    excluded_dir_prefixes: tuple[str, ...]
    excluded_words: set[str]


def build_filters(
    exclude_exts: Iterable[str] | None = None,
    exclude_words: Iterable[str] | None = None,
    exclude_basenames: Iterable[str] | None = None,
    exclude_dirnames: Iterable[str] | None = None,
    exclude_dir_prefixes: Iterable[str] | None = None,
) -> Filters:
    exts = normalize_exclude_exts(exclude_exts) if exclude_exts is not None else set(DEFAULT_EXCLUDED_EXTS)
    words = normalize_exclude_words(exclude_words) if exclude_words is not None else set()
    basenames = normalize_exclude_words(exclude_basenames) if exclude_basenames is not None else set(DEFAULT_EXCLUDED_BASENAMES)
    dirnames = normalize_exclude_words(exclude_dirnames) if exclude_dirnames is not None else set(DEFAULT_EXCLUDED_DIRNAMES)
    prefixes = tuple(normalize_exclude_words(exclude_dir_prefixes)) if exclude_dir_prefixes is not None else DEFAULT_EXCLUDED_DIR_PREFIXES
    return Filters(
        excluded_exts=exts,
        excluded_basenames=basenames,
        excluded_dirnames=dirnames,
        excluded_dir_prefixes=prefixes,
        excluded_words=words,
    )


def _word_in_text(words: set[str], text: str) -> bool:
    if not words:
        return False
    t = text.lower()
    return any(word in t for word in words)


def is_excluded_dirname(name: str, filters: Filters) -> bool:
    n = name.strip().lower()
    if n in filters.excluded_dirnames:
        return True
    for prefix in filters.excluded_dir_prefixes:
        if n.startswith(prefix):
            return True
    if _word_in_text(filters.excluded_words, n):
        return True
    return False


def is_excluded_filename(name: str, filters: Filters) -> bool:
    n = name.strip().lower()
    if n in filters.excluded_basenames:
        return True
    ext = Path(name).suffix.lower().lstrip(".")
    if ext and ext in filters.excluded_exts:
        return True
    if _word_in_text(filters.excluded_words, n):
        return True
    return False


def safe_path_for_tsv(p: str) -> str:
    # Avoid breaking TSV rows if a path contains tabs/newlines
    return p.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _case_variants(text: str) -> set[str]:
    if not text:
        return set()
    if text.lower() != text:
        return {text}
    return {text, text.capitalize(), text.title()}


def build_tree_ignore_pattern(filters: Filters) -> str:
    # tree -I uses a single pattern string with | separators
    parts: list[str] = []

    for ext in sorted(filters.excluded_exts):
        parts.append(f"*.{ext}")

    for name in sorted(filters.excluded_basenames):
        parts.extend(_case_variants(name))

    for dirname in sorted(filters.excluded_dirnames):
        parts.extend(_case_variants(dirname))

    for prefix in filters.excluded_dir_prefixes:
        for variant in _case_variants(prefix):
            parts.append(f"{variant}*")

    return "|".join(dict.fromkeys(parts))


def _permission_flag_from_output(text: str) -> bool:
    return "Permission denied" in text or "Operation not permitted" in text


def write_tree_txt(
    root: Path,
    out_txt: Path,
    use_tree: bool = True,
    depth: int = 0,
    filters: Filters | None = None,
) -> tuple[int, bool]:
    active_filters = filters or build_filters()
    tree_bin = shutil.which("tree") if use_tree else None
    if tree_bin and not active_filters.excluded_words:
        ignore_pat = build_tree_ignore_pattern(active_filters)
        args = [tree_bin, str(root)]
        if depth and depth > 0:
            args.extend(["-L", str(depth)])
        if ignore_pat:
            args.extend(["-I", ignore_pat])
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        out_txt.write_text(proc.stdout, encoding="utf-8", errors="replace")
        return out_txt.stat().st_size, _permission_flag_from_output(proc.stdout)

    # Python tree output (filtered; supports word filters, case-insensitive)
    permission_error = False
    lines = [str(root)]

    def safe_is_dir(entry: os.DirEntry[str]) -> bool:
        nonlocal permission_error
        try:
            return entry.is_dir(follow_symlinks=False)
        except TypeError:
            return entry.is_dir()
        except OSError:
            permission_error = True
            return False

    def walk_dir(path: Path, prefix: str, level: int) -> None:
        nonlocal permission_error
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except PermissionError:
            permission_error = True
            return
        except FileNotFoundError:
            return

        filtered: list[tuple[str, Path, bool]] = []
        for entry in entries:
            name = entry.name
            is_dir = False
            if entry.is_symlink():
                is_dir = False
            else:
                is_dir = safe_is_dir(entry)

            if is_dir:
                if is_excluded_dirname(name, active_filters):
                    continue
            else:
                if is_excluded_filename(name, active_filters):
                    continue

            filtered.append((name, Path(entry.path), is_dir))

        filtered.sort(key=lambda item: (not item[2], item[0].lower()))

        for idx, (name, child_path, is_dir) in enumerate(filtered):
            last = idx == len(filtered) - 1
            connector = "\\-- " if last else "|-- "
            lines.append(f"{prefix}{connector}{name}")
            if is_dir and (depth == 0 or level < depth):
                extension = "    " if last else "|   "
                walk_dir(child_path, prefix + extension, level + 1)

    walk_dir(root, "", 1)

    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8", errors="replace")
    return out_txt.stat().st_size, permission_error


def write_index_tsv(root: Path, out_tsv: Path, filters: Filters | None = None) -> tuple[int, bool]:
    count = 0
    permission_error = False
    active_filters = filters or build_filters()

    def on_walk_error(err: OSError) -> None:
        nonlocal permission_error
        if isinstance(err, PermissionError):
            permission_error = True

    with out_tsv.open("w", encoding="utf-8", errors="replace") as f:
        for dirpath, dirnames, filenames in os.walk(root, onerror=on_walk_error):
            # prune excluded directories
            dirnames[:] = [d for d in dirnames if not is_excluded_dirname(d, active_filters)]

            for name in filenames:
                if is_excluded_filename(name, active_filters):
                    continue

                full = Path(dirpath) / name
                try:
                    st = full.stat()
                except FileNotFoundError:
                    continue
                except PermissionError:
                    permission_error = True
                    continue

                line = f"{safe_path_for_tsv(str(full))}\t{st.st_size}\t{int(st.st_mtime)}\n"
                f.write(line)
                count += 1
    return count, permission_error


def resolve_default_outdir() -> Path:
    if is_packaged_app():
        out = Path.home() / "Documents" / "CloudTree" / "snapshots" / "cloud_tree"
    else:
        out = Path("/Users/alexislovesarchitecture/Desktop/CodexWorkspace/snapshots/cloud_tree")
    return out.resolve()


def is_packaged_app() -> bool:
    return hasattr(sys, "_MEIPASS") or ".app/Contents" in Path(__file__).as_posix()


def get_config_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "CloudTree" / "config.json"


def load_config() -> dict:
    path = get_config_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {}


def save_config(data: dict) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def run_snapshot(
    root: Path,
    out_dir: Path,
    label: str,
    suffix: str = "FILTERED",
    depth: int = 0,
    do_tree: bool = True,
    do_tsv: bool = True,
    use_tree: bool = True,
    exclude_exts: Iterable[str] | None = None,
    exclude_words: Iterable[str] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    tree_path = out_dir / f"{label}_tree_{suffix}_{ts}.txt" if do_tree else None
    tsv_path = out_dir / f"{label}_files_index_{suffix}_{ts}.tsv" if do_tsv else None

    tree_size = None
    tsv_size = None
    files_indexed = 0
    permission_error = False

    if progress_cb:
        progress_cb("Starting scan...")

    filters = build_filters(exclude_exts=exclude_exts, exclude_words=exclude_words)

    if tree_path:
        if progress_cb:
            progress_cb("Writing tree...")
        tree_size, perm = write_tree_txt(
            root,
            tree_path,
            use_tree=use_tree,
            depth=depth,
            filters=filters,
        )
        permission_error = permission_error or perm

    if tsv_path:
        if progress_cb:
            progress_cb("Writing TSV...")
        files_indexed, perm = write_index_tsv(root, tsv_path, filters=filters)
        permission_error = permission_error or perm
        tsv_size = tsv_path.stat().st_size

    if progress_cb:
        progress_cb("Done")

    return {
        "tree_path": tree_path,
        "tree_size": tree_size,
        "tsv_path": tsv_path,
        "tsv_size": tsv_size,
        "files_indexed": files_indexed,
        "permission_error": permission_error,
    }
