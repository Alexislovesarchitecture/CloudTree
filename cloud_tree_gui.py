#!/usr/bin/env python3
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

try:
    import ttkbootstrap as ttkb
    _TTKBOOTSTRAP = True
except Exception:
    ttkb = None
    _TTKBOOTSTRAP = False

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from cloud_tree_core import (
    default_exclude_exts_text,
    load_config,
    parse_exclude_exts,
    parse_exclude_words,
    resolve_default_outdir,
    run_snapshot,
    save_config,
)


def format_size(bytes_count: int | None) -> str:
    if bytes_count is None:
        return "?"
    s = float(bytes_count)
    for unit in ["B", "K", "M", "G", "T"]:
        if s < 1024:
            return f"{s:.0f}{unit}"
        s /= 1024
    return f"{s:.1f}P"


def create_root() -> tk.Tk:
    if _TTKBOOTSTRAP:
        return ttkb.Window(themename="flatly")
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("clam")
    except Exception:
        pass
    return root


class CloudTreeApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("CloudTree")
        self.root.minsize(920, 700)

        self.root_var = tk.StringVar(master=self.root)
        self.label_var = tk.StringVar(master=self.root)
        self.out_var = tk.StringVar(master=self.root, value=str(resolve_default_outdir()))
        self.depth_var = tk.IntVar(master=self.root, value=4)
        self.suffix_var = tk.StringVar(master=self.root, value="FILTERED")
        self.gen_tree_var = tk.BooleanVar(master=self.root, value=True)
        self.gen_tsv_var = tk.BooleanVar(master=self.root, value=True)
        self.remember_var = tk.BooleanVar(master=self.root, value=True)
        self.exclude_exts_var = tk.StringVar(master=self.root, value=default_exclude_exts_text())
        self.exclude_words_var = tk.StringVar(master=self.root, value="")

        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._last_outdir: Path | None = None
        self._last_output_paths: list[str] = []
        self._label_user_set = False

        self._build_ui()
        self._load_config()
        self._ensure_output_not_in_app(on_startup=True)
        self.root.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        title = ttk.Label(main, text="CloudTree", font=("TkDefaultFont", 14, "bold"))
        title.grid(row=0, column=0, sticky="w", pady=(0, 8))

        root_frame = ttk.Frame(main)
        root_frame.grid(row=1, column=0, sticky="ew")
        root_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(root_frame, text="Root folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(root_frame, textvariable=self.root_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(root_frame, text="Browse", command=self._browse_root).grid(row=0, column=2, sticky="ew")

        label_frame = ttk.Frame(main)
        label_frame.grid(row=2, column=0, sticky="ew", pady=(6, 2))
        label_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(label_frame, text="Label:").grid(row=0, column=0, sticky="w")
        self.label_entry = ttk.Entry(label_frame, textvariable=self.label_var)
        self.label_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.label_entry.bind("<KeyRelease>", self._on_label_key)

        out_frame = ttk.Frame(main)
        out_frame.grid(row=3, column=0, sticky="ew", pady=(6, 2))
        out_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(out_frame, text="Output folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(out_frame, textvariable=self.out_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(out_frame, text="Browse", command=self._browse_out).grid(row=0, column=2, sticky="ew")

        options = ttk.Labelframe(main, text="Options", padding=10)
        options.grid(row=4, column=0, sticky="ew", pady=(8, 4))
        options.grid_columnconfigure(5, weight=1)

        ttk.Checkbutton(options, text="Generate Tree TXT", variable=self.gen_tree_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(options, text="Generate TSV Index", variable=self.gen_tsv_var).grid(row=0, column=1, sticky="w", padx=(14, 0))

        ttk.Label(options, text="Depth:").grid(row=0, column=2, sticky="w", padx=(18, 4))
        ttk.Spinbox(options, from_=0, to=10, textvariable=self.depth_var, width=4).grid(row=0, column=3, sticky="w")
        ttk.Label(options, text="0 = unlimited").grid(row=0, column=4, sticky="w", padx=(6, 0))

        ttk.Label(options, text="Suffix:").grid(row=0, column=5, sticky="e", padx=(18, 4))
        ttk.Combobox(
            options,
            textvariable=self.suffix_var,
            values=["FILTERED", "FILTERED2"],
            state="readonly",
            width=12,
        ).grid(row=0, column=6, sticky="w")

        filters = ttk.Labelframe(main, text="Filters", padding=10)
        filters.grid(row=5, column=0, sticky="ew", pady=(4, 4))
        filters.grid_columnconfigure(1, weight=1)
        ttk.Label(filters, text="Exclude extensions (comma/space):").grid(row=0, column=0, sticky="w")
        ttk.Entry(filters, textvariable=self.exclude_exts_var).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(filters, text="Exclude words (comma/line):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(filters, textvariable=self.exclude_words_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        run_frame = ttk.Frame(main)
        run_frame.grid(row=6, column=0, sticky="ew", pady=(8, 6))
        run_frame.grid_columnconfigure(1, weight=1)
        self.run_btn = ttk.Button(run_frame, text="Run", command=self._start_run)
        self.run_btn.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(run_frame, mode="indeterminate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        ttk.Checkbutton(run_frame, text="Remember settings", variable=self.remember_var).grid(
            row=0, column=2, sticky="e", padx=(12, 0)
        )

        log_frame = ttk.Labelframe(main, text="Progress Log", padding=10)
        log_frame.grid(row=7, column=0, sticky="nsew", pady=(6, 6))
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll.grid(row=0, column=1, sticky="ns")

        results = ttk.Labelframe(main, text="Results", padding=10)
        results.grid(row=8, column=0, sticky="ew")
        results.grid_columnconfigure(1, weight=1)

        self.tree_result_var = tk.StringVar(master=self.root, value="Tree: —")
        self.tsv_result_var = tk.StringVar(master=self.root, value="TSV: —")
        self.count_result_var = tk.StringVar(master=self.root, value="Files indexed: —")

        ttk.Label(results, textvariable=self.tree_result_var).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(results, textvariable=self.tsv_result_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(results, textvariable=self.count_result_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self.open_btn = ttk.Button(results, text="Open Output Folder", command=self._open_output, state="disabled")
        self.open_btn.grid(row=0, column=3, sticky="e", padx=(12, 0))
        self.copy_btn = ttk.Button(results, text="Copy Output Paths", command=self._copy_paths, state="disabled")
        self.copy_btn.grid(row=1, column=3, sticky="e", padx=(12, 0))

        main.grid_rowconfigure(7, weight=1)

    def _on_label_key(self, _event: tk.Event) -> None:
        self._label_user_set = True

    def _maybe_set_label(self, root_path: str) -> None:
        if self._label_user_set:
            return
        self.label_var.set(Path(root_path).name)

    def _set_root(self, path: str) -> None:
        self.root_var.set(path)
        self._maybe_set_label(path)

    def _browse_root(self) -> None:
        chosen = filedialog.askdirectory(title="Select folder to snapshot")
        if chosen:
            self._set_root(chosen)

    def _browse_out(self) -> None:
        chosen = filedialog.askdirectory(title="Select output folder")
        if chosen:
            self.out_var.set(chosen)

    def _load_config(self) -> None:
        data = load_config()
        if data.get("last_root"):
            self.root_var.set(str(data.get("last_root")))
        if data.get("last_label"):
            self.label_var.set(str(data.get("last_label")))
            self._label_user_set = True
        if data.get("last_out"):
            self.out_var.set(str(data.get("last_out")))
        if data.get("last_depth") is not None:
            try:
                self.depth_var.set(int(data.get("last_depth")))
            except Exception:
                pass
        if data.get("last_suffix"):
            self.suffix_var.set(str(data.get("last_suffix")))
        if data.get("last_do_tree") is not None:
            self.gen_tree_var.set(bool(data.get("last_do_tree")))
        if data.get("last_do_tsv") is not None:
            self.gen_tsv_var.set(bool(data.get("last_do_tsv")))
        if data.get("remember_settings") is not None:
            self.remember_var.set(bool(data.get("remember_settings")))
        if data.get("exclude_exts") is not None:
            self.exclude_exts_var.set(str(data.get("exclude_exts")))
        if data.get("exclude_words") is not None:
            self.exclude_words_var.set(str(data.get("exclude_words")))

        if not self.out_var.get().strip():
            self.out_var.set(str(resolve_default_outdir()))

    def _ensure_output_not_in_app(self, on_startup: bool = False) -> None:
        out = self.out_var.get().strip()
        if not out:
            return
        if ".app/Contents" in out:
            if on_startup:
                messagebox.showwarning(
                    "CloudTree",
                    "Output folder cannot be inside the app bundle. Resetting to default.",
                )
            else:
                messagebox.showwarning(
                    "CloudTree",
                    "Output folder cannot be inside the app bundle. Resetting to default.",
                )
            self.out_var.set(str(resolve_default_outdir()))

    def _log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _start_run(self) -> None:
        root = self.root_var.get().strip()
        if not root:
            messagebox.showerror("CloudTree", "Please choose a root folder.")
            return

        root_path = Path(root).expanduser().resolve()
        if not root_path.exists() or not root_path.is_dir():
            messagebox.showerror("CloudTree", f"Root is not a directory:\n{root_path}")
            return

        label = self.label_var.get().strip() or root_path.name
        depth = int(self.depth_var.get())
        suffix = self.suffix_var.get().strip() or "FILTERED"
        gen_tree = bool(self.gen_tree_var.get())
        gen_tsv = bool(self.gen_tsv_var.get())
        exclude_exts = parse_exclude_exts(self.exclude_exts_var.get())
        exclude_words = parse_exclude_words(self.exclude_words_var.get())

        if not gen_tree and not gen_tsv:
            messagebox.showerror("CloudTree", "Select at least one output type (Tree TXT or TSV).")
            return
        self._ensure_output_not_in_app()
        outdir = Path(self.out_var.get().strip() or resolve_default_outdir()).expanduser().resolve()

        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            messagebox.showerror(
                "CloudTree",
                "Terminal/Python needs Full Disk Access to read this folder.",
            )
            return

        self.run_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.copy_btn.configure(state="disabled")
        self.progress.start(10)
        self._last_outdir = None
        self._last_output_paths = []
        self.tree_result_var.set("Tree: —")
        self.tsv_result_var.set("TSV: —")
        self.count_result_var.set("Files indexed: —")

        thread = threading.Thread(
            target=self._worker,
            args=(root_path, label, outdir, suffix, depth, gen_tree, gen_tsv, exclude_exts, exclude_words),
            daemon=True,
        )
        thread.start()

    def _worker(
        self,
        root: Path,
        label: str,
        outdir: Path,
        suffix: str,
        depth: int,
        gen_tree: bool,
        gen_tsv: bool,
        exclude_exts: set[str],
        exclude_words: set[str],
    ) -> None:
        try:
            result = run_snapshot(
                root=root,
                out_dir=outdir,
                label=label,
                suffix=suffix,
                depth=depth,
                do_tree=gen_tree,
                do_tsv=gen_tsv,
                use_tree=True,
                exclude_exts=exclude_exts,
                exclude_words=exclude_words,
                progress_cb=lambda msg: self._queue.put(("log", msg)),
            )
            self._queue.put(("done", result))
        except Exception as exc:
            self._queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self._log(str(payload))
            elif kind == "done":
                result = payload
                tree_path = result.get("tree_path")
                tsv_path = result.get("tsv_path")

                if tree_path:
                    self.tree_result_var.set(f"Tree: {tree_path} ({format_size(result.get('tree_size'))})")
                    self._last_output_paths.append(str(tree_path))
                if tsv_path:
                    self.tsv_result_var.set(
                        f"TSV: {tsv_path} ({format_size(result.get('tsv_size'))})"
                    )
                    self._last_output_paths.append(str(tsv_path))
                self.count_result_var.set(f"Files indexed: {result.get('files_indexed', 0)}")

                if result.get("permission_error"):
                    msg = "Terminal/Python needs Full Disk Access to read this folder."
                    self._log(msg)
                    messagebox.showwarning("CloudTree", msg)

                self._last_outdir = tree_path.parent if tree_path else tsv_path.parent if tsv_path else None
                if self._last_outdir:
                    self.open_btn.configure(state="normal")
                if self._last_output_paths:
                    self.copy_btn.configure(state="normal")

                if self.remember_var.get():
                    save_config(
                        {
                            "last_root": str(self.root_var.get().strip()),
                            "last_label": str(self.label_var.get().strip()),
                            "last_out": str(self.out_var.get().strip()),
                            "last_depth": int(self.depth_var.get()),
                            "last_suffix": str(self.suffix_var.get().strip()),
                            "last_do_tree": bool(self.gen_tree_var.get()),
                            "last_do_tsv": bool(self.gen_tsv_var.get()),
                            "exclude_exts": str(self.exclude_exts_var.get().strip()),
                            "exclude_words": str(self.exclude_words_var.get().strip()),
                            "remember_settings": True,
                        }
                    )
                else:
                    save_config(
                        {
                            "last_root": "",
                            "last_label": "",
                            "last_out": "",
                            "last_depth": 4,
                            "last_suffix": "FILTERED",
                            "last_do_tree": True,
                            "last_do_tsv": True,
                            "exclude_exts": default_exclude_exts_text(),
                            "exclude_words": "",
                            "remember_settings": False,
                        }
                    )

                self.run_btn.configure(state="normal")
                self.progress.stop()
            elif kind == "error":
                self._log(f"Error: {payload}")
                messagebox.showerror("CloudTree", f"Error:\n{payload}")
                self.run_btn.configure(state="normal")
                self.progress.stop()

        self.root.after(100, self._poll_queue)

    def _open_output(self) -> None:
        if not self._last_outdir:
            return
        path = str(self._last_outdir)
        try:
            if sys.platform.startswith("darwin"):
                subprocess.run(["open", path], check=False)
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as exc:
            messagebox.showerror("CloudTree", f"Could not open folder:\n{exc}")

    def _copy_paths(self) -> None:
        if not self._last_output_paths:
            return
        text = "\n".join(self._last_output_paths)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self._log("Copied output paths to clipboard.")


if __name__ == "__main__":
    app = CloudTreeApp(create_root())
    app.root.mainloop()
