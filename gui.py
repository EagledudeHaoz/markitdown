#!/usr/bin/env python3
"""
MarkItDown Converter — simple desktop GUI

A point-and-click front end for Microsoft's MarkItDown. Pick a file or a
folder, pick where to save the results, click Convert, and watch progress
in the log window. No command line required.

Run it with:
    python gui.py

Requirements:
    pip install 'markitdown[all]'
    (tkinter ships with standard Python installers on Windows/Mac; on Linux
     you may need: sudo apt-get install python3-tk)
"""

import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from markitdown import MarkItDown

MARKDOWN_EXT = ".md"

DEFAULT_SKIP_EXTENSIONS = {
    ".exe", ".dll", ".so", ".bin", ".pyc", ".class", ".o", ".a",
    ".git", ".gitignore", ".ds_store", ".lock",
}


# ---------- conversion logic (same behavior as the CLI version) ----------

def should_skip(path: Path, skip_exts):
    if path.name.startswith("."):
        return "hidden file"
    if path.suffix.lower() in skip_exts:
        return f"excluded extension ({path.suffix})"
    if path.suffix.lower() == MARKDOWN_EXT:
        return "already markdown"
    return None


def collect_files(root: Path):
    if root.is_file():
        return [root]
    return [p for p in sorted(root.rglob("*")) if p.is_file()]


def convert_one(md: MarkItDown, src: Path, out_root: Path, in_root: Path, skip_existing: bool):
    rel = src.relative_to(in_root) if in_root.is_dir() else Path(src.name)
    out_path = (out_root / rel).with_suffix(MARKDOWN_EXT)

    if skip_existing and out_path.exists():
        return ("skipped", str(src), str(out_path), "output already exists")

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = md.convert(str(src))
        text = getattr(result, "markdown", None) or result.text_content
        out_path.write_text(text or "", encoding="utf-8")
        return ("ok", str(src), str(out_path), "")
    except Exception as e:
        return ("error", str(src), None, f"{type(e).__name__}: {e}")


# ------------------------------- GUI ------------------------------------

class MarkItDownGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MarkItDown Converter")
        self.geometry("720x560")
        self.minsize(640, 480)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar(value=str(Path.cwd() / "output"))
        self.skip_existing = tk.BooleanVar(value=False)
        self.use_plugins = tk.BooleanVar(value=False)
        self.llm_images = tk.BooleanVar(value=False)
        self.llm_model = tk.StringVar(value="gpt-4o")
        self.status_text = tk.StringVar(value="Pick a file or folder to begin.")

        self.log_queue = queue.Queue()
        self.worker_thread = None
        self.total_files = 0
        self.done_files = 0

        self._build_layout()
        self.after(150, self._poll_log_queue)

    # ---- layout ----
    def _build_layout(self):
        pad = {"padx": 10, "pady": 6}

        # Input row
        frame_in = ttk.Frame(self)
        frame_in.pack(fill="x", **pad)
        ttk.Label(frame_in, text="Convert:", width=10).pack(side="left")
        ttk.Entry(frame_in, textvariable=self.input_path).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(frame_in, text="Choose File...", command=self._pick_file).pack(side="left", padx=3)
        ttk.Button(frame_in, text="Choose Folder...", command=self._pick_folder).pack(side="left")

        # Output row
        frame_out = ttk.Frame(self)
        frame_out.pack(fill="x", **pad)
        ttk.Label(frame_out, text="Save to:", width=10).pack(side="left")
        ttk.Entry(frame_out, textvariable=self.output_path).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(frame_out, text="Choose...", command=self._pick_output).pack(side="left")

        # Options
        frame_opts = ttk.LabelFrame(self, text="Options")
        frame_opts.pack(fill="x", **pad)

        ttk.Checkbutton(frame_opts, text="Skip files already converted", variable=self.skip_existing).grid(
            row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(frame_opts, text="Enable installed MarkItDown plugins", variable=self.use_plugins).grid(
            row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(
            frame_opts, text="Describe images with an LLM (needs OPENAI_API_KEY)",
            variable=self.llm_images, command=self._toggle_llm_row
        ).grid(row=2, column=0, sticky="w", padx=8, pady=4)

        self.llm_model_label = ttk.Label(frame_opts, text="Model:")
        self.llm_model_entry = ttk.Entry(frame_opts, textvariable=self.llm_model, width=20)
        self.llm_model_label.grid(row=2, column=1, sticky="w", padx=(4, 2))
        self.llm_model_entry.grid(row=2, column=2, sticky="w")
        self._toggle_llm_row()

        # Convert button + progress
        frame_action = ttk.Frame(self)
        frame_action.pack(fill="x", **pad)
        self.convert_btn = ttk.Button(frame_action, text="Convert", command=self._start_conversion)
        self.convert_btn.pack(side="left")
        self.progress = ttk.Progressbar(frame_action, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        ttk.Label(self, textvariable=self.status_text, anchor="w").pack(fill="x", padx=12)

        # Log
        frame_log = ttk.LabelFrame(self, text="Log")
        frame_log.pack(fill="both", expand=True, **pad)
        self.log_box = tk.Text(frame_log, height=14, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(frame_log, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scrollbar.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _toggle_llm_row(self):
        state = "normal" if self.llm_images.get() else "disabled"
        self.llm_model_label.configure(state=state)
        self.llm_model_entry.configure(state=state)

    # ---- file pickers ----
    def _pick_file(self):
        path = filedialog.askopenfilename(title="Choose a file to convert")
        if path:
            self.input_path.set(path)

    def _pick_folder(self):
        path = filedialog.askdirectory(title="Choose a folder to convert")
        if path:
            self.input_path.set(path)

    def _pick_output(self):
        path = filedialog.askdirectory(title="Choose an output folder")
        if path:
            self.output_path.set(path)

    # ---- logging helpers ----
    def _log(self, line: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ---- conversion ----
    def _start_conversion(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return

        in_str = self.input_path.get().strip()
        out_str = self.output_path.get().strip()
        if not in_str:
            messagebox.showwarning("No input selected", "Please choose a file or folder to convert first.")
            return
        in_path = Path(in_str).expanduser()
        if not in_path.exists():
            messagebox.showerror("Not found", f"This path does not exist:\n{in_path}")
            return
        if not out_str:
            messagebox.showwarning("No output selected", "Please choose an output folder.")
            return

        self.convert_btn.configure(state="disabled")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.status_text.set("Starting...")
        self.progress["value"] = 0

        self.worker_thread = threading.Thread(
            target=self._run_conversion,
            args=(in_path, Path(out_str).expanduser(),
                  self.skip_existing.get(), self.use_plugins.get(),
                  self.llm_images.get(), self.llm_model.get()),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_conversion(self, in_path, out_root, skip_existing, use_plugins, llm_images, llm_model):
        try:
            out_root.mkdir(parents=True, exist_ok=True)
            all_files = collect_files(in_path)
            todo, pre_skipped = [], []
            for f in all_files:
                reason = should_skip(f, DEFAULT_SKIP_EXTENSIONS)
                (pre_skipped if reason else todo).append((f, reason) if reason else f)

            self.log_queue.put(("info", f"Found {len(all_files)} file(s). Converting {len(todo)}, skipping {len(pre_skipped)}."))
            self.log_queue.put(("total", len(todo)))
            for f, reason in pre_skipped:
                self.log_queue.put(("line", f"-  {f}  ({reason})"))

            import inspect

            kwargs = {}

            if llm_images:
                try:
                    from openai import OpenAI
                except ImportError:
                    self.log_queue.put((
                        "error_box",
                        "The 'openai' package is required for image descriptions.\n"
                        "Install it with: pip install openai"
                    ))
                    self.log_queue.put(("done", None))
                    return
            
                kwargs["llm_client"] = OpenAI()
                kwargs["llm_model"] = llm_model
            
            md = MarkItDown(**kwargs)
            in_root_for_rel = in_path if in_path.is_dir() else in_path.parent

            ok = err = skipped = len(pre_skipped)
            ok = 0
            err = 0
            for f in todo:
                status, src, out_path, detail = convert_one(md, f, out_root, in_root_for_rel, skip_existing)
                symbol = {"ok": "✓", "error": "✗", "skipped": "-"}[status]
                if status == "ok":
                    ok += 1
                elif status == "error":
                    err += 1
                else:
                    skipped += 1
                self.log_queue.put(("line", f"{symbol} {src}" + (f"  ({detail})" if detail else "")))
                self.log_queue.put(("progress", 1))

            self.log_queue.put(("summary", (ok, skipped, err)))
        except Exception as e:
            self.log_queue.put(("error_box", f"Unexpected error:\n{type(e).__name__}: {e}"))
        finally:
            self.log_queue.put(("done", None))

    def _poll_log_queue(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "info":
                    self._log(payload)
                elif kind == "line":
                    self._log(payload)
                elif kind == "total":
                    self.total_files = max(payload, 1)
                    self.done_files = 0
                    self.progress["maximum"] = self.total_files
                elif kind == "progress":
                    self.done_files += payload
                    self.progress["value"] = self.done_files
                    self.status_text.set(f"Converting... {self.done_files}/{self.total_files}")
                elif kind == "summary":
                    ok, skipped, err = payload
                    self.status_text.set(f"Done — converted {ok}, skipped {skipped}, errors {err}")
                    self._log(f"\nConverted: {ok}   Skipped: {skipped}   Errors: {err}")
                elif kind == "error_box":
                    messagebox.showerror("Error", payload)
                elif kind == "done":
                    self.convert_btn.configure(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._poll_log_queue)


if __name__ == "__main__":
    app = MarkItDownGUI()
    app.mainloop()
