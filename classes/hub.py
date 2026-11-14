# hub.py — the Hub: the layer between the clients and the agents. it runs inside the server (server.py).
#
#   clients                                HUB                                   agents
#   main.py (terminal) ──┐                                              ┌── Agent "trip"     (in its own thread
#   gui.py (window) ─────┼── requests ──>  who watches which       ─────┼── Agent "taxes"     while it works)
#   anything else ───────┘ <── events ───  conversation?                └── Agent "20261112-20-07-01"
#
# a client never talks to an agent, and an agent never knows a client. both only know the hub:
#   - a client sends REQUESTS (handle): open this conversation, here is a message for it, stop it, rename it, ...
#   - an agent sends EVENTS (event): a piece of the answer, a tool call, a tool result, ... (classes/agent.py, send)
#   - the hub passes every event of a conversation on to the clients that have that conversation open (its
#     "watchers"). usually that is one client, the one that sent the message. open the same conversation in two
#     clients, and both see it. close a window in the middle of a task: the task goes on, and the window gets the
#     rest when it opens the conversation again
#
# every conversation works in its own thread, so several can work at the same time. one conversation does one
# task at a time: a message for a conversation that is still working is refused.
#
# REQUESTS, what a client sends. {"type": ..., and its fields}:
#   hello    kind                  who the client is ("cli", "gui", ...). answered with "hello"
#   new                            start a new conversation, and watch it. answered with "opened"
#   open     conversation          watch a saved conversation. answered with "opened"
#   close    conversation          stop watching it. (a task running in it goes on)
#   message  conversation, text    a message for the model. the answer comes as events
#   stop     conversation          stop the task running in it
#   list                           answered with "list"
#   rename   old, new              answered with "renamed", to every client
#   delete   conversation          answered with "deleted", to every client. its sandbox is stopped
#   sandbox  conversation, and at most one of:        what the USER does with a sandbox. answered with "sandbox"
#              (nothing)           say what runs in this conversation's sandbox, and everywhere
#              net: "on" / "off"   switch its network. only a client can: no tool of the agent leads here
#              do: "open", name    open the sandbox called name for this conversation
#              do: "stop"          stop this conversation's sandbox
#              do: "stop_all"      stop every running sandbox, in every conversation
#
# EVENTS, what a client gets. {"kind": ..., and its fields}. the ones the agent sends (thinking, answer, answer_end,
# tool_call, tool_result, note: see classes/agent.py), and the hub's own:
#   hello    client, model, tools, skills, limit    your client number, and what the server runs
#   opened   conversation, history, live, busy, messages, tokens, limit
#                                  history: what was said so far, as events (functions/history.py).
#                                  live: the events of the task that runs right now, if one does
#   user     conversation, text, client     a message someone sent to the model. client: the sender's number
#   error    conversation, text    the task failed (the model or the connection to it)
#   done     conversation, tokens, limit    the task ended: finished, stopped or failed
#   status   conversation, busy    a conversation started or ended a task. to EVERY client (for their lists)
#   refused  conversation, text    your message was not taken: the conversation is still working
#   problem  text                  your request could not be done (no such conversation, a bad name, ...)
#   list     conversations         [{"name", "busy", "saved", "last"}, ...]. last: when the user last wrote into
#                                  it, in milliseconds (Conversations/last_input.json). None: nothing said yet
#   renamed  old, new, client      to every client
#   deleted  conversation, client  to every client
#   sandbox  conversation, text    the answer to a "sandbox" request. a switched network goes to every watcher

import os
import datetime
import threading
from config import HISTORY_EVENTS
from functions import conversations
from functions.history import events_of_log

BUSY = ("this conversation is still working. wait until it is done, or stop it "
        "(the terminal: ctrl+c, the window: the stop button)")


