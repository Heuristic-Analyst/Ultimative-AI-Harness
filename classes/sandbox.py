# sandbox.py — the sandboxes: throwaway Linux containers (podman) where the agents run everything: code, installs,
# notebooks. an agent never runs anything on your computer itself: its tools only ASK, and every command goes into
# its container. your computer only ever runs podman.
#
# two classes:
#   Workspace   ONE for the whole server. it knows podman, the Sandboxes/ folder, settings/folders.json, and who has
#               which folder, project and notebook right now. it hands every conversation its own Sandbox
#   Sandbox     ONE per conversation: that conversation's container, and everything the agent's tools do with it.
#               an agent only ever gets its own (agent.sandbox), so it can only open, use and close its own
#
# how a sandbox works:
#   - each folder in Sandboxes/ is one kind of sandbox, and its Containerfile is all there is. opening it builds an
#     IMAGE from that file (podman's cache makes this quick when nothing changed) and starts a CONTAINER from it: a
#     throwaway copy that is deleted when it stops (--rm). nothing installed at runtime survives a stop
#   - a sandbox may have settings next to its Containerfile: sandbox.json, written by YOU (memory, gpu, network).
#     the agent can't change them: Sandboxes/ can never be mounted, and no tool writes there. see settings()
#   - a container sees ONLY the folders named in settings/folders.json (functions/folders.py), each at
#     /workspace/<name>, read-only or read-write as you wrote it there:
#       "always"     in every sandbox, from its start
#       "exclusive"  mounted by the agent (mount_folder). one sandbox at a time
#       "shared"     mounted by the agent (mount_folder). any number of sandboxes
#       a project    ONE subfolder of the "projects" folder, read-write. one project per sandbox, and one sandbox per
#                    project. the projects folder itself is never mounted
#   - inside its container the agent may do anything with these folders that their access allows: write files, and
#     run them, also compiled programs. that is all INSIDE: nothing in them is ever run by this program on your
#     computer. the program only creates, renames and deletes folders there, it never opens what the agent wrote
#   - every folder is mounted nosuid, nodev: no file in it can give a program more rights, or stand for a device
#   - the network is OFF whenever the agent opens a sandbox. only you can switch it (/sandbox net on|off), unless the
#     sandbox's own sandbox.json (yours too) says "network": true
#   - podman can't add or remove a folder of a running container, so mounting or unmounting restarts it
#   - closing a sandbox deletes the container and everything in it. the folders on your computer are never touched
#
# what keeps your computer safe (start, below, has the podman flags):
#   - podman must run rootless (config.SANDBOX_ROOTLESS_ONLY): "root" inside is only you outside, never the real root
#   - no new privileges, a few capabilities taken away, limits on memory, cpus and processes
#   - no folder of the program itself, and not your home folder, can be in folders.json (functions/folders.py)
#   - none of your environment variables reach the container (so no API key), and no port of it is opened
#   - every container carries labels: which server started it and which copy of this program. leftovers of a server
#     that crashed are removed when the next one starts. containers you start yourself are never touched

import os
import re
import json
import shutil
import hashlib
import datetime
import threading
import subprocess
from classes.terminal import Terminal
from functions.folders import load_folders, FOLDER_NAME

SANDBOX_NAME = r"[a-z0-9]+(-[a-z0-9]+)*"                # what podman accepts in an image name: lowercase, digits, -
NETWORK = "podman"                                      # podman's own network. connected = internet, disconnected = none
SETTINGS = "sandbox.json"                               # Sandboxes/<name>/sandbox.json: that sandbox's settings (optional)
MEMORY = r"[1-9][0-9]*[kmgKMG]"                         # a memory size podman understands: 512m, 4g
TERMINAL_NAME = r"[A-Za-z0-9_-]{1,30}"                  # what a terminal may be called: main, server, build-2
TERMINALS = 4                                           # terminals open at once, per sandbox
NO_PROJECTS = ("there are no projects: the user set no projects folder (\"projects\" in settings/folders.json), so no "
               "project can be listed, created, mounted, renamed or deleted, and no tool makes that folder. if the "
               "work needs a project, tell the user")
PROGRAM = "[from the program, not the user] "           # how the program's own messages to the model start


