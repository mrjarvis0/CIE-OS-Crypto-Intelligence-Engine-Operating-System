"""Live A01 Agent dashboard — scans the codebase and serves real-time stats."""

import ast
import http.server
import json
import os
import socketserver
import threading
import time
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
PORT = 8501
REFRESH_INTERVAL = 15


def _index_module(raw, rel, class_index, hooks):
    """
    Record the classes a file declares and the hooks that raise.

    Parsed rather than grepped. A file containing ``raise NotImplementedError``
    is usually an abstract base whose concrete subclass sits two files away --
    counting those as holes reported this codebase as far less finished than it
    is, and dragged the AI-layer phase estimate down with it. What matters is
    whether anything *overrides* the hook, which needs the class graph.
    """
    try:
        tree = ast.parse(raw.decode("utf-8", errors="replace"))
    except SyntaxError:
        return

    is_test = "/tests/" in rel or rel.rsplit("/", 1)[-1].startswith("test_")

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        bases = [
            b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
            for b in node.bases
        ]
        methods = {
            n.name
            for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        class_index.setdefault(node.name, []).append((bases, methods))

        if is_test:
            # A stub in a test is deliberate -- it exists so the base class's
            # declining path can be exercised, and is never called.
            continue

        for fn in node.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for stmt in ast.walk(fn):
                if not isinstance(stmt, ast.Raise):
                    continue
                exc = stmt.exc
                name = getattr(exc, "id", None) or getattr(
                    getattr(exc, "func", None), "id", None
                )
                if name == "NotImplementedError":
                    hooks.append((rel, node.name, fn.name))
                    break


def _unimplemented(class_index, hooks):
    """
    Hooks with no concrete override anywhere in the codebase.

    Subclasses are followed transitively, so an adapter three levels below its
    base still counts as implementing it.
    """
    children = {}
    for name, entries in class_index.items():
        for bases, _ in entries:
            for base in bases:
                children.setdefault(base, set()).add(name)

    def overridden(root, method):
        seen, queue = set(), list(children.get(root, ()))
        while queue:
            name = queue.pop()
            if name in seen:
                continue
            seen.add(name)
            for _, methods in class_index.get(name, ()):
                if method in methods:
                    return True
            queue.extend(children.get(name, ()))
        return False

    return sorted(
        f"{rel}::{cls}.{method}"
        for rel, cls, method in hooks
        if not overridden(cls, method)
    )


def scan_codebase():
    modules = {}
    empty_modules = []
    class_index = {}
    hooks = []
    total_py_lines = 0
    total_py_files = 0
    total_files = 0
    test_lines = 0
    doc_config_lines = 0
    doc_exts = {".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini", ".example"}

    for child in sorted(AGENT_ROOT.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name == "__pycache__":
            continue

        mod_files = 0
        mod_lines = 0

        for root, dirs, files in os.walk(child):
            dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
            for f in files:
                fp = Path(root) / f
                total_files += 1

                if fp.suffix == ".py":
                    total_py_files += 1
                    try:
                        raw = fp.read_bytes()
                        line_count = raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
                    except Exception:
                        line_count = 0
                        raw = b""

                    total_py_lines += line_count
                    mod_files += 1
                    mod_lines += line_count

                    if "tests" in fp.parts or fp.name.startswith("test_"):
                        test_lines += line_count

                    if raw:
                        rel = str(fp.relative_to(AGENT_ROOT)).replace("\\", "/")
                        _index_module(raw, rel, class_index, hooks)

                elif fp.suffix in doc_exts:
                    try:
                        raw = fp.read_bytes()
                        doc_config_lines += raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
                    except Exception:
                        pass

        modules[child.name] = {"files": mod_files, "lines": mod_lines}
        if mod_files == 0:
            empty_modules.append(child.name)

    not_implemented_files = _unimplemented(class_index, hooks)

    top_modules = sorted(modules.items(), key=lambda x: x[1]["lines"], reverse=True)[:15]

    phase_status = estimate_phases(modules, empty_modules, not_implemented_files)

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_py_lines": total_py_lines,
        "total_py_files": total_py_files,
        "total_files": total_files,
        "test_lines": test_lines,
        "doc_config_lines": doc_config_lines,
        "grand_total": total_py_lines + doc_config_lines,
        "top_modules": [{"name": n, "files": d["files"], "lines": d["lines"]} for n, d in top_modules],
        "all_modules": [{"name": n, "files": d["files"], "lines": d["lines"]} for n, d in sorted(modules.items())],
        "empty_modules": empty_modules,
        "not_implemented_files": not_implemented_files,
        "not_implemented_count": len(not_implemented_files),
        "phases": phase_status,
    }


def estimate_phases(modules, empty_modules, ni_files):
    def has_code(name):
        return modules.get(name, {}).get("files", 0) > 0

    def pct(name):
        m = modules.get(name, {})
        return min(100, m.get("lines", 0) // 10) if m.get("files", 0) > 0 else 0

    identity_done = has_code("identity") or (AGENT_ROOT / "identity" / "mission.md").exists()
    p0 = 100 if identity_done else 0

    infra_modules = ["config", "core", "telemetry"]
    p1 = min(100, sum(1 for m in infra_modules if has_code(m)) * 34)

    p2 = min(100, pct("sensors")) if has_code("sensors") else 0
    p3 = min(100, pct("ingestion")) if has_code("ingestion") else 0
    p4 = min(100, pct("normalization")) if has_code("normalization") else 0
    p5 = min(100, pct("database")) if has_code("database") else 0

    skills_m = modules.get("skills", {})
    p6 = min(100, (skills_m.get("files", 0) * 7)) if has_code("skills") else 0

    p7 = min(100, pct("intelligence")) if has_code("intelligence") else 0
    p8 = min(100, pct("decision")) if has_code("decision") else 0
    p9 = min(100, pct("interfaces")) if has_code("interfaces") else 0

    ai_files = [f for f in ni_files if "tools/ai/" in f]
    ai_mod = modules.get("tools", {})
    p10 = max(5, 100 - len(ai_files) * 12) if ai_mod.get("files", 0) > 0 else 0

    test_mod = modules.get("tests", {})
    eval_mod = modules.get("evaluation", {})
    p11 = min(100, ((test_mod.get("lines", 0) + eval_mod.get("lines", 0)) // 50))

    p12 = 0
    p13 = 5 if not empty_modules else 0

    return [
        {"name": "P0 Foundation", "pct": p0},
        {"name": "P1 Infrastructure", "pct": p1},
        {"name": "P2 Sensors", "pct": p2},
        {"name": "P3 Ingestion", "pct": p3},
        {"name": "P4 Normalization", "pct": p4},
        {"name": "P5 Database", "pct": p5},
        {"name": "P6 Skills", "pct": p6},
        {"name": "P7 Intelligence", "pct": p7},
        {"name": "P8 Decision", "pct": p8},
        {"name": "P9 Interfaces", "pct": p9},
        {"name": "P10 AI layer", "pct": p10},
        {"name": "P11 Testing", "pct": p11},
        {"name": "P12 Optimization", "pct": p12},
        {"name": "P13 Production", "pct": p13},
    ]


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A01 Agent — Live Dashboard</title>
<style>
  :root {
    --bg: #fcfcfb; --bg1: #f5f5f3; --bg2: #fff;
    --text: #0b0b0b; --text2: #52514e; --text3: #898781;
    --border: rgba(11,11,11,0.10); --radius: 8px;
    --green: #0ca30c; --blue: #2a78d6; --amber: #fab219; --red: #d03b3b;
    --bg-danger: #FCEBEB; --text-danger: #A32D2D;
    --bg-warning: #FAEEDA; --text-warning: #854F0B;
    --bg-success: #EAF3DE; --text-success: #3B6D11;
  }
  @media(prefers-color-scheme:dark){:root{
    --bg: #1a1a19; --bg1: #222221; --bg2: #2a2a28;
    --text: #f0efec; --text2: #c3c2b7; --text3: #898781;
    --border: rgba(255,255,255,0.10);
    --bg-danger: #501313; --text-danger: #F09595;
    --bg-warning: #412402; --text-warning: #FAC775;
    --bg-success: #173404; --text-success: #97C459;
  }}
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--text); padding: 2rem; max-width: 860px; margin: 0 auto; }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; }
  .header h1 { font-size:22px; font-weight:500; }
  .live-dot { width:8px; height:8px; border-radius:50%; background:var(--green); display:inline-block;
              animation: pulse 2s infinite; margin-right:6px; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  .live-label { font-size:13px; color:var(--text2); display:flex; align-items:center; }
  .stat-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px,1fr)); gap:12px; margin-bottom:1.5rem; }
  .stat { background:var(--bg1); border-radius:var(--radius); padding:1rem; }
  .stat .label { font-size:13px; color:var(--text2); margin-bottom:4px; }
  .stat .value { font-size:26px; font-weight:500; font-variant-numeric:tabular-nums; }
  .section-title { font-size:18px; font-weight:500; margin:1.5rem 0 0.75rem; }
  .phase-bar { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
  .phase-bar .name { font-size:12px; color:var(--text2); min-width:140px; }
  .phase-bar .track { flex:1; height:20px; background:var(--bg1); border-radius:4px; overflow:hidden; border:0.5px solid var(--border); }
  .phase-bar .fill { height:100%; border-radius:4px; transition: width 0.6s ease; }
  .phase-bar .pct { font-size:12px; font-weight:500; min-width:40px; text-align:right; }
  .module-row { display:flex; align-items:center; gap:8px; margin-bottom:4px; }
  .module-row .mname { font-size:13px; min-width:120px; color:var(--text2); }
  .module-row .mbar { flex:1; height:14px; background:var(--bg1); border-radius:3px; overflow:hidden; }
  .module-row .mfill { height:100%; background:var(--blue); border-radius:3px; transition:width 0.6s ease; }
  .module-row .mval { font-size:12px; color:var(--text3); min-width:60px; text-align:right; font-variant-numeric:tabular-nums; }
  .pills { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:1rem; }
  .pill { font-size:12px; padding:4px 12px; border-radius:var(--radius); }
  .pill-danger { background:var(--bg-danger); color:var(--text-danger); }
  .pill-warning { background:var(--bg-warning); color:var(--text-warning); }
  .ni-list { font-size:12px; color:var(--text3); line-height:1.8; max-height:200px; overflow-y:auto; }
  .ni-list code { background:var(--bg1); padding:2px 6px; border-radius:3px; font-size:11px; }
  .footer { margin-top:2rem; font-size:12px; color:var(--text3); text-align:center; border-top:0.5px solid var(--border); padding-top:1rem; }
  .overall-pct { font-size:48px; font-weight:500; font-variant-numeric:tabular-nums; }
  .overall-label { font-size:14px; color:var(--text2); }
  .loading { text-align:center; padding:3rem; color:var(--text3); }
  .loading .spinner { width:32px; height:32px; border:3px solid var(--bg1); border-top-color:var(--blue);
                      border-radius:50%; animation:spin 0.8s linear infinite; margin:0 auto 1rem; }
  @keyframes spin { to { transform:rotate(360deg); } }
</style>
</head>
<body>

<div class="header">
  <div>
    <p style="font-size:13px; color:var(--text2);">CIE-OS / Agent A01</p>
    <h1>Blockchain Intelligence Agent</h1>
  </div>
  <div class="live-label"><span class="live-dot"></span>Live</div>
</div>

<div id="app">
  <div class="loading">
    <div class="spinner"></div>
    <p>Scanning codebase...</p>
  </div>
</div>

<div class="footer">A01 Live Dashboard &mdash; auto-refreshes every 15 seconds</div>

<script>
function fmt(n) { return n.toLocaleString(); }

function pctColor(p) {
  if (p >= 90) return 'var(--green)';
  if (p >= 40) return 'var(--blue)';
  if (p >= 15) return 'var(--amber)';
  return 'var(--red)';
}

function render(d) {
  var overallPhases = d.phases;
  var avgPct = Math.round(overallPhases.reduce(function(s,p){ return s + p.pct; }, 0) / overallPhases.length);
  var maxLines = d.top_modules.length ? d.top_modules[0].lines : 1;

  var html = '';

  html += '<div class="stat-grid">';
  html += '<div class="stat" style="grid-column:span 2;text-align:center;">';
  html += '<div class="overall-label">Overall progress</div>';
  html += '<div class="overall-pct" style="color:' + pctColor(avgPct) + '">' + avgPct + '%</div>';
  html += '</div>';
  html += '<div class="stat"><div class="label">Python lines</div><div class="value">' + fmt(d.total_py_lines) + '</div></div>';
  html += '<div class="stat"><div class="label">Python files</div><div class="value">' + fmt(d.total_py_files) + '</div></div>';
  html += '<div class="stat"><div class="label">Total files</div><div class="value">' + fmt(d.total_files) + '</div></div>';
  html += '<div class="stat"><div class="label">Test lines</div><div class="value">' + fmt(d.test_lines) + '</div></div>';
  html += '<div class="stat"><div class="label">Docs/config lines</div><div class="value">' + fmt(d.doc_config_lines) + '</div></div>';
  html += '<div class="stat"><div class="label">Grand total</div><div class="value">' + fmt(d.grand_total) + '</div></div>';
  html += '</div>';

  html += '<div class="section-title">Roadmap phases (0–13)</div>';
  for (var i = 0; i < d.phases.length; i++) {
    var p = d.phases[i];
    var c = pctColor(p.pct);
    var w = Math.max(p.pct, 1);
    html += '<div class="phase-bar">';
    html += '<span class="name">' + p.name + '</span>';
    html += '<div class="track"><div class="fill" style="width:' + w + '%;background:' + c + ';"></div></div>';
    html += '<span class="pct" style="color:' + c + '">' + p.pct + '%</span>';
    html += '</div>';
  }

  html += '<div class="section-title">Top modules by lines of code</div>';
  for (var j = 0; j < d.top_modules.length; j++) {
    var m = d.top_modules[j];
    var bw = Math.max((m.lines / maxLines) * 100, 1);
    html += '<div class="module-row">';
    html += '<span class="mname">' + m.name + '</span>';
    html += '<div class="mbar"><div class="mfill" style="width:' + bw + '%"></div></div>';
    html += '<span class="mval">' + fmt(m.lines) + ' / ' + m.files + 'f</span>';
    html += '</div>';
  }

  if (d.empty_modules.length) {
    html += '<div class="section-title">Empty modules (' + d.empty_modules.length + ')</div><div class="pills">';
    for (var k = 0; k < d.empty_modules.length; k++) {
      html += '<span class="pill pill-danger">' + d.empty_modules[k] + '</span>';
    }
    html += '</div>';
  }

  html += '<div class="section-title">Unimplemented hooks (' + d.not_implemented_count + ')</div>';
  html += '<div class="ni-list">';
  for (var n = 0; n < d.not_implemented_files.length; n++) {
    html += '<code>' + d.not_implemented_files[n] + '</code> ';
  }
  html += '</div>';

  html += '<p style="margin-top:1rem;font-size:12px;color:var(--text3);">Last scan: ' + d.timestamp + '</p>';

  document.getElementById('app').innerHTML = html;
}

function refresh() {
  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/api/stats', true);
  xhr.timeout = 30000;
  xhr.onload = function() {
    if (xhr.status === 200) {
      try { render(JSON.parse(xhr.responseText)); } catch(e) { console.error(e); }
    }
  };
  xhr.onerror = function() { console.error('fetch failed'); };
  xhr.send();
}

refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>
"""


_lock = threading.Lock()
_cached = {"data": None, "ts": 0}


def bg_scan():
    while True:
        try:
            data = scan_codebase()
            with _lock:
                _cached["data"] = data
                _cached["ts"] = time.time()
        except Exception as e:
            print(f"Scan error: {e}")
        time.sleep(REFRESH_INTERVAL)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/stats":
            with _lock:
                data = _cached["data"]
            if data is None:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"scanning"}')
                return
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/", "/index.html"):
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass


class ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def main():
    print(f"A01 Live Dashboard")
    print(f"Agent root: {AGENT_ROOT}")
    print(f"Starting background scan thread...")

    t = threading.Thread(target=bg_scan, daemon=True)
    t.start()

    print(f"Server starting on http://localhost:{PORT}")
    with ReuseTCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
