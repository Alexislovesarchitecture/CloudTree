#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from cloud_tree_core import parse_exclude_exts, parse_exclude_words, resolve_default_outdir, run_snapshot


def format_size(bytes_count: int | None) -> str:
    if bytes_count is None:
        return "?"
    s = float(bytes_count)
    for unit in ["B", "K", "M", "G", "T"]:
        if s < 1024:
            return f"{s:.0f}{unit}"
        s /= 1024
    return f"{s:.1f}P"


def main() -> None:
    ap = argparse.ArgumentParser(description="Cloud Tree: filtered tree + TSV index snapshots.")
    ap.add_argument("--root", help="Root folder to snapshot (if omitted, GUI picker opens).")
    ap.add_argument("--label", help="Label used in output filenames (default: basename of root).")
    ap.add_argument("--out", help="Output directory for snapshots (default: ../snapshots/cloud_tree).")
    ap.add_argument(
        "--exclude-exts",
        help="Comma/space separated extensions to exclude (example: obj, fbx).",
    )
    ap.add_argument(
        "--exclude-words",
        help="Comma/line separated words to exclude from names (case-insensitive).",
    )
    args = ap.parse_args()

    root = args.root
    label = args.label
    outdir = Path(args.out).expanduser().resolve() if args.out else resolve_default_outdir()
    exclude_exts = parse_exclude_exts(args.exclude_exts)
    exclude_words = parse_exclude_words(args.exclude_words)

    if not root:
        # GUI picker mode
        try:
            import tkinter as tk
            from tkinter import filedialog, simpledialog, messagebox
        except Exception:
            print("Tkinter not available. Run with --root instead.", file=sys.stderr)
            sys.exit(1)

        tk.Tk().withdraw()
        chosen = filedialog.askdirectory(title="Select folder to snapshot")
        if not chosen:
            return
        root = chosen
        default_label = Path(root).name
        label = simpledialog.askstring(
            "Cloud Tree",
            "Label for outputs (optional):",
            initialvalue=default_label,
        ) or default_label
        messagebox.showinfo("Cloud Tree", f"Creating snapshots for:\n{root}\n\nLabel:\n{label}")

    root_path = Path(root).expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise SystemExit(f"Root is not a directory: {root_path}")

    if not label:
        label = root_path.name

    result = run_snapshot(
        root=root_path,
        out_dir=outdir,
        label=label,
        suffix="FILTERED",
        depth=0,
        do_tree=True,
        do_tsv=True,
        use_tree=True,
        exclude_exts=exclude_exts,
        exclude_words=exclude_words,
    )

    if result.get("permission_error"):
        print("Terminal/Python needs Full Disk Access to read this folder.")

    print("Done.")
    if result.get("tree_path"):
        print(f"Tree: {result['tree_path']} ({format_size(result.get('tree_size'))})")
    if result.get("tsv_path"):
        print(f"TSV : {result['tsv_path']} ({format_size(result.get('tsv_size'))})")


if __name__ == "__main__":
    main()
