# tools/notebook/_notebook.py — what every nb_* tool next to it goes through. (the _ in front: not a tool, the loader
# skips it)
# the notebooks run INSIDE the sandbox, never on your computer. their engine (kernel.py and client.py) is in the folder
# that settings/folders.json calls Notebook_Engine (config.NOTEBOOK_ENGINE): it is in "always", read-only, so every
# sandbox sees it at /workspace/Notebook_Engine and none can change it. the tools find it by that NAME, through the
# sandbox (sandbox.engine()). one tool call = one run of client.py inside the sandbox, with one command; client.py
# starts, stops or asks the notebook's kernel, a program that stays alive and keeps the notebook's variables.
# the notebooks themselves are .ipynb files in the folders that are kept and can be written in: any mounted read-write
# folder, or the mounted project.
# an open notebook belongs to one sandbox (classes/sandbox.py, claim_notebook): another sandbox that sees the same
# folder can't open it at the same time, because its kernel would run in another container and save over this one's work.

import json
import base64


def resolve(sandbox, path):
    """the notebook's path as the engine needs it, e.g. "Common/sales.ipynb", and None. or None and what is wrong.
    the first part is the NAME of a mounted folder (or the project) the agent can write in, in any spelling"""
    text = str(path).replace("\\", "/").strip()
    if text.startswith("/workspace/"):                 # "/workspace/Common/x.ipynb" means Common/x.ipynb
        text = text[len("/workspace/"):]
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if text.startswith("/") or ".." in parts or len(parts) < 2 or not parts[-1].endswith(".ipynb") \
            or parts[-1] == ".ipynb":
        return None, ("the notebook must be a path ending in .ipynb inside " + allowed(sandbox)
                      + ", with no .. in it")
    folders = {name.lower(): name for name in sandbox.writable()}
    real = folders.get(parts[0].lower())
    if not real:                                       # anywhere else it would be gone when the sandbox stops, or
        return None, "a notebook must be inside " + allowed(sandbox)   # it is read-only
    parts[0] = real
    return "/".join(parts), None


def allowed(sandbox):
    """where notebooks can be, in words"""
    names = sandbox.writable()
    if not names:
        return ("a mounted folder you can write in, but none is mounted: mount a project (mount_project) or a "
                "read-write folder (mount_folder) first")
    return " or ".join(name + "/..." for name in names) + " (e.g. " + names[0] + "/analysis.ipynb)"


def call(agent, cmd, path, **args):
    """send one command for one notebook to the engine in the sandbox. returns the answer as text"""
    sandbox = agent.sandbox
    if not sandbox.running():
        return sandbox.not_running()
    engine, problem = sandbox.engine()                 # where the engine is inside, found by its name
    if problem:
        return problem
    notebook, problem = resolve(sandbox, path)
    if problem:
        return problem
    had_it = notebook in sandbox.notebooks             # open in this sandbox already
    if cmd in ("create", "open") and not had_it and not sandbox.claim_notebook(notebook):
        return (notebook + " is open in another sandbox right now. use another notebook, or try again when it is "
                "closed there")
    answer = send(sandbox, engine, cmd, notebook, args)
    opened = answer.startswith(("created ", "opened ", notebook + " was already open"))
    if cmd in ("create", "open") and not opened and not had_it:
        sandbox.free_notebook(notebook)                # it didn't open (no such file, no python3, ...): free again
    if cmd == "close" or "the notebook is closed" in answer or answer.startswith(notebook + " is not open"):
        sandbox.free_notebook(notebook)                # closed, or its kernel died (e.g. out of memory)
    return answer


def send(sandbox, engine, cmd, notebook, args):
    """run client.py in the sandbox with one command. the command goes as base64 (letters and digits only), so quotes,
    $ or backticks in the code can't confuse bash"""
    command = dict(args, cmd=cmd, notebook=notebook,
                   timeout=max(30, sandbox.ws.timeout - 30))   # a slow cell is stopped before the command's own limit
    payload = base64.b64encode(json.dumps(command).encode()).decode()
    answer = sandbox.exec("python3 -B " + engine + "/client.py " + payload)   # -B: no __pycache__, the engine is
    if "python3: command not found" in answer or answer.startswith("(exit code 127"):   # read-only
        return ("this sandbox has no python3, so notebooks don't work in it. close it and open one that has python3 "
                "(check_sandbox shows them, e.g. python)")
    return answer
