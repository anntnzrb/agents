#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# ///
"""Reliable emacsclient wrapper for live Emacs introspection and reloads.

Examples:
  uv run --script <skill-dir>/scripts/cli.py ping
  uv run --script <skill-dir>/scripts/cli.py face default
  uv run --script <skill-dir>/scripts/cli.py buffer
  uv run --script <skill-dir>/scripts/cli.py key 'C-x C-f'
  uv run --script <skill-dir>/scripts/cli.py library package
  uv run --script <skill-dir>/scripts/cli.py feature use-package
  cat query.el | uv run --script <skill-dir>/scripts/cli.py eval - --json
  uv run --script <skill-dir>/scripts/cli.py eval-file <temp-dir>/query.el --json
  uv run --script <skill-dir>/scripts/cli.py reload-init
  uv run --script <skill-dir>/scripts/cli.py load path/to/init.el

"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path


class EmacsCtlError(RuntimeError):
    """Raised for emacsclient-related failures."""


def elisp_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def read_expr(expr: str | None) -> str:
    if expr is None or expr == "-":
        data = sys.stdin.read()
        if not data.strip():
            raise EmacsCtlError("no Elisp expression provided on stdin")
        return data
    return expr


def build_json_form(expr: str, pretty: bool) -> str:
    pretty_flag = "t" if pretty else "nil"
    return f"""
