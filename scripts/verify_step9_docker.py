#!/usr/bin/env python3
"""Step 9 acceptance test: Docker deployment configuration — STATIC only.

The sandbox has no Docker daemon and no browser (standing user instruction:
no docker-compose up, no headless Chromium). Everything a broken Docker
setup could silently get wrong is therefore checked by PARSING the
configuration and cross-referencing every contract between the files:

  docker-compose.yml      services/ports/healthcheck/build wiring
  docker/backend.Dockerfile   multi-stage: builder venv -> slim runtime
  docker/frontend.Dockerfile  multi-stage: node syntax gate -> nginx
  docker/nginx.conf       static + /api + /ws proxy contracts
  backend/app/main.py     the routes the proxy targets must exist
  backend/requirements.txt    the pins the builder must install
  frontend/               the files index.html references must exist
  .dockerignore           context hygiene

Usage:  python scripts/verify_step9_docker.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # /home/z/my-project
PWEB = ROOT / "pyramid-web"

passed = 0
failed: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        failed.append(name)
        print(f"FAIL  {name}  {extra}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def dockerfile_instructions(text: str) -> list[tuple[str, str]]:
    """Parse a Dockerfile into (instruction, args) logical lines.

    Handles backslash-continuations, line comments and heredoc-free syntax
    (neither Dockerfile here uses heredocs).
    """
    logical: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if line.rstrip().endswith("\\"):
            buf += line.rstrip().rstrip("\\") + " "
            continue
        buf += line
        if buf.strip():
            logical.append(" ".join(buf.split()))
        buf = ""
    if buf.strip():
        logical.append(" ".join(buf.split()))

    out: list[tuple[str, str]] = []
    for inst in logical:
        parts = inst.split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[A-Z]+", parts[0]):
            out.append((parts[0], parts[1]))
    return out


def nginx_directives(text: str) -> list[str]:
    """Return every semicolon-terminated directive (comments stripped)."""
    no_comments = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
    return [d.strip().replace("\n", " ") for d in no_comments.split(";") if d.strip()]


def nginx_braces_balanced(text: str) -> bool:
    no_comments = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
    depth = 0
    for ch in no_comments:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def no_comments_nginx(text: str) -> str:
    return re.sub(r"#.*$", "", text, flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# A. files exist
# ---------------------------------------------------------------------------


def check_files() -> None:
    print("== A. files exist ==")
    for rel in (
        "docker-compose.yml",
        "docker/backend.Dockerfile",
        "docker/frontend.Dockerfile",
        "docker/nginx.conf",
        ".dockerignore",
        "README.md",
    ):
        p = PWEB / rel
        check(f"{rel} exists and is non-empty", p.is_file() and p.stat().st_size > 0)


# ---------------------------------------------------------------------------
# B. docker-compose.yml
# ---------------------------------------------------------------------------


def check_compose() -> None:
    print("== B. docker-compose.yml ==")
    import yaml

    raw = (PWEB / "docker-compose.yml").read_text()
    doc = yaml.safe_load(raw)
    check("YAML parses to a dict", isinstance(doc, dict))
    check("compose project name set", doc.get("name") == "pyramid-web")

    services = doc.get("services", {})
    check("exactly the two services backend+frontend", set(services) == {"backend", "frontend"})

    be, fe = services.get("backend", {}), services.get("frontend", {})
    check(
        "backend build context '.' + docker/backend.Dockerfile",
        be.get("build", {}).get("context") == "."
        and be.get("build", {}).get("dockerfile") == "docker/backend.Dockerfile",
    )
    check(
        "frontend build context '.' + docker/frontend.Dockerfile",
        fe.get("build", {}).get("context") == "."
        and fe.get("build", {}).get("dockerfile") == "docker/frontend.Dockerfile",
    )
    check("build contexts' dockerfiles exist on disk",
          (PWEB / be.get("build", {}).get("dockerfile", "")).is_file()
          and (PWEB / fe.get("build", {}).get("dockerfile", "")).is_file())

    check("backend port mapping 8000:8000", "8000:8000" in be.get("ports", []))
    check("frontend port mapping 8080:80", "8080:80" in fe.get("ports", []))

    hc = " ".join(str(x) for x in be.get("healthcheck", {}).get("test", []))
    check("backend healthcheck hits /api/health", "/api/health" in hc)
    check("backend healthcheck has interval+retries+start_period",
          {"interval", "retries", "start_period"} <= set(be.get("healthcheck", {})))

    dep = fe.get("depends_on", {}).get("backend", {})
    check("frontend waits for backend service_healthy",
          isinstance(dep, dict) and dep.get("condition") == "service_healthy")
    check("restart policy unless-stopped on both services",
          be.get("restart") == "unless-stopped" and fe.get("restart") == "unless-stopped")


# ---------------------------------------------------------------------------
# C. backend.Dockerfile (multi-stage)
# ---------------------------------------------------------------------------


def check_backend_dockerfile() -> None:
    print("== C. docker/backend.Dockerfile ==")
    text = (PWEB / "docker/backend.Dockerfile").read_text()
    inst = dockerfile_instructions(text)
    froms = [args for name, args in inst if name == "FROM"]
    check("multi-stage: exactly two FROM stages", len(froms) == 2, str(froms))
    check("builder stage is python:3.12-slim AS builder",
          len(froms) >= 1 and "python:3.12-slim" in froms[0] and "AS builder" in froms[0])
    check("runtime stage is python:3.12-slim",
          len(froms) >= 2 and "python:3.12-slim" in froms[1])

    args_all = " ".join(a for _, a in inst)
    copy_from = [a for name, a in inst if name == "COPY" and a.startswith("--from=")]
    check("runtime copies the built venv from the builder stage",
          any(a.startswith("--from=builder") and "/opt/venv" in a for a in copy_from))

    req_idx = next((i for i, (n, a) in enumerate(inst) if n == "COPY" and "requirements.txt" in a), -1)
    pip_idx = next((i for i, (n, a) in enumerate(inst) if n == "RUN" and "pip install" in a), -1)
    app_idx = next((i for i, (n, a) in enumerate(inst) if n == "COPY" and "backend/app" in a), -1)
    check("requirements.txt copied before pip install (layer caching)",
          0 <= req_idx < pip_idx)
    check("app code copied AFTER the pip layer (code edits don't bust the dep cache)",
          pip_idx != -1 and app_idx > pip_idx)

    envs = " ".join(a for name, a in inst if name == "ENV")
    check("PYTHONHASHSEED=0 (seeded racks reproducible across processes)",
          "PYTHONHASHSEED=0" in envs)
    check("venv on PATH in the runtime image", 'PATH="/opt/venv/bin:$PATH"' in envs)
    check("libgomp1 installed (numba OpenMP layer)", "libgomp1" in args_all)
    check("runs as non-root USER", any(name == "USER" for name, _ in inst))
    check("backend/pooltool vendored into the image",
          any(name == "COPY" and "backend/pooltool" in a for name, a in inst))
    check("single-container UI: frontend copied into the image",
          any(name == "COPY" and "frontend ./static" in a for name, a in inst))
    check("PYRAMID_STATIC_DIR points at the copied UI tree",
          "PYRAMID_STATIC_DIR=/app/static" in envs)

    cmds = [a for name, a in inst if name == "CMD"]
    check("single CMD, uvicorn without --reload",
          len(cmds) == 1 and "uvicorn" in cmds[0] and "--reload" not in cmds[0])
    check("CMD has no --workers flag (single worker: in-memory lobby + numba)",
          len(cmds) == 1 and "--workers" not in cmds[0])
    check("CMD binds 0.0.0.0 with ${PORT:-8000} (render.com $PORT; compose default 8000)",
          len(cmds) == 1 and "--host" in cmds[0] and "0.0.0.0" in cmds[0]
          and "PORT:-8000" in cmds[0])
    check("EXPOSE 8000", any(name == "EXPOSE" and "8000" in a for name, a in inst))

    # the pip install inside the builder must reference the copied requirements
    pip_args = next((a for name, a in inst if name == "RUN" and "pip install" in a), "")
    check("pip install -r requirements.txt", "requirements.txt" in pip_args)


# ---------------------------------------------------------------------------
# D. frontend.Dockerfile (multi-stage)
# ---------------------------------------------------------------------------


def check_frontend_dockerfile() -> None:
    print("== D. docker/frontend.Dockerfile ==")
    text = (PWEB / "docker/frontend.Dockerfile").read_text()
    inst = dockerfile_instructions(text)
    froms = [args for name, args in inst if name == "FROM"]
    check("multi-stage: exactly two FROM stages", len(froms) == 2, str(froms))
    check("stage 1 is a node image AS build", "node" in froms[0] and "AS build" in froms[0])
    check("stage 2 is nginx:1.27-alpine", "nginx:1.27-alpine" in froms[1])

    runs = [a for name, a in inst if name == "RUN"]
    gate = " ".join(runs)
    check("node --check gate covers main.js", "node --check frontend/main.js" in gate)
    check("node --check gate covers lobby.js", "node --check frontend/lobby.js" in gate)
    check("node --check gate covers ui_math.js", "node --check frontend/ui_math.js" in gate)

    copy_from = [a for name, a in inst if name == "COPY" and a.startswith("--from=")]
    check("nginx copies the validated frontend from the build stage",
          any(a.startswith("--from=build") and "/usr/share/nginx/html" in a for a in copy_from))
    check("nginx.conf mounted as default.conf",
          any(name == "COPY" and "docker/nginx.conf" in a and "default.conf" in a
              for name, a in inst))
    check("EXPOSE 80", any(name == "EXPOSE" and "80" in a for name, a in inst))

    # run the same syntax gate locally — the image build must not be able to
    # succeed where the local suite fails
    ok = True
    for js in ("main.js", "lobby.js", "ui_math.js"):
        proc = subprocess.run(
            ["node", "--check", str(PWEB / "frontend" / js)],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            ok = False
            print(f"    ({js}: {proc.stdout + proc.stderr})")
    check("local node --check passes on all three JS files", ok)


# ---------------------------------------------------------------------------
# E. nginx.conf
# ---------------------------------------------------------------------------


def check_nginx() -> None:
    print("== E. docker/nginx.conf ==")
    text = (PWEB / "docker/nginx.conf").read_text()
    check("braces balanced", nginx_braces_balanced(text))

    directives = nginx_directives(text)
    joined = "\n".join(directives)

    # a directive line may share its ';' chunk with the enclosing block opener
    # (e.g. "server {\n    listen 80"), so anchor on line starts
    check("server listens on 80",
          re.search(r"(?m)^\s*listen 80;", no_comments_nginx(text)) is not None)
    check("root is the nginx html dir", "root /usr/share/nginx/html" in joined)

    # the two proxy contracts — service name and port must match compose + EXPOSE
    check("location /api/ proxies to http://backend:8000/api/",
          re.search(r"location /api/ \{[^}]*proxy_pass http://backend:8000/api/", joined, re.DOTALL) is not None)
    check("location /ws proxies to http://backend:8000/ws",
          re.search(r"location /ws \{[^}]*proxy_pass http://backend:8000/ws", joined, re.DOTALL) is not None)
    check("/ws uses HTTP/1.1 + Upgrade + Connection upgrade",
          all(s in joined for s in ("proxy_http_version 1.1",
                                    "proxy_set_header Upgrade $http_upgrade",
                                    'proxy_set_header Connection "upgrade"')))
    check("long WS timeouts (3600s)", "proxy_read_timeout 3600s" in joined
          and "proxy_send_timeout 3600s" in joined)
    check("vendor/ cached 1 day", "location /vendor/" in joined
          and "max-age=86400" in joined)
    check("SPA fallback try_files -> /index.html",
          "try_files $uri $uri/ /index.html" in joined)
    check("gzip enabled for JS/CSS/JSON", "gzip on" in joined
          and "gzip_types" in joined and "application/javascript" in joined
          and "application/json" in joined)
    check("first-party JS + index.html served no-cache",
          "no-cache" in joined and "location = /index.html" in joined)

    # every proxy target resolves: backend:8000 is the compose service + EXPOSE
    check("proxy host:port == compose service 'backend' + container port 8000",
          "http://backend:8000" in joined)


# ---------------------------------------------------------------------------
# F. cross-references with backend code / requirements
# ---------------------------------------------------------------------------


def check_backend_contracts() -> None:
    print("== F. backend contracts ==")
    main_py = (PWEB / "backend/app/main.py").read_text()
    check("@app.get('/api/health') exists (healthcheck target)",
          '@app.get("/api/health")' in main_py)
    check("@app.websocket('/ws') exists (nginx /ws proxy target)",
          '@app.websocket("/ws")' in main_py)

    reqs = (PWEB / "backend/requirements.txt").read_text()
    for pin in ("fastapi==", "uvicorn[standard]==", "numpy==", "numba==",
                "llvmlite==", "scipy==", "msgpack", "PyYAML=="):
        check(f"requirements.txt pins {pin.rstrip('=')}", pin in reqs)

    # the pinned stack must actually import in this interpreter (same deps the
    # builder installs; the sandbox system python is the reference env)
    proc = subprocess.run(
        [sys.executable, "-c",
         "import fastapi, uvicorn, numpy, numba, llvmlite, scipy, msgpack, yaml; print('ok')"],
        capture_output=True, text=True, check=False,
    )
    check("full pinned stack imports cleanly", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-160:])

    vendored = PWEB / "backend/pooltool"
    check("vendored pooltool present with __init__",
          (vendored / "__init__.py").is_file())
    check("vendored ruleset present (rules.py imports it)",
          (vendored / "ruleset" / "russian_pyramid.py").is_file())
    check("VENDORED.md provenance shipped",
          (vendored / "VENDORED.md").is_file())


# ---------------------------------------------------------------------------
# G. frontend files the container must serve
# ---------------------------------------------------------------------------


def check_frontend_files() -> None:
    print("== G. frontend integrity ==")
    html = (PWEB / "frontend/index.html").read_text()
    needed = ["style.css", "main.js", "lobby.js", "./vendor/three.module.js"]
    for rel in needed:
        check(f"index.html references {rel}", rel in html)
        # resolve the referenced path exactly as the browser would (relative
        # to frontend/) — './vendor/x' must exist under frontend/vendor/
        rel_path = rel.lstrip("./")
        check(f"frontend/{rel_path} exists on disk (will be COPYed)",
              (PWEB / "frontend" / rel_path).is_file())

    # three.module.js re-exports from three.core.js (r167+ split build —
    # decision #6): both files must ship
    three_mod = (PWEB / "frontend/vendor/three.module.js").read_text()
    check("three.module.js imports three.core.js (split build)",
          "three.core.js" in three_mod)
    check("vendor/three.core.js exists", (PWEB / "frontend/vendor/three.core.js").is_file())

    # the importmap resolves module specifiers -> vendored paths; every file
    # it points at must exist or the module graph 404s silently (Step 1 bug)
    imports: dict[str, str] = {}
    im = re.search(r'<script type="importmap">\s*(\{.*?\})\s*</script>', html, re.DOTALL)
    check("index.html has an importmap", im is not None)
    if im:
        import json

        try:
            imports = json.loads(im.group(1)).get("imports", {})
            ok_map, bad = True, []
            for spec, target in imports.items():
                if spec.endswith("/") and target.endswith("/"):
                    # prefix mapping (e.g. "three/addons/" -> "./vendor/jsm/"):
                    # not a file itself — concrete resolutions through it are
                    # covered by the OrbitControls check below
                    continue
                rel = target.removeprefix("./")
                if not (PWEB / "frontend" / rel).is_file():
                    ok_map = False
                    bad.append(f"{spec} -> {target}")
            check("every importmap target exists in frontend/", ok_map, str(bad))
        except json.JSONDecodeError as exc:
            check("every importmap target exists in frontend/", False, str(exc))

    main_js = (PWEB / "frontend/main.js").read_text()
    m = re.search(r'from\s+["\']([^"\']*OrbitControls\.js)["\']', main_js)
    check("main.js imports the vendored OrbitControls", m is not None)

    # Resolve main.js's OrbitControls specifier the way the browser importmap
    # does: bare specifiers starting with a mapped prefix are replaced; the
    # longest matching key wins (importmap semantics).
    def resolve_spec(spec: str, mapping: dict[str, str]) -> str | None:
        best: tuple[int, str] | None = None
        for key, target in mapping.items():
            if spec == key or spec.startswith(key):
                trail = spec[len(key):]
                cand = target + trail
                if best is None or len(key) > best[0]:
                    best = (len(key), cand)
        return best[1] if best else spec

    if m:
        spec = m.group(1)
        resolved = resolve_spec(spec, imports)
        rel = (resolved or "").removeprefix("./")
        check("OrbitControls specifier resolves to an existing vendored file",
              rel.startswith("vendor/") and (PWEB / "frontend" / rel).is_file(),
              f"{spec} -> {resolved}")


# ---------------------------------------------------------------------------
# H. .dockerignore
# ---------------------------------------------------------------------------


def check_dockerignore() -> None:
    print("== H. .dockerignore ==")
    text = (PWEB / ".dockerignore").read_text()
    check("excludes virtualenvs", ".venv" in text)
    check("excludes __pycache__", "__pycache__" in text)
    check("excludes .git", ".git" in text)


# ---------------------------------------------------------------------------


def main() -> int:
    check_files()
    check_compose()
    check_backend_dockerfile()
    check_frontend_dockerfile()
    check_nginx()
    check_backend_contracts()
    check_frontend_files()
    check_dockerignore()

    print(f"\n{passed} checks passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"  FAILED: {name}")
        return 1
    print("RESULT: PASS — Docker configuration statically verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