class Hub:
    def __init__(self, make_agent, about, workspace=None):
        self.make_agent = make_agent           # a function (name, messages) -> a new Agent. server.py writes it: it
                                               # knows the model, the key, the tools and the skills
        self.workspace = workspace             # the Workspace (classes/sandbox.py): every conversation's sandbox.
                                               # None = no sandboxes (podman missing)
        self.about = about                     # what every client is told in "hello": model, tools, skills, limit
        self.lock = threading.RLock()          # clients and agents all run in their own threads: one at a time
                                               # changes what is below. RLock: these functions call each other
        self.clients = {}                      # client number -> {"send": the function that sends it an event,
                                               #                   "kind": "cli", "gui", ...}
        self.last_client = 0                   # the number the last client got. the next one gets one more
        self.agents = {}                       # conversation name -> its Agent. only the conversations in use:
                                               # open in a client, or working
        self.watchers = {}                     # conversation name -> the numbers of the clients that have it open
        self.working = {}                      # conversation name -> {"events": [...], "log_size": n}, only while
                                               # a task runs in it. events: what the task sent so far, for a client
                                               # that opens the conversation in the middle of it

    # --- clients come and go (server.py calls these) ---
    def connect(self, send):
        """a new client. send: a function that takes one event and sends it to that client. returns its number"""
        with self.lock:
            self.last_client += 1
            self.clients[self.last_client] = {"send": send, "kind": "?"}
            return self.last_client

    def disconnect(self, client):
        """a client left: it watches nothing anymore. what it started goes on"""
        with self.lock:
            self.clients.pop(client, None)
            for name in list(self.watchers):
                self.unwatch(client, name)

    # --- sending events ---
    def tell(self, client, event):
        """one event to one client"""
        if client in self.clients:
            self.clients[client]["send"](event)

    def to_watchers(self, name, event):
        """one event to every client that has this conversation open"""
        for client in self.watchers.get(name, ()):
            self.tell(client, event)

    def to_all(self, event):
        """one event to every client"""
        for client in list(self.clients):
            self.tell(client, event)

    def problem(self, client, text):
        self.tell(client, {"kind": "problem", "text": text})

    def event(self, event):
        """an event of a conversation: from its agent (this is agent.output), or from the hub itself. it goes to
        the conversation's watchers. while a task runs it is remembered too, for clients that open the conversation
        later. pieces of the same text (thinking, answer) are glued together there, so it stays short"""
        with self.lock:
            name = event["conversation"]
            task = self.working.get(name)
            if task is not None:
                events = task["events"]
                if event["kind"] in ("thinking", "answer") and events and events[-1]["kind"] == event["kind"]:
                    events[-1]["text"] += event["text"]
                else:
                    events.append(dict(event))     # dict(...) = a copy: the original is on its way to the clients
            self.to_watchers(name, event)

    # --- conversations in memory ---
    def agent_of(self, name):
        """the agent of this conversation. not in memory yet: made now, from what is saved (like /open always did:
        the saved messages, and a fresh system prompt)"""
        if name not in self.agents:
            data = conversations.load(name)
            agent = self.make_agent(name, data["messages"])
            agent.tokens = data.get("tokens", 0)
            self.agents[name] = agent
        return self.agents[name]

    def watch(self, client, name):
        self.watchers.setdefault(name, set()).add(client)

    def unwatch(self, client, name):
        """this client doesn't have the conversation open anymore. nobody has, and it isn't working: out of memory.
        (it is saved after every task, so nothing is lost. a new one in which nothing was said is simply gone)"""
        watching = self.watchers.get(name)
        if watching is not None:
            watching.discard(client)
            if not watching:
                del self.watchers[name]
        if name not in self.watchers and name not in self.working:
            self.forget(name)

    def forget(self, name):
        """the conversation leaves the server's memory. a sandbox that runs for it stays (and its agent gets it back
        when the conversation is opened again); one that doesn't is forgotten too"""
        self.agents.pop(name, None)
        if self.workspace:
            self.workspace.idle(name)

    def opened(self, client, name):
        """tell a client everything about a conversation it just opened"""
        agent = self.agents[name]
        task = self.working.get(name)
        history = events_of_log(agent.log_file, name, upto=task["log_size"] if task else None, limit=HISTORY_EVENTS)
        messages = len(agent.conversation)
        if messages and agent.conversation[0]["role"] == "system":
            messages -= 1                              # the system prompt is not a message of the conversation
        self.tell(client, {"kind": "opened", "conversation": name, "history": history,
                           "live": [dict(e) for e in task["events"]] if task else [],
                           "busy": task is not None, "messages": messages,
                           "tokens": agent.tokens, "limit": agent.context_limit})

    # --- requests: what a client wants (server.py calls handle for every line a client sends) ---
    def handle(self, client, request):
        """do one request of one client. whatever is wrong with it comes back as a "problem" event"""
        what = request.get("type")
        name = request.get("conversation")
        with self.lock:
            if what == "hello":
                self.clients[client]["kind"] = str(request.get("kind", "?"))
                self.tell(client, dict(self.about, kind="hello", client=client))

            elif what == "new":
                name = conversations.new_name(taken=self.agents)
                self.agents[name] = self.make_agent(name, None)
                self.watch(client, name)
                self.opened(client, name)

            elif what == "open":
                if not isinstance(name, str) or conversations.name_problem(name) or \
                        (name not in self.agents and name not in conversations.names()):
                    self.problem(client, "no saved conversation called '" + str(name) + "'. /list shows them")
                else:
                    self.agent_of(name)
                    self.watch(client, name)
                    self.opened(client, name)

            elif what == "close":
                self.unwatch(client, name)

            elif what == "message":
                self.message(client, name, request.get("text"))

            elif what == "stop":
                if name in self.working:
                    self.agents[name].stop_requested = True    # the agent sees it at its next safe point
                    self.say(name + ": stop asked by client " + str(client))
                else:
                    self.problem(client, "nothing is running in '" + str(name) + "'")

            elif what == "list":
                saved = conversations.names()
                names = sorted(set(saved) | set(self.agents))
                known = conversations.last_inputs()         # when the user last wrote into each one
                self.tell(client, {"kind": "list", "conversations": [
                    {"name": n, "busy": n in self.working, "saved": n in saved,
                     "last": conversations.last_input(n, known)} for n in names]})

            elif what == "rename":
                self.rename(client, request.get("old"), request.get("new"))

            elif what == "delete":
                self.delete(client, name)

            elif what == "sandbox":
                net, do = request.get("net"), request.get("do")
                if not self.workspace:
                    self.problem(client, "there are no sandboxes: podman was not found when the server started. "
                                         "install it (mac/windows: podman machine start), then start the server again")
                elif name not in self.agents or client not in self.watchers.get(name, ()):
                    self.problem(client, "open the conversation first: every conversation has its own sandbox")
                elif net not in (None, "on", "off") or do not in (None, "open", "stop", "stop_all") or (net and do) \
                        or (do == "open" and not isinstance(request.get("name"), str)):
                    self.problem(client, "usage: /sandbox  or  /sandbox net on|off  or  /sandbox open <name>  or  "
                                         "/sandbox stop  or  /sandbox stop all")
                else:                                      # in its own thread: podman can take a while (building an
                    threading.Thread(target=self.sandbox,  # image: minutes), and the hub must stay awake
                                     args=(client, name, net, do, request.get("name")), daemon=True).start()

            else:
                self.problem(client, "unknown request: " + str(what))

    def message(self, client, name, text):
        """a message for the model: start a task in that conversation, in its own thread"""
        if name not in self.agents or client not in self.watchers.get(name, ()):
            self.problem(client, "open the conversation first, then send it a message")
        elif not isinstance(text, str) or not text.strip():
            self.problem(client, "the message is empty")
        elif name in self.working:                         # one task at a time per conversation
            self.tell(client, {"kind": "refused", "conversation": name, "text": BUSY})
        else:
            agent = self.agents[name]
            agent.stop_requested = False                   # a new task: an old stop request is forgotten
            try:
                conversations.touch(name)                  # when you last wrote into it, for the clients' lists
            except OSError:                                # the list is only sorted by it: never worth losing
                pass                                       # a message over
            log_size = os.path.getsize(agent.log_file) if os.path.isfile(agent.log_file) else 0
            self.working[name] = {"events": [], "log_size": log_size}   # the log as it is now + these events =
                                                                        # everything, at any moment of the task
            self.to_all({"kind": "status", "conversation": name, "busy": True})
            self.event({"conversation": name, "kind": "user", "text": text, "client": client})
            self.say(name + ": working (message from client " + str(client) + ")")
            notes = agent.sandbox.take_notes() if agent.sandbox else []   # what you changed with /sandbox meanwhile
            if notes:                                      # (the network): the model is told with this message,
                text = text + "\n\n" + "\n".join(notes)   # after your own words
            threading.Thread(target=self.work, args=(name, agent, text), daemon=True).start()

    def sandbox(self, client, name, net, do, kind):
        """/sandbox, typed by a user in a client. this is the ONLY way the network is ever switched, and the only
        way anyone but a conversation's own agent opens or stops its sandbox: no tool leads here.
        net "on" / "off": switch the network of this conversation's sandbox
        do "open": open the sandbox called kind for this conversation. "stop": stop it. "stop_all": every sandbox
        neither: say what runs"""
        everyone = True                                    # a change: everyone who has the conversation open sees it
        others = []                                        # stop_all: the other conversations that lost a sandbox
        try:
            if net:
                text = self.workspace.of(name).user_network(net == "on")
            elif do == "open":
                text = self.workspace.of(name).user_open(kind)
            elif do == "stop":
                stopped = self.workspace.of(name).user_close()
                text = "stopped " + stopped + ". its folders stay as they are" if stopped else \
                    "no sandbox runs in this conversation"
            elif do == "stop_all":
                stopped = self.workspace.stop_all()
                text = ("stopped " + str(len(stopped)) + " sandbox(es): "
                        + ", ".join(kind + " in " + conversation for conversation, kind in stopped)
                        + ". their folders stay as they are") if stopped else "no sandbox runs anywhere"
                others = [conversation for conversation, kind in stopped if conversation != name]
            else:
                text = self.workspace.overview(name)
                everyone = False                           # only you asked what runs
        except Exception as e:
            text = "the server could not do that: " + type(e).__name__ + ": " + str(e)
            everyone = False
        with self.lock:
            event = {"kind": "sandbox", "conversation": name, "text": text}
            if everyone and client in self.watchers.get(name, ()):
                self.to_watchers(name, event)
            else:
                self.tell(client, event)
            for other in others:                           # who watches a conversation whose sandbox was stopped
                self.to_watchers(other, {"kind": "sandbox", "conversation": other,
                                         "text": "this conversation's sandbox was stopped (/sandbox stop all)"})
            if everyone:
                self.say(name + ": /sandbox " + (("net " + net) if net else do) + " by client " + str(client)
                         + " -> " + text.split("\n")[0])

    def work(self, name, agent, text):
        """one task, in its own thread: the agent's whole loop, until it has answered. everything it has to say
        arrives in event(), while it happens"""
        try:
            agent.ask(text)
        except Exception as e:                             # the model or the connection failed: say what happened
            self.event({"conversation": name, "kind": "error", "text": type(e).__name__ + ": " + str(e)})
        with self.lock:
            try:
                conversations.save(name, agent)            # after every task, also a failed one: tools that already
            except Exception as e:                         # ran are part of the conversation now
                self.event({"conversation": name, "kind": "error",
                            "text": "could not save the conversation: " + type(e).__name__ + ": " + str(e)})
            del self.working[name]                         # from now on the log has all of it again
            self.to_all({"kind": "status", "conversation": name, "busy": False})
            self.to_watchers(name, {"kind": "done", "conversation": name,       # "done" is the very last event
                                    "tokens": agent.tokens, "limit": agent.context_limit})   # of a task
            self.say(name + ": done")
            if name not in self.watchers:                  # nobody has it open anymore: out of memory
                self.forget(name)

    def rename(self, client, old, new):
        if not isinstance(old, str) or not isinstance(new, str):
            return self.problem(client, "rename needs the old and the new name")
        if old in self.working:
            return self.problem(client, old + " is working: wait until it is done, or stop it, then rename it")
        if conversations.exists(old):
            problem = conversations.rename(old, new)
        elif old in self.agents:                           # a new one, nothing said yet: it has no folder to rename
            problem = conversations.name_problem(new)
            if not problem and conversations.exists(new):
                problem = "a conversation called '" + new + "' exists already"
        else:
            problem = "no conversation called '" + old + "'. /list shows them"
        if not problem and new in self.agents:
            problem = "a conversation called '" + new + "' exists already"
        if problem:
            return self.problem(client, problem)
        if old in self.agents:                             # it is in memory: its agent writes into the new folder
            agent = self.agents.pop(old)                   # from now on
            agent.name = new
            agent.log_file = conversations.log_of(new)
            agent.results_dir = conversations.results_of(new)
            agent.checkpoint_file = conversations.checkpoint_of(new)
            self.agents[new] = agent
        if self.workspace:                                 # its sandbox, running or not, goes with it
            self.workspace.rename(old, new)
        if old in self.watchers:
            self.watchers[new] = self.watchers.pop(old)
        self.to_all({"kind": "renamed", "old": old, "new": new, "client": client})

    def delete(self, client, name):
        if not isinstance(name, str) or (not conversations.exists(name) and name not in self.agents):
            return self.problem(client, "no conversation called '" + str(name) + "'. /list shows them")
        if name in self.working:
            return self.problem(client, name + " is working: wait until it is done, or stop it, then delete it")
        if conversations.exists(name):
            problem = conversations.delete(name)
            if problem:
                return self.problem(client, problem)
        self.agents.pop(name, None)
        self.watchers.pop(name, None)
        if self.workspace:                                 # its sandbox is stopped (the container is deleted, the
            threading.Thread(target=self.workspace.remove, args=(name,), daemon=True).start()   # folders stay). in
                                                           # its own thread: stopping takes a few seconds
        self.to_all({"kind": "deleted", "conversation": name, "client": client})

    # --- the server's own terminal ---
    def say(self, text):
        """one line in the server's terminal, with the time: so you see what it is doing"""
        print("[" + datetime.datetime.now().strftime("%H:%M:%S") + "] " + text)

    def shutdown(self):
        """the server stops. nothing has to be saved: every conversation is saved after each of its tasks. a task
        that runs right now is cut off, and deliberately NOT saved in the middle (half a round, e.g. a tool call
        without its result, would make a conversation the provider rejects): it opens again as it was before that
        task, and every message of the task is in its log.jsonl"""
        with self.lock:
            for name in self.working:
                self.say(name + ": cut off in the middle of a task (its log.jsonl has everything it said)")
        if self.workspace:                                 # outside the lock: stopping takes a few seconds each
            self.say("stopping the sandboxes")
            self.workspace.shutdown()