(progn
  (require 'json)
  (let* ((json-encoding-pretty-print {pretty_flag})
         (value (progn {expr}))
         (json-str (json-encode value))
         (b64 (base64-encode-string json-str t)))
    b64))
""".strip()


def format_error(message: str) -> str:
    msg = message.strip()
    lower = msg.lower()
    if "can't find socket" in lower or "no socket or alternate editor" in lower:
        return (
            "emacsclient could not find a running Emacs server. "
            "Start one in Emacs with M-x server-start, or ensure the right "
            "socket/server-file is selected.\n\nOriginal error:\n"
            f"{msg}"
        )
    return msg or "emacsclient failed"


def run_emacsclient(args: argparse.Namespace, form: str) -> str:
    cmd = [args.emacsclient]
    if args.socket_name:
        cmd += ["--socket-name", args.socket_name]
    if args.server_file:
        cmd += ["--server-file", args.server_file]
    cmd += ["--eval", form]

    result = subprocess.run(
        cmd,
        check=False,
        shell=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise EmacsCtlError(format_error(result.stderr or result.stdout))
    return result.stdout.strip()


def decode_base64_lisp_string(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    try:
        return base64.b64decode(raw.encode("ascii")).decode("utf-8")
    except Exception as exc:  # pragma: no cover
        raise EmacsCtlError(
            f"failed to decode emacsclient JSON payload: {exc}",
        ) from exc


def print_json(data: object) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def json_eval(args: argparse.Namespace, expr: str) -> None:
    raw = run_emacsclient(args, build_json_form(expr, pretty=False))
    payload = decode_base64_lisp_string(raw)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise EmacsCtlError(
            f"Emacs returned invalid JSON: {exc}\nPayload: {payload}",
        ) from exc
    print_json(data)


def cmd_ping(args: argparse.Namespace) -> int:
    expr = """
(list
  (cons "emacs_version" emacs-version)
  (cons "system_type" (symbol-name system-type))
  (cons "daemonp" (if (daemonp) t :json-false))
  (cons "server_running" (if (fboundp 'server-running-p) (server-running-p) :json-false))
  (cons "user_emacs_directory" user-emacs-directory)
  (cons "user_init_file" (or user-init-file ""))
  (cons "early_init_file" (if (boundp 'early-init-file) (or early-init-file "") ""))
  (cons "data_directory" data-directory))
""".strip()
    json_eval(args, expr)
    return 0


def cmd_face(args: argparse.Namespace) -> int:
    face = args.face
    expr = f"""
(let* ((face '{face})
       (font (face-attribute face :font nil 'default)))
  (list
    (cons "face" (symbol-name face))
    (cons "family" (face-attribute face :family nil 'default))
    (cons "height" (face-attribute face :height nil 'default))
    (cons "font" (if font (format "%s" font) ""))))
""".strip()
    json_eval(args, expr)
    return 0


def cmd_buffer(args: argparse.Namespace) -> int:
    expr = """
(list
  (cons "buffer_name" (buffer-name))
  (cons "major_mode" (symbol-name major-mode))
  (cons "default_directory" default-directory)
  (cons "file_name" (or buffer-file-name "")))
""".strip()
    json_eval(args, expr)
    return 0


def cmd_key(args: argparse.Namespace) -> int:
    key = args.key_sequence
    expr = f"""
(let* ((key {elisp_string(key)})
       (cmd (key-binding (kbd key))))
  (list
    (cons "key" key)
    (cons "command"
          (cond
           ((symbolp cmd) (symbol-name cmd))
           ((stringp cmd) cmd)
           (cmd (format "%S" cmd))
           (t "")))))
""".strip()
    json_eval(args, expr)
    return 0


def cmd_library(args: argparse.Namespace) -> int:
    name = args.name
    expr = f"""
(let ((name {elisp_string(name)}))
  (list
    (cons "library" name)
    (cons "path" (or (locate-library name) ""))))
""".strip()
    json_eval(args, expr)
    return 0


def cmd_feature(args: argparse.Namespace) -> int:
    name = args.name
    expr = f"""
(let* ((name {elisp_string(name)})
       (feature (intern name)))
  (list
    (cons "feature" name)
    (cons "loaded" (if (featurep feature) t :json-false))
    (cons "library" (or (locate-library name) ""))))
""".strip()
    json_eval(args, expr)
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    expr = read_expr(args.expr)
    if args.json:
        json_eval(args, expr)
    else:
        print(run_emacsclient(args, expr))
    return 0


def cmd_eval_file(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    expr = path.read_text(encoding="utf-8")
    if args.json:
        json_eval(args, expr)
    else:
        print(run_emacsclient(args, expr))
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    expr = (
        "(list "
        f'(cons "loaded" {elisp_string(str(path))}) '
        f'(cons "result" (load-file {elisp_string(str(path))})))'
    )
    json_eval(args, expr)
    return 0


def cmd_reload_init(args: argparse.Namespace) -> int:
    expr = """
(let ((path (or user-init-file "")))
  (list
    (cons "loaded" path)
    (cons "result" (and (stringp path) (> (length path) 0) (load-file path)))))
""".strip()
    json_eval(args, expr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reliable emacsclient wrapper")
    parser.add_argument(
        "--emacsclient",
        default="emacsclient",
        help="emacsclient binary to use (default: emacsclient)",
    )
    parser.add_argument("--socket-name", help="optional Emacs socket name")
    parser.add_argument("--server-file", help="optional Emacs server file")

    sub = parser.add_subparsers(dest="command", required=True)

    ping = sub.add_parser(
        "ping",
        help="check connectivity and print runtime basics as JSON",
    )
    ping.set_defaults(func=cmd_ping)

    face = sub.add_parser(
        "face",
        help="print family/height/font data for a face as JSON",
    )
    face.add_argument("face", help="face symbol name, e.g. default or fixed-pitch")
    face.set_defaults(func=cmd_face)

    buffer_cmd = sub.add_parser("buffer", help="print current buffer basics as JSON")
    buffer_cmd.set_defaults(func=cmd_buffer)

    key = sub.add_parser(
        "key",
        help="resolve a key sequence in the current context as JSON",
    )
    key.add_argument("key_sequence", help="key sequence, e.g. C-x C-f")
    key.set_defaults(func=cmd_key)

    library = sub.add_parser("library", help="locate a library on load-path as JSON")
    library.add_argument(
        "name",
        help="library name without .el, e.g. package or use-package",
    )
    library.set_defaults(func=cmd_library)

    feature = sub.add_parser(
        "feature",
        help="check feature load state and likely library path as JSON",
    )
    feature.add_argument("name", help="feature name, e.g. server or use-package")
    feature.set_defaults(func=cmd_feature)

    ev = sub.add_parser("eval", help="evaluate Elisp expression or read it from stdin")
    ev.add_argument(
        "expr",
        nargs="?",
        help="Elisp expression, or - / omitted to read from stdin",
    )
    ev.add_argument(
        "--json",
        action="store_true",
        help="treat result as JSON-encodable and print parsed JSON",
    )
    ev.set_defaults(func=cmd_eval)

    evf = sub.add_parser("eval-file", help="evaluate Elisp loaded from a file")
    evf.add_argument("path", help="path to .el file containing an Elisp expression")
    evf.add_argument(
        "--json",
        action="store_true",
        help="treat result as JSON-encodable and print parsed JSON",
    )
    evf.set_defaults(func=cmd_eval_file)

    load = sub.add_parser("load", help="load-file PATH and print a small JSON result")
    load.add_argument("path", help="path to file to load into the running Emacs")
    load.set_defaults(func=cmd_load)

    reload_init = sub.add_parser(
        "reload-init",
        help="load the current user-init-file and print JSON",
    )
    reload_init.set_defaults(func=cmd_reload_init)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        parser.exit(127, f"required executable not found: {exc.filename}\n")
    except EmacsCtlError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
