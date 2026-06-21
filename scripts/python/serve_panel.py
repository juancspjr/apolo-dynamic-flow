#!/usr/bin/env python3
"""serve_panel.py — Servidor HTTP para el panel de telemetría."""

import argparse
import http.server
import os
import socketserver
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def main():
    parser = argparse.ArgumentParser(description="Servidor del panel apolo-dynamic-flow")
    parser.add_argument("--repo-root", required=True, help="Raíz del repo")
    parser.add_argument("--flowid", default="", help="Flow ID por defecto")
    parser.add_argument("--port", type=int, default=8765, help="Puerto HTTP")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    class PanelHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(repo_root), **kw)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/" or path == "":
                qs = parse_qs(parsed.query)
                flowid = qs.get("flowid", [args.flowid])[0]
                repo = qs.get("repo", [str(repo_root)])[0]
                new_path = f"/panel/index.html?repo={repo}&flowid={flowid}"
                self.send_response(302)
                self.send_header("Location", new_path)
                self.end_headers()
                return
            if path == "/panel":
                self.send_response(302)
                self.send_header("Location", "/panel/index.html")
                self.end_headers()
                return
            super().do_GET()

        def log_message(self, format, *args):
            status = args[1] if len(args) > 1 else ""
            if isinstance(status, str) and (status.startswith("4") or status.startswith("5")):
                super().log_message(format, *args)

    os.chdir(repo_root)
    try:
        with ReusableTCPServer(("0.0.0.0", args.port), PanelHandler) as httpd:
            url = f"http://localhost:{args.port}/?repo={repo_root}&flowid={args.flowid}"
            print(f"Panel disponible en:")
            print(f"  {url}")
            print(f"Sirviendo desde: {repo_root}")
            print(f"Ctrl+C para detener.\n")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"ERROR: puerto {args.port} ocupado. Matar proceso con:", file=sys.stderr)
            print(f"  fuser -k {args.port}/tcp", file=sys.stderr)
            print(f"  o cambiar puerto: --port {args.port + 1}", file=sys.stderr)
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
