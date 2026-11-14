# run it:  python server.py
# start this FIRST, and leave it running. it is the one program that holds the agents: it calls the model, runs the
# tools, saves the conversations. everything else is a client that connects to it, and only shows things:
#   python main.py     the chat in a terminal
#   python gui.py      the chat in a window, with several conversations working at once
# several clients can be connected at the same time. ctrl+c stops the server.
#
# how the parts fit together:
#   a client  <── lines of json over a socket ──>  this file  <──>  the Hub (classes/hub.py)  <──>  the Agents
# this file only carries lines between the clients and the hub. what they mean is decided in the hub.

import os
import json
import queue
import socket
import atexit
import signal
import threading
from config import *
from classes.hub import Hub
from classes.agent import Agent
from classes.sandbox import Workspace
from functions.read_text import read_text
from functions.load_tools import load_tools
from functions.load_skills import load_skills
from functions import conversations


def new_agent(name, messages=None):
    """a fresh agent for the conversation called name: it logs into that conversation's log.jsonl, saves long
    tool results into its results/ folder, and its checkpoint as checkpoint.md. messages: a saved conversation to go on
    with (it gets a new system prompt, with the checkpoint in it if there is one).
    output=hub.event: everything the agent has to say goes to the hub, which passes it on to the right clients"""
    return Agent(MODEL, API_KEY, instructions=soul, stream=STREAM, effort=EFFORT,     # by name: can never land
                 tools=tools, skills=skills, conversation=messages,                   # in the wrong parameter
                 log_file=conversations.log_of(name), results_dir=conversations.results_of(name),
                 checkpoint_file=conversations.checkpoint_of(name), context_limit=CONTEXT_LIMIT,
                 output=hub.event, name=name,
                 sandbox=workspace.of(name) if workspace else None)   # this conversation's own sandbox, and no other

SANDBOX_TOOLS = ("sandbox", "notebook")              # the folders in tools/ that need a sandbox to do anything
SANDBOX_SKILLS = ("sandbox", "projects", "notebook")   # and the skills that explain them


def serve(connection, hub):
    """one client, in its own thread, as long as it is connected: every line it sends is a request for the hub,
    and every event the hub has for it is sent to it as a line"""
    outbox = queue.Queue()                           # the events on their way to this client. the hub only puts
                                                     # them in here and goes on: a slow client never holds it up
    client = hub.connect(outbox.put)                 # the hub's way to reach this client. returns its number
    hub.say("client " + str(client) + " connected")

    def write():                                     # a second thread: takes the events out and sends them
        while True:
            event = outbox.get()                     # waits for the next one
            if event is None:                        # None = the client left (see below): done
                return
            try:
                connection.sendall((json.dumps(event) + "\n").encode("utf-8"))
            except OSError:                          # the client is gone: nothing more to send
                return
    threading.Thread(target=write, daemon=True).start()

    try:
        with connection.makefile("r", encoding="utf-8") as lines:
            for line in lines:                       # waits for the client's next line, until it disconnects
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("a request must be one {...}")
                    hub.handle(client, request)
                except ValueError as e:              # not json: tell the client, and go on
                    hub.problem(client, "that request is not valid json: " + str(e))
                except Exception as e:               # a bug in handling one request must not end the server
                    hub.problem(client, "the server could not do that: " + type(e).__name__ + ": " + str(e))
    except OSError:                                  # the connection broke
        pass
    hub.disconnect(client)                           # it watches nothing anymore. what it started goes on
    outbox.put(None)                                 # ends the writing thread
    connection.close()
    hub.say("client " + str(client) + " disconnected")


