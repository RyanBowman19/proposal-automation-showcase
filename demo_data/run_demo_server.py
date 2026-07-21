"""Runs the search server against the fake demo data in this folder, for
recording/screenshots only. Not part of the real tool - the real one reads
resumes_index.json/profiles_index.json built from src.resumes/src.profiles
against the actual company drives.

    py demo_data/run_demo_server.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from http.server import ThreadingHTTPServer
from src.web import Handler

server = ThreadingHTTPServer(("127.0.0.1", 8790), Handler)
print("demo server up on http://127.0.0.1:8790", flush=True)
server.serve_forever()