class Workspace:
    def __init__(self, home, sandboxes_dir, folders_file, engine, command="podman", memory="2g", cpus="2",
                 pids=2048, timeout=600, rootless_only=True):
        self.home = home                       # the program's folder: relative paths in folders.json start here
        self.home_id = os.path.realpath(home)  # written on every container: two copies of this program on one
                                               # computer never touch each other's containers
        self.sandboxes_dir = sandboxes_dir     # Sandboxes/: one folder with a Containerfile per sandbox
        self.folders_file = folders_file       # settings/folders.json: the folders a sandbox may see
        self.engine = engine                   # the NAME of the folder with the notebook engine, e.g. "Notebook_Engine"
        self.command = command                 # "podman"
        self.memory = memory                   # limits for a container, unless its sandbox.json says otherwise
        self.cpus = cpus
        self.pids = pids
        self.timeout = timeout                 # seconds a command may run inside
        self.rootless_only = rootless_only     # True = sandboxes only start when podman runs without root rights
        self.instance = str(os.getpid()) + "-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")   # this server
        self.starts = 0                        # containers this server started so far, for their names
        self.all = {}                          # conversation name -> its Sandbox
        self.held = {}                         # what only one sandbox can have at a time -> the Sandbox that has it:
                                               # "folder:data", "project:website", "notebook:<hash>"
        self.guard = threading.Lock()          # one thread at a time changes all, held and starts
        self.tell = None                       # a function (conversation, text): a note for the clients that watch
                                               # that conversation (server.py sets it). None = nobody is told

    # --- podman: every command to it goes through here ---
    def podman(self, *args, timeout=None):
        """run one podman command. returns (exit code, what it printed). never raises"""
        try:
            done = subprocess.run([self.command] + list(args), capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                  encoding="utf-8", errors="replace", timeout=timeout)
        except FileNotFoundError:
            return 127, self.command + " is not installed"
        except subprocess.TimeoutExpired:
            return 124, self.command + " gave no answer within " + str(timeout) + " seconds"
        return done.returncode, (done.stdout + done.stderr).strip()

    def available(self):
        """is podman installed and running? (on mac and windows: `podman machine start` once)"""
        return self.podman("info", "--format", "{{.Host.Arch}}", timeout=60)[0] == 0

    def unusable(self):
        """None if sandboxes can start, otherwise why not"""
        code, out = self.podman("info", "--format", "{{.Host.Security.Rootless}}", timeout=60)
        if code != 0:
            return self.command + " is not installed or not running, so there are no sandboxes right now"
        if self.rootless_only and out.strip().lower() != "true":
            return (self.command + " runs with root rights (rootful), so no sandbox is started: \"root\" inside a "
                    "sandbox would be the real root of the computer. podman must run rootless (its default). only "
                    "for a podman machine that was set up rootful on purpose: SANDBOX_ROOTLESS_ONLY = False in "
                    "config.py allows it")
        return None

    def note(self, conversation, text):
        if self.tell:
            self.tell(conversation, text)

    # --- the folders a sandbox may see: settings/folders.json, read fresh every time, so your changes count at once ---
    def folders(self):
        """(the folders, None), or (None, what is wrong with the file). see functions/folders.py"""
        return load_folders(self.folders_file, self.home)

    # --- the sandboxes: the folders in Sandboxes/ ---
    def sandboxes(self):
        """every folder in Sandboxes/ with a Containerfile: name -> None if it can be used, otherwise why not"""
        found = {}
        if os.path.isdir(self.sandboxes_dir):
            for name in sorted(os.listdir(self.sandboxes_dir)):
                if os.path.isfile(os.path.join(self.sandboxes_dir, name, "Containerfile")):
                    if not re.fullmatch(SANDBOX_NAME, name):
                        found[name] = ("can't be used: a sandbox's folder name must be lowercase letters, digits and - "
                                       "(the user can rename it)")
                    else:
                        found[name] = self.settings(name)[1]     # None, or what is wrong with its sandbox.json
        return found

    def names(self):
        return [name for name, problem in self.sandboxes().items() if problem is None]

    def image(self, name):
        return "localhost/harness-sandbox-" + name

    def containerfile(self, name):
        with open(os.path.join(self.sandboxes_dir, name, "Containerfile"), encoding="utf-8", errors="replace") as f:
            return f.read().strip()

    def settings(self, name):
        """a sandbox's settings: Sandboxes/<name>/sandbox.json, written by you, never by the agent.
        (the settings, None), or ({}, what is wrong). no file: ({}, None) = the defaults from config.py.
        only these keys, each checked, so nothing else can ever reach podman through this file:
            memory  "4g"     how much memory it may use (default SANDBOX_MEMORY in config.py)
            gpu     true     it gets the computer's NVIDIA GPUs (needs the NVIDIA Container Toolkit, see Sandboxes/)
            network true     its network is ON when the agent opens it (default: off, only you switch it on)
        keys starting with _ (like _about) are notes for you, and are skipped"""
        path = os.path.join(self.sandboxes_dir, name, SETTINGS)
        if not os.path.isfile(path):
            return {}, None
        where = "Sandboxes/" + name + "/" + SETTINGS
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except ValueError as e:
            return {}, "can't be used: " + where + " is not valid JSON (" + str(e) + "). the user must fix it"
        except OSError as e:
            return {}, "can't be used: " + where + " can't be read (" + str(e) + ")"
        if not isinstance(data, dict):
            return {}, "can't be used: " + where + " must be one {...} with settings. the user must fix it"
        problems = []
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if key == "memory":
                if not (isinstance(value, str) and re.fullmatch(MEMORY, value)):
                    problems.append('"memory" must be like "4g" or "512m"')
            elif key == "gpu":
                if not isinstance(value, bool):
                    problems.append('"gpu" must be true or false')
            elif key == "network":
                if not isinstance(value, bool):
                    problems.append('"network" must be true or false')
            else:
                problems.append('"' + key + '" is not a setting (there are: _about, memory, gpu, network)')
        if problems:
            return {}, "can't be used: " + where + ": " + "; ".join(problems) + ". the user must fix it"
        return {k: v for k, v in data.items() if not k.startswith("_")}, None

    def describe_settings(self, settings):
        return ("memory " + settings.get("memory", self.memory) + ", GPU " + ("yes" if settings.get("gpu") else "no")
                + ", network " + ("on" if settings.get("network") else "off") + " when opened")

    def built_at(self, name):
        code, out = self.podman("image", "inspect", "--format", "{{.Created}}", self.image(name), timeout=60)
        return out[:19] if code == 0 and out else None

    def build(self, name, conversation):
        """build the image from the Containerfile. None if it worked, otherwise the end of the build's output"""
        self.note(conversation, "sandbox: building " + name + " from Sandboxes/" + name
                  + "/Containerfile (quick if nothing changed)")
        code, out = self.podman("build", "--tag", self.image(name), os.path.join(self.sandboxes_dir, name), timeout=3600)
        if code != 0:
            return "the build of " + name + " failed. the end of its output:\n" + out[-2000:]
        return None

    # --- containers ---
    def container_runs(self, container):
        code, out = self.podman("container", "inspect", "--format", "{{.State.Running}}", container, timeout=60)
        return code == 0 and out == "true"

    def new_container_name(self, sandbox_name):
        with self.guard:
            self.starts += 1
            return "harness-" + sandbox_name + "-" + self.instance + "-" + str(self.starts)

    def cleanup(self):
        """when the server starts: remove the containers an earlier server of this copy left behind (a crash, a
        killed terminal). found by their labels; containers you started yourself have none and are never touched.
        returns how many were removed"""
        code, out = self.podman("ps", "--all", "--filter", "label=harness.server", "--format", "json", timeout=60)
        if code != 0 or not out:
            return 0
        try:
            listed = json.loads(out)
        except ValueError:                             # not json: podman printed an error
            return 0
        removed = 0
        for c in listed:
            labels = c.get("Labels") or {}             # "or {}": podman writes null when there are none
            if labels.get("harness.home") != self.home_id:     # another copy of this program: not ours to touch
                continue
            if labels.get("harness.server") == self.instance:  # one of this server's own
                continue
            name = (c.get("Names") or [""])[0]
            if name and self.podman("rm", "--force", name, timeout=60)[0] == 0:
                removed += 1
        return removed

    # --- who has what: folders in "exclusive", projects and notebooks belong to one sandbox at a time ---
    def take(self, key, sandbox):
        """give this sandbox the thing behind key, if nobody else has it. taking is one step, so two sandboxes can
        never both get it. a sandbox whose container died without telling anyone doesn't keep it"""
        with self.guard:
            holder = self.held.get(key)
            if holder is None or holder is sandbox:
                self.held[key] = sandbox
                return True
            container, starting = holder.container, holder.starting
        if starting or (container and self.container_runs(container)):   # asked outside the guard: podman is slow
            return False
        with self.guard:                               # its container is gone: the thing is free
            if self.held.get(key) is holder:
                self.held[key] = sandbox
            return self.held.get(key) is sandbox

    def release(self, key, sandbox):
        with self.guard:
            if self.held.get(key) is sandbox:
                del self.held[key]

    def holder(self, key, sandbox):
        """who has it: "you", "another sandbox", or None = it is free"""
        with self.guard:
            holder = self.held.get(key)
            if holder is None:
                return None
            if holder is sandbox:
                return "you"
            container, starting = holder.container, holder.starting
        if starting or (container and self.container_runs(container)):
            return "another sandbox"
        return None

    # --- one Sandbox per conversation ---
    def of(self, conversation):
        """the Sandbox of this conversation. made the first time it is asked for; it starts nothing by itself"""
        with self.guard:
            if conversation not in self.all:
                self.all[conversation] = Sandbox(self, conversation)
            return self.all[conversation]

    def idle(self, conversation):
        """the conversation left the server's memory. no container runs for it: its Sandbox is forgotten too (a
        running one stays, with its container, until the agent closes it, the conversation is deleted or the server
        stops)"""
        with self.guard:
            sandbox = self.all.get(conversation)
            if sandbox and not sandbox.container and not sandbox.starting and not sandbox.notes:
                del self.all[conversation]

    def rename(self, old, new):
        """the conversation has a new name: its sandbox goes with it"""
        with self.guard:
            if old in self.all:
                self.all[new] = self.all.pop(old)
                self.all[new].conversation = new

    def remove(self, conversation):
        """the conversation was deleted: its sandbox is stopped and forgotten. the folders on your computer stay"""
        with self.guard:
            sandbox = self.all.pop(conversation, None)
        if sandbox:
            sandbox.shutdown()

    def shutdown(self):
        """the server stops: every container is stopped (and so deleted). the folders on your computer stay"""
        with self.guard:
            everyone = list(self.all.values())
        for sandbox in everyone:
            sandbox.shutdown()

    def stop_all(self):
        """/sandbox stop all: stop every running sandbox, in every conversation. returns [(conversation, sandbox)].
        the folders on your computer stay; every model is told with the next message in its conversation"""
        with self.guard:
            everyone = list(self.all.values())
        stopped = []
        for sandbox in everyone:
            name = sandbox.user_close()
            if name:
                stopped.append((sandbox.conversation, name))
        return stopped

    def overview(self, conversation):
        """/sandbox: what runs in this conversation, what runs in the others, and every sandbox there is"""
        problem = self.unusable()
        if problem:
            return problem
        mine = self.of(conversation)
        mine.running()
        lines = [mine.status_line()]
        with self.guard:
            others = [s for s in self.all.values() if s is not mine and s.container]
        for other in others:                           # asked from podman directly, never through their lock: one
            if self.container_runs(other.container or ""):   # that is busy restarting must not hold this up
                lines.append("also running: " + str(other.name) + " in conversation " + other.conversation
                             + " (network " + ("on" if other.network else "off") + ")")
        config, problem = self.folders()
        if problem:
            lines.append("folders: " + problem)
        lines.append("sandboxes:")
        found = self.sandboxes()
        for name, problem in found.items():
            marks = ""
            if problem:
                marks += " (" + problem + ")"
            else:
                if not self.built_at(name):
                    marks += " (not built yet)"
                marks += " [" + self.describe_settings(self.settings(name)[0]) + "]"
            lines.append("  " + name + marks)
        if not found:
            lines.append("  none. a new sandbox: a folder in Sandboxes/ with a Containerfile inside")
        return "\n".join(lines)


