# folders.py — reads settings/folders.json: the ONLY folders of your computer a sandbox can ever see.
# you write that file; no tool writes it, and the settings/ folder can never be mounted into a sandbox.
#
#   "always"     mounted in EVERY sandbox, from its start. any number of sandboxes at the same time
#   "exclusive"  the agent can mount them (mount_folder). only ONE sandbox can have one at a time
#   "shared"     the agent can mount them (mount_folder). any number of sandboxes at the same time
#   "projects"   ONE path: the folder that holds the projects. it is never mounted itself: a sandbox mounts one of its
#                subfolders (a project), read-write, and only one sandbox can have a project at a time.
#                left out (or ""): there are no projects, and no tool creates that folder for you
#
# every folder in the three lists is  {"name": ..., "path": ..., "access": "ro" or "rw"}:
#   name    what the tools call it, and where it appears inside: /workspace/<name>
#   path    absolute, or relative to the program's folder (where config.py is). ~ is your home folder
#   access  "ro" = read-only: nothing in it can be changed, renamed or deleted from inside. "rw" = read and write
# keys starting with _ are notes for you, and are skipped.
#
# every path is CHECKED (see path_problem), and one mistake makes the whole file unusable until you fix it: then no
# sandbox starts at all. that is on purpose: a folder you didn't mean must never reach a sandbox.

import os
import re
import json

FOLDER_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"            # what a folder (and a project) may be called
LISTS = ("always", "exclusive", "shared")
PROGRAM_FOLDERS = ("classes", "functions", "tools", "skills", "settings", "Sandboxes", "Ego", "Conversations", ".git")
                                                       # the program's own folders: never mounted, not even read-only
                                                       # (its code, your settings, your chats)


def same(path):
    """a path in the one spelling that can be compared: links followed, and on windows and mac lowercase"""
    return os.path.normcase(os.path.realpath(path))


def inside(path, folder):
    """is path the folder itself, or somewhere inside it?"""
    a, b = same(path), same(folder)
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:                                 # windows: two different drives
        return False


def path_problem(path, home):
    """None if a sandbox may see this folder, otherwise why not. the rules that keep your computer safe:
    - not the program's folder or anything above it, and not one of the program's own folders: a sandbox that could
      write there could change the code that runs on your computer; one that could read there would see your .env
    - not your home folder or anything above it: writing ~/.bashrc or ~/.ssh is running things on your computer
    - no ":" on mac and linux, and no line break: podman's --volume would read the path as something else"""
    if "\n" in path or "\r" in path or (os.name != "nt" and ":" in path):
        return "has a character podman can't take in a path (: or a line break)"
    if os.path.isfile(path):
        return "is a file, not a folder"
    if inside(home, path):                             # the program's folder is inside it (or is it)
        return "is the program's own folder, or above it: a sandbox must never see the program itself"
    for own in PROGRAM_FOLDERS:
        if inside(path, os.path.join(home, own)):
            return "is inside the program's own folder " + own + "/, which a sandbox must never see"
    if inside(os.path.expanduser("~"), path):
        return "is your home folder, or above it: far too much for a sandbox. give one folder inside it"
    return None


def load_folders(file, home):
    """read folders.json. returns (the folders, None), or (None, what is wrong).
    the folders: {"always": [...], "exclusive": [...], "shared": [...], "projects": path or None,
                  "projects_shown": the path as you wrote it}
    each folder: {"name", "path": absolute, links followed, "shown": as you wrote it, "access": "ro"/"rw",
                  "kind": the list it is in}"""
    where = os.path.relpath(file, home).replace(os.sep, "/")
    if not os.path.isfile(file):
        return None, where + " is missing, so no folder can be mounted and no sandbox starts"
    try:
        with open(file, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as e:
        return None, where + " is not valid JSON (" + str(e) + ")"
    except OSError as e:
        return None, where + " can't be read (" + str(e) + ")"
    if not isinstance(data, dict):
        return None, where + " must be one {...}"

    problems = []
    found = {"always": [], "exclusive": [], "shared": [], "projects": None, "projects_shown": None}
    names = {}                                         # lowercase name -> the list it is in: no name twice
    paths = []                                         # (what it is, its path): no folder inside another one

    def absolute(text):
        path = os.path.expanduser(text)
        if not os.path.isabs(path):                    # relative: from the program's folder
            path = os.path.join(home, path)
        return os.path.realpath(path)                  # links followed: what is mounted is what was checked

    for key, value in data.items():
        if key.startswith("_"):
            continue
        if key == "projects":
            if value in (None, ""):
                continue
            if not isinstance(value, str):
                problems.append('"projects" must be one path, as text')
                continue
            path = absolute(value)
            problem = path_problem(path, home)
            if problem:
                problems.append('"projects": ' + value + " " + problem)
            found["projects"], found["projects_shown"] = path, value
            paths.append(("the projects folder", path))
        elif key in LISTS:
            if not isinstance(value, list):
                problems.append('"' + key + '" must be a list [...] of folders')
                continue
            for entry in value:
                if not isinstance(entry, dict):
                    problems.append('"' + key + '": every folder must be {"name": ..., "path": ..., "access": ...}')
                    continue
                extra = [k for k in entry if k not in ("name", "path", "access") and not k.startswith("_")]
                name, text, access = entry.get("name"), entry.get("path"), entry.get("access")
                label = '"' + key + '": ' + (str(name) if name else "a folder without a name")
                if extra:
                    problems.append(label + " has settings that don't exist: " + ", ".join(extra))
                if not isinstance(name, str) or not re.fullmatch(FOLDER_NAME, name) or len(name) > 60:
                    problems.append(label + ': "name" must be letters, digits, - _ . only, at most 60 characters')
                    continue
                if name.lower() in names:
                    problems.append(label + ": the name is used twice (in " + names[name.lower()] + " and " + key + ")")
                    continue
                names[name.lower()] = key
                if access not in ("ro", "rw"):
                    problems.append(label + ': "access" must be "ro" (read-only) or "rw" (read and write)')
                if not isinstance(text, str) or not text.strip():
                    problems.append(label + ': "path" is missing')
                    continue
                path = absolute(text)
                problem = path_problem(path, home)
                if problem:
                    problems.append(label + ": " + text + " " + problem)
                paths.append((name, path))
                found[key].append({"name": name, "path": path, "shown": text, "access": access, "kind": key})
        else:
            problems.append('"' + key + '" is not a setting (there are: always, exclusive, shared, projects)')

    for i, (one, a) in enumerate(paths):               # a folder inside another one would get around "read-only" and
        for other, b in paths[i + 1:]:                 # "only one sandbox at a time": every folder stands alone
            if inside(a, b) or inside(b, a):
                problems.append(one + " and " + other + " are the same folder, or one is inside the other")

    if problems:
        return None, where + ": " + "; ".join(problems) + ". the user must fix it"
    return found, None
