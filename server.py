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
import threading
from config import *
from classes.hub import Hub
from classes.agent import Agent
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
                 output=hub.event, name=name)


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

    hub = Hub(new_agent, {"model": MODEL, "tools": list(tools), "skills": list(skills), "limit": CONTEXT_LIMIT})

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":                              # mac and linux: let a restarted server use the port right away.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # (on windows this option would let two
    try:                                                                 # servers share one port, so not there)
        listener.bind((HOST, PORT))
    except OSError as e:
        raise SystemExit("can't listen on " + HOST + ":" + str(PORT) + " (" + str(e) + "). is a server running "
                         "already? otherwise pick another PORT in config.py")
    listener.listen()

    print("model: " + MODEL + " | tools: " + (", ".join(tools) or "none")
          + " | skills: " + (", ".join(skills) or "none"))
    print("the server listens on " + HOST + ":" + str(PORT) + ". clients: python main.py (terminal), "
          "python gui.py (window). ctrl+c stops the server\n")

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