class Sandbox:
    def __init__(self, workspace, conversation):
        self.ws = workspace                    # the Workspace: podman, the settings, who has what
        self.conversation = conversation       # the conversation this sandbox belongs to
        self.container = None                  # its container, e.g. harness-python-48213-2026...-1. None = none
        self.name = None                       # the kind of sandbox that runs, e.g. "python"
        self.mounts = []                       # what the container sees, in order: [{"name", "path", "shown",
                                               # "access": "ro"/"rw", "kind": always/exclusive/shared/project}]
        self.keys = set()                      # what this sandbox holds alone (Workspace.held): its exclusive
                                               # folders and its project
        self.network = False                   # internet on? off whenever the agent opens a sandbox. only you switch it
        self.notebooks = {}                    # the open notebooks: "Common/sales.ipynb" -> its key in Workspace.held
        self.terminals = {}                    # the open terminals (shells that stay open): "main" -> its Terminal
        self.notes = []                        # what YOU changed with /sandbox: told to the model with your next message
        self.lost = None                       # the sandbox stopped by itself (out of memory, removed by hand): which one
        self.starting = False                  # True while it starts or restarts: what it holds is not free meanwhile
        self.lock = threading.RLock()          # tools run in parallel: one opens, closes or mounts at a time.
                                               # RLock: these functions call each other while holding it

    # --- what is mounted ---
    def mount_of(self, name):
        """the mounted folder (or project) with this name, in any spelling, or None"""
        for mount in self.mounts:
            if mount["name"].lower() == str(name).lower():
                return mount
        return None

    def folders(self):
        """the names of the folders the agent mounted itself (not the always ones, not the project)"""
        return [m["name"] for m in self.mounts if m["kind"] in ("exclusive", "shared")]

    def project(self):
        for mount in self.mounts:
            if mount["kind"] == "project":
                return mount["name"]
        return None

    def writable(self):
        """the names of everything mounted read-write: where files can be kept"""
        return [m["name"] for m in self.mounts if m["access"] == "rw"]

    def workdir(self):
        """where commands start inside: the project, otherwise the first folder that can be written in"""
        if self.project():
            return "/workspace/" + self.project()
        writable = self.writable()
        if writable:
            return "/workspace/" + writable[0]
        return "/workspace" if self.mounts else "/"

    def engine(self):
        """the mounted notebook engine: (its path inside, None), or (None, why notebooks don't work)"""
        mount = self.mount_of(self.ws.engine)
        if not mount:
            return None, ("the notebook engine is not mounted: settings/folders.json has no folder called "
                          + self.ws.engine + " in \"always\". tell the user, notebooks don't work without it")
        if not os.path.isfile(os.path.join(mount["path"], "client.py")):   # looked at on your computer, never run there
            return None, ("the notebook engine is missing: there is no client.py in " + mount["shown"]
                          + ". tell the user, notebooks don't work without it")
        return "/workspace/" + mount["name"], None

    @staticmethod
    def key(mount):
        """the key in Workspace.held for something only one sandbox can have, or None if any number can"""
        if mount["kind"] == "exclusive":
            return "folder:" + mount["name"].lower()   # lowercase: on mac and windows Web and web are one folder
        if mount["kind"] == "project":
            return "project:" + mount["name"].lower()
        return None

    def plan(self, folders, project):
        """everything a container with these folders and this project will see: (the mounts, None), or (None, why not).
        read fresh from settings/folders.json, so what you changed there counts at the next start"""
        config, problem = self.ws.folders()
        if problem:
            return None, "no sandbox can start: " + problem
        mounts = [dict(entry) for entry in config["always"]]
        for name in folders:
            entry = self.find_folder(config, name)[0]
            if not entry:
                return None, name + " is not a folder that can be mounted anymore (the user changed settings/folders.json)"
            mounts.append(dict(entry))
        if project:
            if not config["projects"]:
                return None, NO_PROJECTS
            path = os.path.join(config["projects"], project)
            if not os.path.isdir(path) or os.path.islink(path):
                return None, "the project " + project + " is gone"
            mounts.append({"name": project, "path": path, "shown": config["projects_shown"].rstrip("/\\") + "/" + project,
                           "access": "rw", "kind": "project"})
        for mount in mounts:
            if mount["kind"] != "project" and not os.path.isdir(mount["path"]):   # a folder you named but didn't make
                try:                                                                # yet: made now, empty
                    os.makedirs(mount["path"], exist_ok=True)
                except OSError as e:
                    return None, "the folder " + mount["name"] + " (" + mount["shown"] + ") can't be made: " + str(e)
        return mounts, None

    @staticmethod
    def volume(mount):
        """the --volume value for one folder.
        ro / rw: as you wrote it in folders.json. z = other containers may share it, Z = only this container (selinux).
        nosuid, nodev: no file in it gives a program more rights, or stands for a device. (files in it CAN be run
        from inside the container: that harms nothing outside, and a compiler or a venv needs it)"""
        label = "Z" if mount["kind"] in ("exclusive", "project") else "z"
        return mount["path"] + ":/workspace/" + mount["name"] + ":" + label + "," + mount["access"] + ",nosuid,nodev"

    # --- starting and stopping this conversation's container ---
    def start(self, name, folders, project):
        """start a new container of this sandbox, with the always folders, these folders and this project mounted,
        and the settings of its sandbox.json. the caller holds the keys. returns None if it runs, otherwise why not"""
        settings, problem = self.ws.settings(name)
        if problem:
            return name + " " + problem
        mounts, problem = self.plan(folders, project)
        if problem:
            return problem
        problem = self.ws.build(name, self.conversation)
        if problem:
            return problem
        memory = settings.get("memory", self.ws.memory)
        container = self.ws.new_container_name(name)   # never clashes with another
        args = ["run", "--detach", "--rm", "--name", container,                        # --rm: deleted when it stops
                "--label", "harness.server=" + self.ws.instance,
                "--label", "harness.home=" + self.ws.home_id,
                "--label", "harness.sandbox=" + name,
                "--network", NETWORK,                  # born on the network, sealed right below (only podman's network
                                                       # can be switched later; a container born without one can't)
                "--entrypoint", "sleep",               # the only thing that runs inside until a command comes: nothing
                                                       # can use the network before it is sealed
                "--security-opt", "no-new-privileges", # no way to gain more rights than it starts with
                "--cap-drop", "NET_RAW", "--cap-drop", "MKNOD", "--cap-drop", "AUDIT_WRITE",   # no raw network
                                                       # packets, no device files, no audit log
                "--http-proxy=false",                  # your proxy settings (they can hold a password) stay outside.
                                                       # no other variable of yours is ever passed in
                "--init",                              # a tiny first process that cleans up ended background programs
                "--pids-limit", str(self.ws.pids), "--memory", memory, "--cpus", str(self.ws.cpus),
                "--shm-size", memory]                  # /dev/shm (shared memory, used by pytorch): as big as the
                                                       # memory limit. it can't use more anyway: it counts towards it
        if settings.get("gpu"):                        # the NVIDIA GPUs, through CDI (the NVIDIA Container Toolkit)
            args += ["--device", "nvidia.com/gpu=all"]
        for mount in mounts:
            args += ["--volume", self.volume(mount)]
        self.mounts = mounts                           # workdir() below reads it
        args += ["--workdir", self.workdir(), self.ws.image(name), "infinity"]
        code, out = self.ws.podman(*args, timeout=180)
        if code != 0:
            self.mounts = []
            if settings.get("gpu") and re.search(r"cdi|nvidia", out, re.IGNORECASE):
                return (name + " asks for the GPU (\"gpu\": true in Sandboxes/" + name + "/" + SETTINGS + "), but podman "
                        "can't give it: the NVIDIA Container Toolkit is not set up on this computer (see "
                        "Sandboxes/README.md). tell the user. podman said: " + out[-800:])
            return "could not start " + name + ": " + out[-1500:]
        self.container = container
        self.name = name
        self.lost = None
        if not self.set_network(self.network):         # off (or on again after a restart, if you had switched it on)
            self.stop()
            return ("the sandbox was stopped again, because its network could not be switched "
                    + ("on" if self.network else "off") + ". tell the user")
        return None

    def stop(self, keep=()):
        """stop the container (podman deletes it: --rm). keep: the keys that stay held (a restart mounts them again)"""
        if self.container:
            code, out = self.ws.podman("stop", "--time", "2", self.container, timeout=60)
            if code != 0:
                self.ws.podman("rm", "--force", self.container, timeout=60)
        self.forget(keep)

    def forget(self, keep=()):
        """this conversation has no container anymore: what it held (except keep) and its notebooks are free again"""
        for key in list(self.keys):
            if key not in keep:
                self.ws.release(key, self)
                self.keys.discard(key)
        for key in list(self.notebooks.values()):      # the kernels died with the container
            self.ws.release(key, self)
        self.notebooks.clear()
        for terminal in list(self.terminals.values()):   # they ran inside the container: gone with it
            terminal.close()
        self.terminals.clear()
        self.container = None
        self.name = None
        self.mounts = []

    def running(self):
        """the sandbox running in this conversation, or None. asked from podman, so one that died meanwhile is noticed"""
        with self.lock:                                # waits while a mount or unmount restarts the container
            if not self.container:
                return None
            if self.ws.container_runs(self.container):
                return self.name
            self.lost = self.name                      # gone (out of memory, removed by hand): it holds nothing anymore
            self.ws.podman("rm", "--force", self.container, timeout=60)
            self.forget()
            return None

    def not_running(self):
        """the answer for a tool that needs a running sandbox"""
        text = "no sandbox runs in this conversation. "
        if self.lost:
            text = ("the sandbox " + self.lost + " stopped by itself (most often: out of memory). everything inside it is "
                    "gone, the files in the mounted folders stay. ")
        return text + "start one with open_sandbox (check_sandbox shows which there are)"

    def shutdown(self):
        """the conversation was deleted, or the server stops: stop the container. nothing to save"""
        with self.lock:
            if self.container:
                self.stop()

    # --- the network: off whenever the agent opens a sandbox. only the user switches it ---
    def network_state(self):
        """True = connected, False = not, None = podman couldn't say"""
        code, out = self.ws.podman("inspect", "--format", "{{json .NetworkSettings.Networks}}", self.container, timeout=60)
        if code != 0:
            return None
        return '"' + NETWORK + '"' in out

    def set_network(self, on):
        """connect or disconnect the container, then CHECK. True only if it is now as asked"""
        if not self.container:
            return False
        state = self.network_state()
        if state is None:
            return False
        if on and not state:
            self.ws.podman("network", "connect", NETWORK, self.container, timeout=60)
        if not on and state:
            self.ws.podman("network", "disconnect", NETWORK, self.container, timeout=60)
        return self.network_state() == on

    def user_network(self, on):
        """/sandbox net on|off: only ever called for you (classes/hub.py), never by a tool"""
        with self.lock:
            if not self.running():
                return "no sandbox runs in this conversation (the agent opens one when it needs it)"
            if not self.set_network(on):
                return "could not switch the network " + ("on" if on else "off") + ". " + \
                    ("it is on" if self.network_state() else "it is off")
            self.network = on
            self.notes.append(PROGRAM + "The user switched the sandbox's network "
                              + ("ON: the sandbox can reach the internet now (e.g. pip install)." if on else
                                 "OFF: the sandbox can't reach the internet anymore."))
            return "network " + ("on" if on else "off") + " (until the agent opens a new sandbox, or you switch it)"

    def user_open(self, name):
        """/sandbox open <name>: you open this conversation's sandbox yourself. the same as the agent's open_sandbox,
        with the always folders only (the agent mounts what it needs). the model is told with your next message"""
        answer = self.open(name)
        if not answer.startswith("running "):
            return answer.replace(". tell the user", "").replace("close_sandbox first", "/sandbox stop first")
        self.notes.append(PROGRAM + "The user opened the sandbox " + name + " for you. It runs now, network "
                          + ("on" if self.network else "off") + ". " + self.where() + ".")
        return "opened " + name + ", network " + ("on" if self.network else "off") + "\n" + self.status_line()

    def user_close(self):
        """/sandbox stop: you stop this conversation's sandbox. the model is told with your next message"""
        with self.lock:
            here = self.running()
            if not here:
                return None                            # nothing ran
            self.stop()
            unknown = any("The user opened the sandbox" in note for note in self.notes)   # opened by you, and the
            self.notes = []                            # model was never told: for it, nothing happened at all.
            if not unknown:                            # (what you switched in a sandbox that is gone doesn't matter)
                self.notes.append(PROGRAM + "The user closed the sandbox (" + here + "). Everything inside it is "
                                  "gone, open notebooks and terminals are closed; the files in the mounted "
                                  "folders stay.")
            return here

    def take_notes(self):
        """what the user changed with /sandbox since the model's last message, and forget it"""
        notes, self.notes = self.notes, []
        return notes

    # --- running commands inside ---
    def exec(self, command, timeout=None):
        """run a bash command inside this conversation's container, in the working folder. returns what it printed"""
        timeout = timeout or self.ws.timeout
        if not self.running():
            return self.not_running()
        code, out = self.ws.podman("exec", "--workdir", self.workdir(), self.container,
                                   "timeout", "-k", "5", str(timeout), "bash", "-c", command,   # stopped inside, killed
                                   timeout=timeout + 15)                                         # 5 s later; and a limit
        if code == 124:                                                                          # outside
            return (out + "\n" if out else "") + "error: stopped after " + str(timeout) + " seconds"
        if code == 127 and not out:
            return "(exit code 127: a command was not found)"
        if code != 0:
            return (out + "\n" if out else "") + "(exit code " + str(code) + ")"
        return out or "(no output)"

    # --- what the agent and you see ---
    def describe(self, mount):
        """one mounted folder in words"""
        text = "/workspace/" + mount["name"] + " = " + mount["shown"] + " on the user's computer ("
        text += "read and write, kept" if mount["access"] == "rw" else "READ-ONLY: you can't change anything in it"
        if mount["kind"] == "project":
            text += ", your project: no other sandbox can mount it now"
        elif mount["kind"] == "exclusive":
            text += ", no other sandbox can mount it now"
        else:
            text += ", other sandboxes see it too"
        return text + ")"

    def where(self):
        """what the container sees, in words"""
        text = "; ".join(self.describe(m) for m in self.mounts) or "no folder is mounted"
        return text + "; everything else inside is gone when the sandbox stops"

    def status_line(self):
        """one line: the state right now. the tools that change it end their answer with it"""
        if not self.container:
            return "[now: no sandbox runs]"
        return ("[now: sandbox " + self.name + " runs, mounted: "
                + (", ".join(m["name"] + (" (read-only)" if m["access"] == "ro" else "") for m in self.mounts) or "nothing")
                + ", project: " + (self.project() or "none") + ", working folder " + self.workdir()
                + ", network " + ("on" if self.network else "off")
                + ", open notebooks: " + (", ".join(self.notebooks) or "none")
                + ", open terminals: " + (self.terminals_text() or "none") + "]")

    def snapshot(self):
        """the workspace for the system prompt: built whenever the system prompt is built (a new conversation, /open, a
        checkpoint), so a fresh context always knows what runs. tool results after it are newer"""
        here = self.running()
        lines = ["Your sandbox: a throwaway Linux container where everything you run happens (sandbox_shell, terminal, "
                 "notebooks). It is yours alone. You can't run anything on the user's computer. Inside it, only the "
                 "mounted folders under /workspace are kept; everything else is gone when it stops.",
                 "As it was when this context started (tool results after this are newer):"]
        if here:
            lines.append("- running: " + here + ", working folder " + self.workdir())
            for mount in self.mounts:
                lines.append("- " + self.describe(mount))
            lines.append("- network: " + ("on" if self.network else "off (only the user can switch it on)"))
            lines.append("- open notebooks: " + (", ".join(self.notebooks) or "none"))
            lines.append("- open terminals: " + (self.terminals_text() or "none"))
        else:
            lines.append("- no sandbox runs. open one with open_sandbox when you need to run something")
        lines.append("- sandboxes: " + (", ".join(self.ws.names()) or "none"))
        config, problem = self.ws.folders()
        if not problem:
            lines.append("- folders in every sandbox: " + (", ".join(e["name"] for e in config["always"]) or "none")
                         + ". folders you can mount: "
                         + (", ".join(e["name"] for e in config["exclusive"] + config["shared"]) or "none")
                         + ". projects: " + ((", ".join(self.projects_of_disk(config)) or "none yet")
                                             if config["projects"] else "not set up by the user"))
        return "\n".join(lines)

    # --- the agent's tools: sandboxes (tools/sandbox/) ---
    def check(self, name=None):
        """check_sandbox: every sandbox (or one) with its whole Containerfile, the folders, and what runs here.
        changes nothing"""
        problem = self.ws.unusable()
        if problem:
            return problem + ". tell the user"
        found = self.ws.sandboxes()
        if name and name not in found:
            return "no sandbox called '" + name + "'. sandboxes: " + (", ".join(found) or "none")
        if not found:
            return "no sandboxes yet. the user makes one: a folder in Sandboxes/ with a Containerfile inside"
        here = self.running()
        lines = ["running in this conversation: " + (here if here else "none") + ". one sandbox per conversation, and "
                 "it is yours alone.",
                 "every start builds the image from its Containerfile again: what is below is exactly what you get. "
                 "nothing installed at runtime is kept."]
        for each in ([name] if name else list(found)):
            lines.append("")
            lines.append("=== sandbox: " + each + " ===")
            if found[each]:
                lines.append(found[each])
            else:
                lines.append("settings (set by the user in " + SETTINGS + ", you can't change them): "
                             + self.ws.describe_settings(self.ws.settings(each)[0]))
            built = self.ws.built_at(each)
            lines.append("image: " + ("built " + built if built else "not built yet: the first start builds it, "
                                                                       "which can take a while"))
            lines.append("state: " + ("running here" if each == here else "not running here"))
            lines.append("Containerfile:")
            lines.append(self.ws.containerfile(each) or "(empty)")
        lines.append("")
        lines.append(self.check_folders())
        return "\n".join(lines) + "\n\n" + self.status_line()

    def check_folders(self):
        """the folders part of check_sandbox: what every sandbox sees, what can be mounted, and who has it"""
        config, problem = self.ws.folders()
        if problem:
            return "=== folders ===\nno sandbox can start: " + problem
        def line(entry, state=""):
            return ("- " + entry["name"] + ": /workspace/" + entry["name"] + ", "
                    + ("read and write" if entry["access"] == "rw" else "READ-ONLY") + ", = " + entry["shown"]
                    + " on the user's computer" + state)
        lines = ["=== folders (set by the user in settings/folders.json, you can't change them) ===",
                 "in every sandbox, always:"]
        lines += [line(e) for e in config["always"]] or ["- none"]
        lines.append("you can mount these (open_sandbox with folders, or mount_folder). only one sandbox at a time:")
        for entry in config["exclusive"]:
            holder = self.ws.holder(self.key(entry), self)
            lines.append(line(entry, {"you": ". mounted by you", "another sandbox": ". mounted by another sandbox, "
                                      "not available now", None: ". free"}[holder]))
        if not config["exclusive"]:
            lines.append("- none")
        lines.append("you can mount these too. other sandboxes can have them at the same time:")
        lines += [line(e, ". mounted by you" if self.mount_of(e["name"]) else "") for e in config["shared"]] or ["- none"]
        lines.append("projects: " + ("check_projects lists them" if config["projects"] else NO_PROJECTS))
        return "\n".join(lines)

    def find_folder(self, config, name):
        """(the folder of "exclusive" or "shared" with this name, None), or (None, why not)"""
        for entry in config["exclusive"] + config["shared"]:
            if entry["name"].lower() == str(name).lower():
                return entry, None
        for entry in config["always"]:
            if entry["name"].lower() == str(name).lower():
                return None, entry["name"] + " is in every sandbox already: it is never mounted or unmounted"
        names = [e["name"] for e in config["exclusive"] + config["shared"]]
        return None, ("no folder called '" + str(name) + "' can be mounted. folders: " + (", ".join(names) or "none")
                      + ". (a project? mount_project)")

    def open(self, name, folders=None, project=None):
        """open_sandbox: build and start this sandbox for this conversation, optionally with folders and a project"""
        with self.lock:
            problem = self.ws.unusable()
            if problem:
                return problem + ". tell the user"
            here = self.running()
            if here:
                return ("a sandbox already runs in this conversation: " + here + ". only one: use it, or "
                        "close_sandbox first. (to mount something into it: mount_folder, mount_project)\n"
                        + self.status_line())
            found = self.ws.sandboxes()
            if name not in found:
                return "no sandbox called '" + str(name) + "'. sandboxes: " + (", ".join(found) or "none")
            if found[name]:
                return name + " " + found[name]
            config, problem = self.ws.folders()
            if problem:
                return "no sandbox can start: " + problem
            if isinstance(folders, str):               # one folder as text: fine too
                folders = [folders]
            if folders is not None and not isinstance(folders, list):
                return "folders must be a list of folder names, e.g. [\"data\"]"
            wanted = []                                # the folders to mount, as they are in folders.json
            for folder in folders or []:
                entry, problem = self.find_folder(config, folder)
                if entry and entry not in wanted:
                    wanted.append(entry)
                elif problem and "in every sandbox already" not in problem:
                    return problem
            real = None
            if project:
                real, problem = self.find_project(config, project)
                if problem:
                    return problem
                wanted.append({"name": real, "kind": "project"})
            taken = []
            for entry in wanted:                       # every key, or none
                key = self.key(entry)
                if key and not self.ws.take(key, self):
                    for t in taken:
                        self.ws.release(t, self)
                    return (entry["name"] + " is mounted by another sandbox right now. leave it out, or pick "
                            "something else (check_sandbox, check_projects)")
                if key:
                    taken.append(key)
            self.keys = set(taken)
            self.network = self.ws.settings(name)[0].get("network", False)   # off, unless its sandbox.json (the
            self.starting = True                                             # user's) says "network": true
            try:
                problem = self.start(name, [e["name"] for e in wanted if e["kind"] != "project"], real)
            finally:
                self.starting = False
            if problem:
                self.forget()
                return problem
            return ("running " + name + ", network " + ("on (its sandbox.json, set by the user)" if self.network
                                                        else "off") + ". " + self.where() + "\n" + self.status_line())

    def close(self):
        """close_sandbox: stop it. the container is deleted, the folders on the user's computer stay as they are"""
        with self.lock:
            here = self.running()
            if not here:
                return self.not_running()
            self.stop()
            return ("stopped " + here + ". everything installed or started inside is gone; the files in the mounted "
                    "folders stay on the user's computer, untouched. what only you had mounted is free for other "
                    "sandboxes again\n" + self.status_line())

    def restart(self, folders, project, keys):
        """podman can't add or remove a folder of a running container: stop it and start a new one with these folders
        and this project. keys: what stays held through it; if it doesn't start again, they are given back. the
        network stays as it was"""
        name = self.name
        self.starting = True
        try:
            self.stop(keep=keys)                       # gives back only what is not in the new set
            self.keys = set(keys)
            problem = self.start(name, folders, project)
        finally:
            self.starting = False
        if problem:
            self.forget()
            return "the sandbox was stopped, but could not start again: " + problem
        return ("restarted " + name + ": whatever was installed or started inside since its start is gone, open "
                "notebooks were closed (nb_open them again), open terminals too. " + self.where())

    # --- the agent's tools: folders ---
    def mount_folder(self, name):
        """mount_folder: mount one more folder of "exclusive" or "shared". restarts the sandbox"""
        with self.lock:
            if not self.running():
                return "no sandbox runs in this conversation. open_sandbox can mount folders right away"
            config, problem = self.ws.folders()
            if problem:
                return problem
            entry, problem = self.find_folder(config, name)
            if problem:
                return problem
            if self.mount_of(entry["name"]):
                return entry["name"] + " is mounted already, at /workspace/" + entry["name"] + "\n" + self.status_line()
            key = self.key(entry)
            if key and not self.ws.take(key, self):
                return entry["name"] + " is mounted by another sandbox right now. only one can have it: try again later"
            answer = self.restart(self.folders() + [entry["name"]], self.project(), self.keys | ({key} if key else set()))
            if self.container:
                answer = "mounted " + entry["name"] + ". " + answer
            return answer + "\n" + self.status_line()

    def unmount_folder(self, name):
        """unmount_folder: unmount one folder the agent mounted. restarts the sandbox"""
        with self.lock:
            if not self.running():
                return self.not_running()
            mount = self.mount_of(name)
            if not mount or mount["kind"] not in ("exclusive", "shared"):
                if mount and mount["kind"] == "always":
                    return mount["name"] + " is in every sandbox, always: it can't be unmounted\n" + self.status_line()
                if mount and mount["kind"] == "project":
                    return mount["name"] + " is your project: unmount_project unmounts it\n" + self.status_line()
                return (str(name) + " is not mounted. folders you mounted: " + (", ".join(self.folders()) or "none")
                        + "\n" + self.status_line())
            rest = [f for f in self.folders() if f != mount["name"]]
            answer = self.restart(rest, self.project(), self.keys - {self.key(mount)})
            if self.container:
                answer = "unmounted " + mount["name"] + ". " + answer
            return answer + "\n" + self.status_line()

    # --- the agent's tools: projects. the subfolders of the projects folder in folders.json ---
    def projects_config(self):
        """(the folders, None) when there is a projects folder, otherwise (None, why there are no projects).
        the folder is only ever made when you named it: no path, no folder"""
        config, problem = self.ws.folders()
        if problem:
            return None, problem
        if not config["projects"]:
            return None, NO_PROJECTS
        try:
            os.makedirs(config["projects"], exist_ok=True)
        except OSError as e:
            return None, "the projects folder (" + config["projects_shown"] + ") can't be made: " + str(e)
        return config, None

    def projects_of_disk(self, config):
        """the project folders. links to folders elsewhere are not projects: a sandbox could reach outside through them"""
        found = []
        if config["projects"] and os.path.isdir(config["projects"]):
            for name in sorted(os.listdir(config["projects"])):
                path = os.path.join(config["projects"], name)
                if not name.startswith(".") and os.path.isdir(path) and not os.path.islink(path):
                    found.append(name)
        return found

    def name_problem(self, config, name):
        """None if this is a good name for a project, otherwise why not"""
        if not isinstance(name, str) or not name:
            return "give the project's name"
        if not re.fullmatch(FOLDER_NAME, name) or len(name) > 60:
            return "invalid project name: letters, digits, - _ . only, at most 60 characters, e.g. sales-2026"
        for entry in config["always"] + config["exclusive"] + config["shared"]:
            if entry["name"].lower() == name.lower():  # both would be /workspace/<name>
                return (entry["name"] + " is the name of a folder from settings/folders.json, so no project can be "
                        "called that: pick another name")
        return None

    def find_project(self, config, name):
        """(the existing project's real name, None), or (None, why not). the same name in another spelling is accepted"""
        if not config["projects"]:
            return None, NO_PROJECTS
        problem = self.name_problem(config, name)
        if problem:
            return None, problem
        existing = self.projects_of_disk(config)
        if name in existing:
            return name, None
        same = [p for p in existing if p.lower() == name.lower()]
        if len(same) == 1:
            return same[0], None
        return None, ("no project called '" + name + "'. projects: " + (", ".join(existing) or "none yet")
                      + ". create_project makes a new one")

    def check_projects(self):
        """check_projects: every project, and who has it mounted"""
        config, problem = self.projects_config()
        if problem:
            return problem
        self.running()
        lines = ["projects are the folders in " + config["projects_shown"] + " on the user's computer. a sandbox mounts "
                 "ONE of them, read and write, at /workspace/<project>, and while it has it, no other sandbox can "
                 "mount that one. the projects folder itself is never mounted."]
        names = self.projects_of_disk(config)
        if not names:
            lines.append("projects: none yet. create_project makes one")
        else:
            lines.append("projects:")
            for name in names:
                if self.name_problem(config, name):
                    state = "can't be used: " + self.name_problem(config, name) + " (the user can rename it)"
                else:
                    state = {"you": "mounted by you", "another sandbox": "mounted by another sandbox, not available now",
                             None: "free"}[self.ws.holder("project:" + name.lower(), self)]
                lines.append("- " + name + ": " + state)
        return "\n".join(lines) + "\n" + self.status_line()

    def create_project(self, name):
        """create_project: a new, empty folder in the projects folder"""
        with self.lock:
            config, problem = self.projects_config()
            problem = problem or self.name_problem(config, name)
            if problem:
                return problem
            for existing in os.listdir(config["projects"]):
                if existing.lower() == name.lower():
                    return "'" + existing + "' exists already in the projects folder: use it, or pick another name"
            os.makedirs(os.path.join(config["projects"], name))
            return ("created project " + name + " (" + config["projects_shown"].rstrip("/\\") + "/" + name + " on the "
                    "user's computer). mount_project mounts it, or open_sandbox with project=\"" + name + "\"\n"
                    + self.status_line())

    def mount_project(self, name):
        """mount_project: mount one project. one per sandbox. restarts the sandbox"""
        with self.lock:
            if not self.running():
                return "no sandbox runs in this conversation. open_sandbox can mount a project right away"
            config, problem = self.projects_config()
            if problem:
                return problem
            real, problem = self.find_project(config, name)
            if problem:
                return problem
            if self.project() == real:
                return real + " is mounted already, at /workspace/" + real + "\n" + self.status_line()
            if self.project():
                return ("your sandbox has the project " + self.project() + " mounted, and only one project per "
                        "sandbox is allowed: unmount_project first\n" + self.status_line())
            key = "project:" + real.lower()
            if not self.ws.take(key, self):
                return real + " is mounted by another sandbox right now. pick another project, or try again later"
            answer = self.restart(self.folders(), real, self.keys | {key})
            if self.container:
                answer = "mounted " + real + ". " + answer
            return answer + "\n" + self.status_line()

    def unmount_project(self):
        """unmount_project: unmount the project. restarts the sandbox"""
        with self.lock:
            if not self.running():
                return self.not_running()
            old = self.project()
            if not old:
                return "no project is mounted\n" + self.status_line()
            answer = self.restart(self.folders(), None, self.keys - {"project:" + old.lower()})
            if self.container:
                answer = "unmounted " + old + ", it is free for other sandboxes again. " + answer
            return answer + "\n" + self.status_line()

    def rename_project(self, name, new_name):
        """rename_project: rename a project folder nobody has mounted"""
        with self.lock:
            config, problem = self.projects_config()
            if problem:
                return problem
            real, problem = self.find_project(config, name)
            problem = problem or self.name_problem(config, new_name)
            if problem:
                return problem
            for existing in os.listdir(config["projects"]):
                if existing.lower() == new_name.lower() and existing != real:
                    return "'" + existing + "' exists already in the projects folder: pick another name"
            if self.project() == real:
                return real + " is mounted in your sandbox: unmount_project first, then rename it"
            key = "project:" + real.lower()
            if not self.ws.take(key, self):            # held while renaming: nobody can mount it meanwhile
                return real + " is mounted by another sandbox right now: it can only be renamed when nobody has it"
            try:
                os.rename(os.path.join(config["projects"], real), os.path.join(config["projects"], new_name))
            finally:
                self.ws.release(key, self)
            return "renamed project " + real + " -> " + new_name + "\n" + self.status_line()

    def delete_project(self, name):
        """delete_project: delete a project folder with everything in it, if nobody has it mounted"""
        with self.lock:
            config, problem = self.projects_config()
            if problem:
                return problem
            real, problem = self.find_project(config, name)
            if problem:
                return problem
            if self.project() == real:
                return real + " is mounted in your sandbox: unmount_project first, then delete it"
            key = "project:" + real.lower()
            if not self.ws.take(key, self):            # held while deleting: nobody can mount it meanwhile
                return real + " is mounted by another sandbox right now: it can only be deleted when nobody has it"
            try:
                shutil.rmtree(os.path.join(config["projects"], real))   # the folder and everything in it. there is
            finally:                                                    # no undo. links in it are removed, never
                self.ws.release(key, self)                              # followed
            return "deleted project " + real + " and everything in it\n" + self.status_line()

    # --- notebooks: which ones are open here (tools/notebook/_notebook.py) ---
    def claim_notebook(self, path):
        """take a notebook for this sandbox before its kernel starts. path: as the engine knows it, e.g.
        "Common/sales.ipynb". False = another sandbox has it open (possible in every folder several sandboxes see)"""
        mount = self.mount_of(path.split("/")[0])
        real = os.path.join(mount["path"], *path.split("/")[1:]) if mount else path   # the file on your computer:
        key = "notebook:" + hashlib.md5(os.path.normcase(real).encode()).hexdigest()[:16]   # the same for everyone
        if not self.ws.take(key, self):
            return False
        self.notebooks[path] = key
        return True

    def free_notebook(self, path):
        key = self.notebooks.pop(path, None)
        if key:
            self.ws.release(key, self)

    # --- terminals: shells that stay open between calls (classes/terminal.py) ---
    def terminals_text(self):
        """the open terminals and where each one is, e.g. "main (in /workspace/website)" """
        return ", ".join(name + " (in " + str(t.folder) + ")" for name, t in self.terminals.items() if t.alive())

    def terminal(self, command, name=None):
        """terminal: run a command in a shell that stays open (opened by the first call with this name). its folder
        (cd), variables, functions and activated environments stay for the next call"""
        name = str(name or "main").strip()
        if not re.fullmatch(TERMINAL_NAME, name):
            return "a terminal's name: letters, digits, - and _ only, at most 30 characters, e.g. main or server"
        if not isinstance(command, str) or not command.strip():
            return "give the command to run"
        if not self.running():
            return self.not_running()
        opened = ""
        with self.lock:                                # opening: one at a time, and not while the sandbox restarts
            if not self.container:
                return self.not_running()
            terminal = self.terminals.get(name)
            if terminal and not terminal.alive():
                self.terminals.pop(name)
                terminal = None
            if not terminal:
                if len(self.terminals) >= TERMINALS:
                    return ("already " + str(TERMINALS) + " terminals are open: " + self.terminals_text()
                            + ". use one of them, or close_terminal one first")
                shell = ["bash", "--noprofile", "--norc", "--noediting", "-i"]   # -i: see classes/terminal.py
                terminal = Terminal(name, [self.ws.command, "exec", "-i", "--workdir", self.workdir(), self.container]
                                    + shell, [self.ws.command, "exec", self.container])
                problem = terminal.start()
                if problem:
                    return problem
                self.terminals[name] = terminal
                opened = "(opened a new terminal '" + name + "' in " + str(terminal.folder) + ")\n"
        timeout = self.ws.timeout
        text, code, note = terminal.run(command, timeout)
        text = text.strip("\n")
        if note == "ended" or note == "timeout_reset":
            with self.lock:
                if self.terminals.get(name) is terminal:
                    self.terminals.pop(name)
        if note is None:
            answer = text or "(no output)"
            if code:
                answer += "\n(exit code " + str(code) + ")"
        elif note == "timeout":
            answer = ((text + "\n") if text else "") + ("error: stopped after " + str(timeout) + " seconds "
                      "(like ctrl+c). the terminal is still open: its folder and variables are kept")
        elif note == "timeout_reset":
            answer = ((text + "\n") if text else "") + ("error: stopped after " + str(timeout) + " seconds, "
                      "and it didn't end, so the terminal '" + name + "' was closed. its folder and variables are "
                      "gone; the next call opens a new one")
        else:
            answer = ((text + "\n") if text else "") + ("the terminal '" + name + "' ended (exit, `set -e` and a "
                      "failing command, or the sandbox stopped). its folder and variables are gone; the next call "
                      "opens a new one")
        if terminal.alive():
            answer += "\n[terminal " + name + ", now in " + str(terminal.folder) + "]"
        return opened + answer

    def close_terminal(self, name=None):
        """close_terminal: close one terminal, or all of them (no name)"""
        with self.lock:
            if not self.terminals:
                return "no terminal is open"
            if name:
                terminal = self.terminals.pop(str(name).strip(), None)
                if not terminal:
                    return "no terminal called '" + str(name) + "'. open: " + (self.terminals_text() or "none")
                closing = [terminal]
            else:
                closing = list(self.terminals.values())
                self.terminals.clear()
        for terminal in closing:                       # outside the lock: closing a busy one takes a few seconds
            terminal.close()
        names = ", ".join(t.name for t in closing)
        return ("closed " + names + ". programs it started in the background keep running\n" + self.status_line())
