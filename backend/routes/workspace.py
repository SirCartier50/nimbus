import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_workspace: dict = {
    "path": None,
    "cwd": None,
    "github_url": None,
    "initialized": False,
}

ALLOWED_COMMANDS = {
    "git", "ls", "cat", "pwd", "tree", "mkdir", "touch",
    "rm", "mv", "cp", "echo", "head", "tail", "wc",
    "grep", "find", "chmod", "diff",
}

BLOCKED_GIT = {"push --force", "reset --hard", "clean -fd"}


def _get_or_create_workspace() -> str:
    if not _workspace["path"] or not os.path.exists(_workspace["path"]):
        _workspace["path"] = tempfile.mkdtemp(prefix="nimbus-workspace-")
        _workspace["cwd"] = _workspace["path"]
        _workspace["initialized"] = False
    return _workspace["path"]


def _get_cwd() -> str:
    ws = _get_or_create_workspace()
    cwd = _workspace.get("cwd") or ws
    if not os.path.exists(cwd):
        _workspace["cwd"] = ws
        cwd = ws
    return cwd


def _run(cmd: list[str], cwd: str, timeout: int = 15) -> dict:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Command timed out", "exit_code": -1}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "exit_code": -1}


def _resolve_path(target: str) -> str:
    cwd = _get_cwd()
    ws = _workspace["path"]
    resolved = os.path.normpath(os.path.join(cwd, target))
    if not resolved.startswith(ws):
        return ws
    return resolved


class ExecRequest(BaseModel):
    command: str


class GitHubLinkRequest(BaseModel):
    repo_url: str
    branch: Optional[str] = "main"


class WriteFilesRequest(BaseModel):
    files: dict
    session_id: Optional[str] = None


class SaveFileRequest(BaseModel):
    filename: str
    content: str


@router.post("/workspace/exec")
async def exec_command(req: ExecRequest):
    ws = _get_or_create_workspace()
    cwd = _get_cwd()
    raw = req.command.strip()

    if not raw:
        return {"success": False, "output": "Empty command"}

    parts = raw.split()
    base_cmd = parts[0]

    if base_cmd == "cd":
        target = parts[1] if len(parts) > 1 else ws
        if target == "~" or target == "/":
            target = ws
        resolved = _resolve_path(target)
        if os.path.isdir(resolved):
            _workspace["cwd"] = resolved
            rel = os.path.relpath(resolved, ws)
            display = "~" if rel == "." else f"~/{rel}"
            return {"success": True, "output": display, "cwd": display}
        return {"success": False, "output": f"cd: no such directory: {target}"}

    if base_cmd not in ALLOWED_COMMANDS:
        return {
            "success": False,
            "output": f"Command '{base_cmd}' not allowed. Allowed: cd, {', '.join(sorted(ALLOWED_COMMANDS))}",
        }

    if base_cmd == "git" and len(parts) > 1:
        subcmd = " ".join(parts[1:3])
        if subcmd in BLOCKED_GIT:
            return {"success": False, "output": f"'{subcmd}' is blocked for safety"}

    result = _run(parts, cwd)

    output = result["stdout"]
    if result["stderr"] and not result["success"]:
        output = result["stderr"] if not output else f"{output}\n{result['stderr']}"
    elif result["stderr"]:
        output = f"{output}\n{result['stderr']}" if output else result["stderr"]

    rel = os.path.relpath(cwd, ws)
    display_cwd = "~" if rel == "." else f"~/{rel}"

    return {
        "success": result["success"],
        "output": output or ("(no output)" if result["success"] else "Command failed"),
        "exit_code": result["exit_code"],
        "cwd": display_cwd,
    }


@router.post("/workspace/github/link")
async def link_github(req: GitHubLinkRequest):
    ws = _get_or_create_workspace()

    has_files = any(Path(ws).iterdir())

    if has_files:
        result = _run(["git", "init"], ws)
        if not result["success"]:
            return {"success": False, "message": f"git init failed: {result['stderr']}"}

        _run(["git", "remote", "remove", "origin"], ws)
        result = _run(["git", "remote", "add", "origin", req.repo_url], ws)
        if not result["success"]:
            return {"success": False, "message": f"Failed to add remote: {result['stderr']}"}

        _run(["git", "checkout", "-b", req.branch], ws)
    else:
        parent = os.path.dirname(ws)
        shutil.rmtree(ws)
        result = _run(["git", "clone", req.repo_url, os.path.basename(ws)], parent, timeout=30)
        if not result["success"]:
            _workspace["path"] = tempfile.mkdtemp(prefix="nimbus-workspace-")
            _workspace["cwd"] = _workspace["path"]
            return {"success": False, "message": f"Clone failed: {result['stderr']}"}

        if req.branch != "main":
            _run(["git", "checkout", "-b", req.branch], ws)

    _workspace["github_url"] = req.repo_url
    _workspace["cwd"] = ws
    _workspace["initialized"] = True

    return {
        "success": True,
        "message": f"Linked to {req.repo_url}",
        "workspace": ws,
        "branch": req.branch,
    }


@router.get("/workspace/github/status")
async def github_status():
    ws = _workspace.get("path")
    branch = ""
    if ws and os.path.exists(ws):
        result = _run(["git", "branch", "--show-current"], ws)
        if result["success"]:
            branch = result["stdout"]

    return {
        "linked": bool(_workspace.get("github_url")),
        "repo_url": _workspace.get("github_url"),
        "workspace": ws,
        "branch": branch,
    }


@router.post("/workspace/write-files")
async def write_files(req: WriteFilesRequest):
    ws = _get_or_create_workspace()
    written = []

    for filename, content in req.files.items():
        filepath = os.path.join(ws, filename)
        dirpath = os.path.dirname(filepath)
        if dirpath != ws:
            os.makedirs(dirpath, exist_ok=True)
        with open(filepath, "w") as f:
            f.write(content)
        written.append(filename)

    return {"success": True, "workspace": ws, "files_written": written}


@router.get("/workspace/files")
async def list_files():
    ws = _workspace.get("path")
    if not ws or not os.path.exists(ws):
        return {"files": [], "workspace": None}

    files = []
    for root, dirs, filenames in os.walk(ws):
        dirs[:] = [d for d in dirs if d != ".git" and d != "__pycache__"]
        for name in filenames:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, ws)
            files.append({"name": rel, "size": os.path.getsize(full)})

    return {"files": sorted(files, key=lambda f: f["name"]), "workspace": ws}


@router.get("/workspace/file/{filename:path}")
async def read_file(filename: str):
    ws = _workspace.get("path")
    if not ws:
        return {"success": False, "content": ""}

    filepath = os.path.join(ws, filename)
    if not os.path.exists(filepath) or not filepath.startswith(ws):
        return {"success": False, "content": "File not found"}

    try:
        with open(filepath, "r") as f:
            content = f.read()
        return {"success": True, "content": content, "filename": filename}
    except UnicodeDecodeError:
        return {"success": False, "content": "(binary file)"}


@router.post("/workspace/file/save")
async def save_file(req: SaveFileRequest):
    ws = _get_or_create_workspace()
    filepath = os.path.join(ws, req.filename)

    if not filepath.startswith(ws):
        return {"success": False, "message": "Invalid path"}

    dirpath = os.path.dirname(filepath)
    if dirpath != ws:
        os.makedirs(dirpath, exist_ok=True)

    with open(filepath, "w") as f:
        f.write(req.content)

    return {"success": True, "filename": req.filename, "size": len(req.content)}
