"""The search page. Run with Search Projects.bat (or py -m src.web).

Other computers can open it at http://<this pc's ip>:8765.
Search only - nothing here can change the source files. The LOI Tools tab
is the exception: it saves an uploaded PDF and writes reports to output/,
using src.check/src.compare/src.review under the hood.
"""

import contextlib
import io
import json
import re
import socket
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import check, compare, review
from .profiles import INDEX_PATH as PROJECTS_INDEX, search_index
from .resumes import INDEX_PATH as RESUMES_INDEX, search_resumes

HOST, PORT = "0.0.0.0", 8765
UPLOADS_DIR = compare.ROOT / "output" / "_uploads"
MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # 30MB - plenty for a PDF LOI

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>VS Search</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%232a6db0'/%3E%3Ctext x='32' y='43' font-family='Segoe UI, Arial, sans-serif' font-size='30' font-weight='700' fill='white' text-anchor='middle'%3EVS%3C/text%3E%3C/svg%3E">
<style>
  body { font-family: Segoe UI, sans-serif; max-width: 860px; margin: 0 auto 40px; padding: 0 16px; color: #222; }
  .brandbar { height: 5px; margin: 0 -16px 28px; background: linear-gradient(90deg, #2a6db0, #6fa8dc); }
  h1 { font-size: 22px; display: flex; align-items: center; gap: 10px; }
  .logo { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px;
          background: #2a6db0; color: #fff; border-radius: 7px; font-size: 14px; font-weight: 700; }
  .tabs { margin-bottom: 14px; }
  .tabs button { font-size: 15px; padding: 6px 18px; margin-right: 6px; cursor: pointer;
                 border: 1px solid #2a6db0; background: #fff; color: #2a6db0; border-radius: 6px; }
  .tabs button.active { background: #2a6db0; color: #fff; }
  #q { width: 100%; font-size: 20px; padding: 10px 14px; box-sizing: border-box;
       border: 2px solid #2a6db0; border-radius: 6px; }
  .hint { color: #777; font-size: 13px; margin: 6px 2px 20px; }
  .card { border: 1px solid #ddd; border-radius: 6px; padding: 12px 16px; margin-bottom: 12px; }
  .card h3 { margin: 0 0 6px; font-size: 16px; }
  .card h3 small { color: #888; font-weight: normal; }
  .tag { display: inline-block; background: #e8f0fa; color: #2a6db0; border-radius: 10px;
         padding: 1px 9px; font-size: 12px; margin: 0 4px 4px 0; }
  .people, .snippet { color: #444; font-size: 13px; margin: 4px 0; }
  .path { color: #888; font-size: 12px; word-break: break-all; }
  .actions { margin-top: 6px; }
  .actions button { font-size: 12px; margin-right: 8px; cursor: pointer; }
  .actions .note { font-size: 12px; color: #2a6db0; }
  #count { color: #555; margin-bottom: 14px; }
  #loi-panel label { display: block; margin: 14px 0 4px; font-size: 14px; }
  #loi-panel input, #loi-panel select { font-size: 14px; padding: 6px 8px; }
  #loi-panel select, #loi-panel input[type=file] { width: 100%; box-sizing: border-box; }
  #loi-panel details { margin-top: 14px; color: #555; }
  #loi-panel summary { cursor: pointer; font-size: 13px; }
  #loi-panel button[type=submit] { margin-top: 18px; font-size: 15px; padding: 8px 22px;
    background: #2a6db0; color: #fff; border: none; border-radius: 6px; cursor: pointer; }
  #loi-panel button[type=submit]:disabled { background: #9bb8d3; cursor: default; }
  #loiStatus { margin-top: 14px; font-size: 14px; color: #444; }
  #loiLog { background: #f5f5f5; border-radius: 6px; padding: 10px 12px; max-height: 180px;
    overflow: auto; font-size: 12px; white-space: pre-wrap; margin-top: 8px; }
  #loiResults .card pre { white-space: pre-wrap; background: #f5f5f5; padding: 10px 12px;
    border-radius: 6px; font-size: 13px; }
  #loiResults .card h2 { font-size: 18px; margin: 14px 0 6px; }
  #loiResults .card h3 { font-size: 15px; margin: 14px 0 4px; }
</style>
</head>
<body>
<div class="brandbar"></div>
<h1><span class="logo">VS</span> Search</h1>
<div class="tabs">
  <button id="tab-projects" class="active" onclick="setTab('projects')">Projects</button>
  <button id="tab-resumes" onclick="setTab('resumes')">Resumes</button>
  <button id="tab-loi" onclick="setTab('loi')">LOI Tools</button>
</div>
<input id="q" autofocus>
<p class="hint" id="hint"></p>
<div id="count"></div>
<div id="results"></div>
<div id="loi-panel" style="display:none">
  <p class="hint">Add an LOI PDF - it gets checked for mistakes, then compared
  against past ranked competitors for that same RFP/item, using AI. Or add a
  specific competitor LOI below to compare against that one instead.</p>
  <form id="loiForm">
    <label>LOI to check
      <input type="file" id="loiFile" accept="application/pdf" required>
    </label>
    <label>Competitor LOI to compare against (optional - leave blank to use
      whichever past competitors are already on file)
      <input type="file" id="competitorFile" accept="application/pdf">
    </label>
    <label>Or compare against a past winner in the same discipline (optional -
      useful when there's no past pursuit with the exact same RFP/item)
      <select id="benchPursuit">
        <option value="">— use my file's own RFP/item —</option>
      </select>
    </label>
    <details>
      <summary>More options</summary>
      <label>Client <input id="client" value="INDOT"></label>
      <label>RFP # override (only if it can't guess it from the filename) <input id="rfpOverride"></label>
      <label>Item # override <input id="itemOverride"></label>
      <label>Page limit <input id="maxPages" type="number" min="1"></label>
    </details>
    <button type="submit" id="loiSubmit">Check &amp; Compare</button>
  </form>
  <div id="loiStatus"></div>
  <pre id="loiLog" style="display:none"></pre>
  <div id="loiResults"></div>
</div>
<script>
const q = document.getElementById('q');
let tab = 'projects';
let timer;
const HINTS = {
  projects: 'Every word must match. Use tags (roadway, bridge, drainage, central_indiana...), people, clients, or any word from the write-up. Try: trail lebanon',
  resumes: 'Full-text search of staff resumes. Every word must match. Try: signals &nbsp;or&nbsp; "load rating"',
};

function setTab(name) {
  tab = name;
  document.getElementById('tab-projects').classList.toggle('active', name === 'projects');
  document.getElementById('tab-resumes').classList.toggle('active', name === 'resumes');
  document.getElementById('tab-loi').classList.toggle('active', name === 'loi');

  const isSearch = name === 'projects' || name === 'resumes';
  q.style.display = isSearch ? '' : 'none';
  document.getElementById('hint').style.display = isSearch ? '' : 'none';
  document.getElementById('count').style.display = isSearch ? '' : 'none';
  document.getElementById('results').style.display = isSearch ? '' : 'none';
  document.getElementById('loi-panel').style.display = isSearch ? 'none' : '';

  if (isSearch) {
    document.getElementById('hint').innerHTML = HINTS[name];
    q.focus();
    run();
  } else if (name === 'loi' && !winnersLoaded) {
    loadWinners();
  }
}
setTab('projects');

let winnersLoaded = false;

async function loadWinners() {
  const sel = document.getElementById('benchPursuit');
  try {
    const res = await fetch('/api/winners');
    const byDiscipline = await res.json();
    for (const discipline in byDiscipline) {
      const group = document.createElement('optgroup');
      group.label = discipline;
      for (const w of byDiscipline[discipline]) {
        const opt = document.createElement('option');
        opt.value = w.pursuit;
        opt.textContent = `${w.who} — ${w.pursuit}`;
        group.appendChild(opt);
      }
      sel.appendChild(group);
    }
    winnersLoaded = true;
  } catch (e) {
    // leave just the default option - not critical if this fails
  }
}

q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 250); });

async function run() {
  const terms = q.value.trim();
  const count = document.getElementById('count');
  const box = document.getElementById('results');
  if (!terms) { count.textContent = ''; box.innerHTML = ''; return; }
  let hits;
  try {
    const api = tab === 'projects' ? '/api/search' : '/api/resumes';
    const res = await fetch(api + '?q=' + encodeURIComponent(terms));
    if (!res.ok) { count.textContent = await res.text(); box.innerHTML = ''; return; }
    hits = await res.json();
  } catch (e) {
    count.textContent = "Can't reach the search engine. It may have been stopped on the host PC.";
    box.innerHTML = '';
    return;
  }
  count.textContent = hits.length + ' match(es)';
  box.innerHTML = hits.slice(0, 50).map(tab === 'projects' ? projectCard : resumeCard).join('');
}

function projectCard(h) {
  return `
    <div class="card">
      <h3>${esc(h.title)}</h3>
      <div>${h.tags.map(t => '<span class="tag">' + esc(t) + '</span>').join('')}</div>
      ${h.people.length ? '<div class="people">People: ' + esc(h.people.join(', ')) + '</div>' : ''}
      ${fileBits(h.file)}
    </div>`;
}

function resumeCard(h) {
  return `
    <div class="card">
      <h3>${esc(h.person)} <small>— ${esc(h.variant)}</small></h3>
      ${h.discipline ? '<span class="tag">' + esc(h.discipline) + '</span>' : ''}
      ${h.snippet ? '<div class="snippet">' + esc(h.snippet) + '</div>' : ''}
      ${fileBits(h.file)}
    </div>`;
}

function fileBits(file) {
  return `
    <div class="path">${esc(file)}</div>
    <div class="actions">
      <button onclick="openFolder(this, '${jsq(file)}')"
        title="Opens the folder this file is in.">Open folder</button>
      <button onclick="copyPath(this, '${jsq(file)}')">Copy path</button>
    </div>`;
}

// Three ways to open a folder, tried best-first. A web page has no way to
// reach the desktop itself - browsers refuse to follow a file:// link from an
// http:// page - so every route needs someone else to do the opening:
//   1. the server, when you're at the host PC (nothing to install)
//   2. the vsfolder: handler, on any PC that ran Enable Open Folder.bat
//   3. the clipboard, so you can paste the folder into Explorer yourself
async function openFolder(btn, file) {
  // 1. The server knows whether you're on its machine; don't guess from the URL.
  try {
    const res = await fetch('/api/open?path=' + encodeURIComponent(file));
    if (res.ok && (await res.json()).opened) {
      flash(btn, 'Opening');
      return;
    }
  } catch (e) { /* server unreachable - the routes below don't need it */ }

  // 2. Chromium ignores an unregistered scheme quietly. Firefox pops its own
  // error box instead, so don't even try there.
  const handlerTried = !!window.chrome;
  if (handlerTried) tryHandler(file);

  // 3. Always copy as well, so there's something to fall back on.
  const ok = await copyText(folderOf(file));
  if (!ok) selectText(btn.closest('.actions').previousElementSibling);

  // If the handler is installed, Explorer takes the focus - that's the only
  // signal we get that it worked, and it decides the wording only. Saying
  // "paste it" when the folder already opened is what made this look broken.
  if (handlerTried && !(await stillFocused())) {
    flash(btn, 'Opening');
    return;
  }
  flash(btn, ok ? 'Copied - paste in Explorer' : 'Press Ctrl+C');
}

// False means something else took the focus - on this page that means the
// vsfolder: handler launched Explorer.
function stillFocused() {
  return new Promise(resolve =>
    setTimeout(() => resolve(document.hasFocus()), 700));
}

// Fire the vsfolder: link inside a throwaway iframe rather than assigning
// window.location. Same handoff, but a browser with no handler registered
// cannot disturb the page the user is looking at - assigning location starts
// a real navigation and tears the page's JS context down mid-click.
function tryHandler(file) {
  const frame = document.createElement('iframe');
  frame.style.display = 'none';
  frame.src = 'vsfolder:' + encodeURIComponent(file);
  document.body.appendChild(frame);
  setTimeout(() => frame.remove(), 2000);
}

function folderOf(file) {
  const cut = Math.max(file.lastIndexOf('\\\\'), file.lastIndexOf('/'));
  return cut > 0 ? file.slice(0, cut) : file;
}

// Say what happened next to the buttons. Relabelling the button itself made
// it grow and shove the other button sideways on every click.
function flash(btn, message) {
  const row = btn.closest('.actions');
  let note = row.querySelector('.note');
  if (!note) {
    note = document.createElement('span');
    note.className = 'note';
    row.appendChild(note);
  }
  note.textContent = message;
  clearTimeout(note.timer);
  note.timer = setTimeout(() => note.remove(), 2500);
}

// navigator.clipboard only exists in a "secure context" - https:// or
// localhost. Over the LAN (http://<ip>:8765) it is undefined, so the old
// inline navigator.clipboard.writeText() threw and Copy path silently did
// nothing for everyone except someone sitting at the host PC. Fall back to
// the hidden-textarea + execCommand trick, which plain http still allows.
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.cssText = 'position:fixed;top:-1000px;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, ta.value.length);
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

// Both fallbacks can still be refused (locked-down browser policy), so say
// so on the button instead of failing quietly, and select the path text on
// the page so Ctrl+C works by hand.
async function copyPath(btn, path) {
  const ok = await copyText(path);
  if (!ok) selectText(btn.closest('.actions').previousElementSibling);
  flash(btn, ok ? 'Copied' : 'Press Ctrl+C');
}

function selectText(el) {
  if (!el) return;
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function jsq(s) { return s.replace(/\\\\/g, '\\\\\\\\').replace(/'/g, "\\\\'"); }

// --- LOI Tools tab: upload a PDF and it gets checked + compared. The
// pursuit (which competitor data to benchmark against) is normally guessed
// from the file's own name, unless benchPursuit picks a different one
// (a past winner in the same discipline).

let loiPollTimer;

document.getElementById('loiForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  clearTimeout(loiPollTimer);

  const file = document.getElementById('loiFile').files[0];
  if (!file) return;

  const fd = new FormData();
  fd.append('file', file);
  const competitorFile = document.getElementById('competitorFile').files[0];
  if (competitorFile) fd.append('competitor_file', competitorFile);
  const benchPursuit = document.getElementById('benchPursuit').value;
  if (benchPursuit) fd.append('bench_pursuit', benchPursuit);
  fd.append('client', document.getElementById('client').value);
  fd.append('rfp', document.getElementById('rfpOverride').value);
  fd.append('item', document.getElementById('itemOverride').value);
  fd.append('max_pages', document.getElementById('maxPages').value);

  const submitBtn = document.getElementById('loiSubmit');
  submitBtn.disabled = true;
  document.getElementById('loiResults').innerHTML = '';
  document.getElementById('loiLog').style.display = 'block';
  document.getElementById('loiLog').textContent = '';
  document.getElementById('loiStatus').textContent = 'Starting...';

  let res;
  try {
    res = await fetch('/api/run', { method: 'POST', body: fd });
  } catch (err) {
    document.getElementById('loiStatus').textContent = "Can't reach the server.";
    submitBtn.disabled = false;
    return;
  }
  if (!res.ok) {
    document.getElementById('loiStatus').textContent = await res.text();
    submitBtn.disabled = false;
    return;
  }
  const { job_id } = await res.json();
  pollJob(job_id);
});

async function pollJob(jobId) {
  const res = await fetch('/api/job?id=' + jobId);
  const job = await res.json();
  document.getElementById('loiLog').textContent = job.log.join('\\n');
  document.getElementById('loiLog').scrollTop = 1e9;

  if (job.state === 'running') {
    document.getElementById('loiStatus').textContent = 'Working - this can take a couple minutes...';
    loiPollTimer = setTimeout(() => pollJob(jobId), 2000);
    return;
  }
  document.getElementById('loiSubmit').disabled = false;
  document.getElementById('loiStatus').textContent =
    job.state === 'done' ? 'Done.' : ('Stopped: ' + job.error);
  renderLoiResults(job);
}

function renderLoiResults(job) {
  const box = document.getElementById('loiResults');
  let out = '';
  if (job.mistake_check) {
    out += `<div class="card"><h3>Mistake check</h3><pre>${esc(job.mistake_check)}</pre></div>`;
  }
  for (const r of job.reports) {
    out += `<div class="card">`;
    if (r.docx_url) out += `<p><a href="${r.docx_url}">Download as Word doc</a></p>`;
    out += r.html + `</div>`;
  }
  box.innerHTML = out;
}
</script>
</body>
</html>"""


# --- LOI Tools: runs src.review (mistake check + comparison) in a
# background thread per request, so the page can poll for progress instead
# of the browser just hanging for the minute or two an AI comparison takes.

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def _parse_multipart(body: bytes, content_type: str) -> dict:
    """Minimal multipart/form-data reader (Python removed the cgi module
    that used to do this). Returns {field: "text"} for form fields and
    {field: (filename, bytes)} for the uploaded file."""
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type)
    if not m:
        return {}
    boundary = (m.group(1) or m.group(2)).encode()
    fields = {}
    for part in body.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, _, content = part.partition(b"\r\n\r\n")
        headers = header_blob.decode("utf-8", "replace")
        name_m = re.search(r'name="([^"]+)"', headers)
        if not name_m:
            continue
        content = content.rstrip(b"\r\n")
        file_m = re.search(r'filename="([^"]*)"', headers)
        fields[name_m.group(1)] = (
            (file_m.group(1), content) if file_m else content.decode("utf-8", "replace")
        )
    return fields


class _JobLog(io.TextIOBase):
    """A fake stdout that appends every print() from review.review() to a
    job's log, so the web page can show progress while it runs."""

    def __init__(self, job_id):
        self.job_id = job_id

    def write(self, s):
        if s.strip():
            with JOBS_LOCK:
                JOBS[self.job_id]["log"].append(s.rstrip("\n"))
        return len(s)


def _run_job(job_id, pursuit, against, vs_path, client, rfp, item, max_pages, competitor_path=None):
    out_dir = compare.out_dir_for(pursuit)
    with JOBS_LOCK:
        JOBS[job_id]["out_dir"] = str(out_dir)

    # A pursuit that's been reviewed before already has files sitting in
    # out_dir. Snapshot them so a failed/partial run doesn't show a past
    # run's leftovers as if this job produced them.
    before = {p.name: p.stat().st_mtime for p in out_dir.glob("*")} if out_dir.exists() else {}

    error = None
    try:
        with contextlib.redirect_stdout(_JobLog(job_id)):
            review.review(pursuit, against, vs_path, client, rfp, item, max_pages, competitor_path)
    except SystemExit as exc:
        error = str(exc.code) if exc.code else "Failed - see log."
    except compare.anthropic.AuthenticationError:
        # A key IS set, but Anthropic rejected it - wrong/revoked/typo'd.
        error = "The Anthropic API key on this server is invalid - check it was typed correctly."
    except TypeError as exc:
        # No key found in the environment at all.
        error = ("No Anthropic API key set on this server yet."
                  if "auth" in str(exc).lower() else f"Unexpected error: {exc}")
    except Exception as exc:  # keep whatever partial results exist either way
        error = f"Unexpected error: {exc}"

    # Only report files this run actually wrote or overwrote (e.g. the
    # mistake check, which always runs first) - the comparison needing an
    # API key doesn't mean the mistake check was wasted work, but an old
    # report from a previous run shouldn't be shown as this run's output.
    files = sorted(
        p.name for p in (out_dir.glob("*") if out_dir.exists() else [])
        if p.name not in before or p.stat().st_mtime > before[p.name]
    )
    reports = []
    for name in files:
        if name.endswith(".md"):
            md_text = (out_dir / name).read_text(encoding="utf-8")
            docx_name = name[:-3] + ".docx"
            reports.append({
                "title": name[:-3],
                "html": compare.markdown_to_html(md_text),
                "docx": docx_name if (out_dir / docx_name).exists() else None,
            })
    mistake_check = None
    if (out_dir / "mistake-check.txt").exists():
        mistake_check = (out_dir / "mistake-check.txt").read_text(encoding="utf-8")

    with JOBS_LOCK:
        JOBS[job_id].update(
            state="error" if error else "done",
            error=error,
            files=files,
            reports=reports,
            mistake_check=mistake_check,
        )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif url.path == "/api/search":
            terms = parse_qs(url.query).get("q", [""])[0].split()
            results = search_index(terms) if terms else []
            payload = [
                {k: e[k] for k in ("title", "tags", "people", "file", "modified")}
                for _, e in results
            ]
            self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
        elif url.path == "/api/resumes":
            if not RESUMES_INDEX.exists():
                self._send(200, b"No resume index yet - run Update Index.bat on the host PC.", "text/plain")
                return
            terms = parse_qs(url.query).get("q", [""])[0].split()
            results = search_resumes(terms) if terms else []
            self._send(200, json.dumps(results).encode("utf-8"), "application/json")
        elif url.path == "/api/open":
            path = parse_qs(url.query).get("path", [""])[0]
            if path not in self._known_files():
                self._send(403, b"unknown file", "text/plain")
            elif not self._from_host():
                # Explorer would open on this machine's screen, not theirs, so
                # don't - just tell the page so it can fall back.
                self._send(200, json.dumps({"opened": False}).encode("utf-8"),
                           "application/json")
            else:
                # Show the file in Explorer rather than opening it in Word —
                # the source docs must never be edited.
                subprocess.Popen(["explorer", "/select,", path])
                self._send(200, json.dumps({"opened": True}).encode("utf-8"),
                           "application/json")
        elif url.path == "/api/winners":
            self._send(200, json.dumps(compare.winners_by_discipline()).encode("utf-8"),
                       "application/json")
        elif url.path == "/api/job":
            job_id = parse_qs(url.query).get("id", [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if not job:
                    self._send(404, b'{"error": "unknown job"}', "application/json")
                    return
                payload = {
                    "state": job["state"],
                    "error": job["error"],
                    "log": job["log"][-40:],  # just the recent tail keeps polling light
                    "mistake_check": job["mistake_check"],
                    "reports": [
                        {"title": r["title"], "html": r["html"],
                         "docx_url": f"/api/file?job={job_id}&name={r['docx']}" if r["docx"] else None}
                        for r in job["reports"]
                    ],
                }
            self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
        elif url.path == "/api/file":
            q = parse_qs(url.query)
            job_id, name = q.get("job", [""])[0], q.get("name", [""])[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            # name must be one this job actually produced - blocks path tricks.
            if not job or not job["out_dir"] or name not in job["files"]:
                self._send(404, b"not found", "text/plain")
                return
            path = Path(job["out_dir"]) / name
            body = path.read_bytes()
            content_type = {
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".txt": "text/plain; charset=utf-8",
                ".md": "text/markdown; charset=utf-8",
            }.get(path.suffix.lower(), "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/run":
            self._send(404, b"not found", "text/plain")
            return

        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD_BYTES:
            self._send(413, b"File too large.", "text/plain")
            return
        fields = _parse_multipart(self.rfile.read(length), self.headers.get("Content-Type", ""))

        upload = fields.get("file")
        if not isinstance(upload, tuple) or not upload[0]:
            self._send(400, b"Choose an LOI PDF.", "text/plain")
            return
        filename, content = upload
        if not filename.lower().endswith(".pdf"):
            self._send(400, b"Only PDF files are supported.", "text/plain")
            return

        rfp_override = fields.get("rfp") or None
        item_override = fields.get("item") or None
        guessed_rfp, guessed_item = check.expected_from_filename(filename)
        rfp, item = rfp_override or guessed_rfp, item_override or guessed_item

        bench_pursuit = fields.get("bench_pursuit") or None
        if bench_pursuit:
            # Comparing against a winner in a different discipline pursuit -
            # the mistake checker still uses the file's own real RFP/item
            # (guessed above, or the override fields), just the comparison
            # benchmark is different.
            pursuit, against = bench_pursuit, "1"
        else:
            if not rfp or not item:
                self._send(400, (
                    "Couldn't tell the RFP/item number from that filename. Rename "
                    'it to include both (e.g. "RFP 2605 Item 5 LOI.pdf"), or pick '
                    "a discipline to compare against below."
                ).encode("utf-8"), "text/plain")
                return
            pursuit, against = f"{rfp} Item {item}", "all"

        job_id = uuid.uuid4().hex
        # Keep the real filename (spaces and all) - the mistake checker just
        # guessed the RFP/item number from it, and that only works with the
        # actual, unmangled name. Path(...).name strips any "../" or "C:\"
        # tricks in a forged filename; the per-job folder (not the name) is
        # what avoids collisions between different uploads.
        upload_dir = UPLOADS_DIR / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        vs_path = str(upload_dir / Path(filename).name)
        Path(vs_path).write_bytes(content)

        competitor_path = None
        comp_upload = fields.get("competitor_file")
        if isinstance(comp_upload, tuple) and comp_upload[0]:
            comp_filename, comp_content = comp_upload
            if not comp_filename.lower().endswith(".pdf"):
                self._send(400, b"Competitor LOI must be a PDF.", "text/plain")
                return
            competitor_path = str(upload_dir / Path(comp_filename).name)
            Path(competitor_path).write_bytes(comp_content)

        max_pages_raw = fields.get("max_pages", "")
        max_pages = int(max_pages_raw) if max_pages_raw.strip().isdigit() else None

        with JOBS_LOCK:
            JOBS[job_id] = {"state": "running", "log": [], "error": None,
                            "out_dir": None, "files": [], "reports": [],
                            "mistake_check": None}
        threading.Thread(
            target=_run_job,
            args=(job_id, pursuit, against, vs_path, fields.get("client") or "INDOT",
                  rfp_override, item_override, max_pages, competitor_path),
            daemon=True,
        ).start()
        self._send(200, json.dumps({"job_id": job_id}).encode("utf-8"), "application/json")

    def _from_host(self) -> bool:
        """Is this request coming from the machine running the server?

        Only then is opening Explorer any use - the window appears on this
        screen. The page used to decide this from location.hostname, which got
        it wrong for the most common case: someone sitting at the host PC who
        browsed to the http://<ip> address printed in the black window instead
        of localhost. They'd be told to paste a path while the server sat there
        able to open the folder for them. The server knows who's asking, so let
        it answer. It also stops a coworker popping Explorer windows on the
        host's screen from across the office.
        """
        client = self.client_address[0]
        if client in ("127.0.0.1", "::1"):
            return True
        own = set()
        with contextlib.suppress(OSError):
            own.add(lan_ip())
        with contextlib.suppress(OSError):
            own.update(socket.gethostbyname_ex(socket.gethostname())[2])
        return client in own

    @classmethod
    def _known_files(cls):
        if not hasattr(cls, "_files"):
            cls._files = set()
            for index in (PROJECTS_INDEX, RESUMES_INDEX):
                if index.exists():
                    entries = json.loads(index.read_text(encoding="utf-8"))
                    cls._files.update(e["file"] for e in entries)
        return cls._files

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the console quiet
        pass


def lan_ip() -> str:
    """This machine's LAN address — what coworkers put in their browser."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no traffic sent; just picks the interface
            return s.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def main() -> int:
    if not PROJECTS_INDEX.exists():
        sys.exit("No index yet — run:  py -m src.profiles index <profiles_folder>")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Search running.  This PC:      http://127.0.0.1:{PORT}")
    print(f"                 Coworkers:    http://{lan_ip()}:{PORT}")
    print("Ctrl+C to stop.")
    threading.Timer(0.5, webbrowser.open, args=[f"http://127.0.0.1:{PORT}"]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