if __name__ == "__main__":                           # runs only when you start server.py directly
    soul = read_text(SOUL_FILE) or "You are a helpful assistant."   # missing or empty file: a short fallback
    tools = load_tools(TOOLS_DIR)                    # every tool in tools/: name -> its schema and its function
    skills = load_skills(SKILLS_DIR)                 # every skill in skills/: name -> its description and its file
    if not skills:                                   # no skills: load_skill could do nothing, so the model
        tools.pop("load_skill", None)                # doesn't get it. (None: no error if it isn't there either)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":                              # mac and linux: let a restarted server use the port right away.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # (on windows this option would let two
    try:                                                                 # servers share one port, so not there)
        listener.bind((HOST, PORT))
    except OSError as e:
        raise SystemExit("can't listen on " + HOST + ":" + str(PORT) + " (" + str(e) + "). is a server running "
                         "already? otherwise pick another PORT in config.py")
    listener.listen()
                                                     # from here on this is the only server of this copy of the
                                                     # program (a second one would not have got the port). only now
                                                     # is anything of the sandboxes touched: a server that fails to
                                                     # start must never remove the sandboxes of the one that runs

    workspace = Workspace(HERE, SANDBOXES_DIR, FOLDERS_FILE, NOTEBOOK_ENGINE, command=CONTAINER_CMD,
                          memory=SANDBOX_MEMORY, cpus=SANDBOX_CPUS, pids=SANDBOX_PIDS, timeout=COMMAND_TIMEOUT,
                          rootless_only=SANDBOX_ROOTLESS_ONLY)
    if workspace.available():
        left = workspace.cleanup()                   # containers an earlier server left behind (a crash) go first
        if left:
            print("removed " + str(left) + " sandbox(es) an earlier server left behind")
        atexit.register(workspace.shutdown)          # whatever happens (also a crash in python): every sandbox stops
        for problem in (workspace.unusable(), workspace.folders()[1]):
            if problem:                              # the agent is told the same when it tries to open a sandbox
                print("sandboxes: " + problem.replace(". the user must fix it", ": fix it, no restart needed"))
    else:                                            # no podman: the sandbox and notebook tools could do nothing,
        workspace = None                             # so the model doesn't get them, nor the skills for them
        for name in [n for n, tool in tools.items() if tool["folder"].split("/")[0] in SANDBOX_TOOLS]:
            tools.pop(name)
        for name in SANDBOX_SKILLS:
            skills.pop(name, None)
        print(CONTAINER_CMD + " not found or not running: no sandboxes, so the agent can't run code "
              "(mac/windows: podman machine start, then start the server again)")
    if not skills:                                   # the last skills may just have been dropped
        tools.pop("load_skill", None)

    hub = Hub(new_agent, {"model": MODEL, "tools": list(tools), "skills": list(skills), "limit": CONTEXT_LIMIT},
              workspace=workspace)
    if workspace:                                    # what a sandbox says while it works (e.g. building an image)
        workspace.tell = lambda conversation, text: hub.event({"conversation": conversation, "kind": "note",
                                                               "text": text})

    print("model: " + MODEL + " | tools: " + (", ".join(tools) or "none")
          + " | skills: " + (", ".join(skills) or "none")
          + " | sandboxes: " + ((", ".join(workspace.names()) or "none") if workspace else "none"))
    print("the server listens on " + HOST + ":" + str(PORT) + ". clients: python main.py (terminal), "
          "python gui.py (window). ctrl+c stops the server\n")

    def leave(number, frame):                        # the terminal was closed, or the server was asked to end
        raise KeyboardInterrupt                      # (kill): leave the same way as with ctrl+c, so every
    for name in ("SIGTERM", "SIGHUP"):               # sandbox is stopped. (windows has no SIGHUP: there, and after
        if hasattr(signal, name):                    # a hard kill, the next server start removes what was left)
            signal.signal(getattr(signal, name), leave)

    listener.settimeout(1)                           # accept() gives up every second, so ctrl+c is noticed (on
    try:                                             # windows it isn't while accept() waits)
        while True:
            try:
                connection, address = listener.accept()   # waits for the next client
            except socket.timeout:
                continue
            connection.settimeout(None)              # the new connection must not inherit the 1 second
            threading.Thread(target=serve, args=(connection, hub), daemon=True).start()
    except KeyboardInterrupt:                        # ctrl+c: leave
        print()
    hub.shutdown()
    listener.close()
    print("bye")
