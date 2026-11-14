# run it:  python main.py        (the server must be running: python server.py)
# then type your messages. /help shows the commands, /exit (or ctrl+c) leaves.
# while the model works, ctrl+c stops the task instead of leaving.
#
# this is a CLIENT: it holds no agent, calls no model and saves nothing. it sends what you type to the server
# (classes/connection.py) and prints the events that come back (classes/printer.py). the conversations live in the
# server: leave this program and start it again, and they are still there, even one that is still working.

import sys
from config import HOST, PORT, PRINT_THINKING
from classes.printer import Printer
from classes.connection import Connection
from functions.commands import check_input

SHOWN = ("thinking", "answer", "answer_end", "tool_call", "tool_result", "note", "error")   # the events of a task
                                                     # that are printed as they are (see classes/printer.py)


def handle(event):
    """do what one event from the server asks for. everything the server sends comes through here"""
    global current, busy
    kind = event["kind"]
    mine = event.get("conversation") == current      # is it about the conversation you are in?

    if kind == "closed":                             # the server is gone: nothing works without it
        print("\nthe server was stopped. start it again (python server.py), then this program")
        sys.exit()
    elif kind in SHOWN and mine:
        printer.show(event)
    elif kind == "user" and mine and event["client"] != me:   # sent from another client into this conversation.
        print("\n> " + event["text"] + "     (sent from another client)")   # (your own you typed here already)
    elif kind == "status" and mine and event["busy"]:   # this conversation started a task (maybe from another
        busy = True                                      # client). that it ended is said by "done": see follow
    elif kind == "refused" and mine:                 # your message was not taken: it is still working
        printer.show(event)
    elif kind == "problem":                          # a request that could not be done: the server says why
        print(event["text"])
    elif kind == "sandbox" and mine:                 # the answer to /sandbox (or another client switched the network)
        print(event["text"])
    elif kind == "renamed":
        if event["old"] == current:                  # the one you are in has a new name from now on
            current = event["new"]
        if event["client"] == me:
            print("renamed " + event["old"] + " -> " + event["new"])
        elif event["new"] == current:
            print("[this conversation was renamed by another client: " + current + "]")
    elif kind == "deleted":
        if event["client"] == me:
            print("deleted " + event["conversation"])
        if mine:                                     # the one you are in is gone: start a new one, or the next
            if event["client"] != me:                # message would have nowhere to go
                print("[this conversation was deleted by another client]")
            busy = False
            new_conversation()


def wait_for(*kinds):
    """read events until one of these kinds arrives, and return it. every event on the way is handled too"""
    while True:
        event = server.next(0.2)                     # 0.2 seconds at a time, so ctrl+c is noticed while waiting
        if event is None:
            continue
        handle(event)
        if event["kind"] in kinds:
            return event


def sandbox_request(words):
    """what /sandbox ... asks the server for. words: what you typed, already checked (functions/commands.py)"""
    if len(words) == 1:                              # /sandbox: what runs
        return {}
    if words[1] == "net":                            # /sandbox net on|off. only you can: the agent has no tool for it
        return {"net": words[2]}
    if words[1] == "open":                           # /sandbox open <name>
        return {"do": "open", "name": words[2]}
    return {"do": "stop_all" if len(words) == 3 else "stop"}   # /sandbox stop, /sandbox stop all


def new_conversation():
    """ask the server for a new conversation, and go into it"""
    global current
    server.send("new")
    current = None                                   # between two conversations: no event is "mine" meanwhile
    current = wait_for("opened")["conversation"]
    print("new conversation: " + current)


def follow():
    """the conversation you are in is working: print what happens, until the task is done.
    ctrl+c: ask the server to stop the task. a second ctrl+c, while it is stopping: leave the program"""
    global busy
    asked = False                                    # was the server asked to stop already?
    while busy:
        try:
            event = server.next(0.2)
            if event is not None:
                handle(event)
                if event["kind"] == "done" and event["conversation"] == current:
                    busy = False
                if event["kind"] == "problem":       # the server could not take the message at all: nothing runs
                    busy = False
        except KeyboardInterrupt:
            if asked:                                # the second ctrl+c: leave (the main loop below ends)
                raise
            asked = True
            server.send("stop", conversation=current)
            print("\n[stopping ... (ctrl+c again leaves the program)]")


def list_conversations():
    """print every conversation. * marks the one you are in"""
    server.send("list")
    for c in wait_for("list")["conversations"]:
        print(("* " if c["name"] == current else "  ") + c["name"]
              + (" (working)" if c["busy"] else "")
              + ("" if c["saved"] else " (nothing said yet, not saved)"))


if __name__ == "__main__":                           # runs only when you start main.py directly
    try:
        server = Connection(HOST, PORT, "cli")
    except OSError:
        raise SystemExit("no server is running on " + HOST + ":" + str(PORT) + ". start it first, in another "
                         "terminal: python server.py")
    printer = Printer(print_thinking=PRINT_THINKING)
    current = None                                   # the name of the conversation you are in
    busy = False                                     # is it working right now?
    me = None                                        # this client's number at the server: how it tells its own
                                                     # messages from the ones other clients sent
    try:
        hello = wait_for("hello")                    # the server's answer to our connecting
        me = hello["client"]
        print("model: " + hello["model"] + " | tools: " + (", ".join(hello["tools"]) or "none")
              + " | skills: " + (", ".join(hello["skills"]) or "none"))
        server.send("new")                           # a new conversation at every start
        current = wait_for("opened")["conversation"]
        print("conversation: " + current + "   (/help for commands)")

        while True:                                  # one round = one input from you
            while True:                              # first: what arrived while you were typing or away
                event = server.next(0)               # (e.g. another client wrote into this conversation)
                if event is None:
                    break
                handle(event)
            if busy:                                 # it is working (started by another client): watch it finish
                follow()

            text = input("\n> ").strip()             # strip: no spaces or empty lines around it
            what = check_input(text)                 # what to do with it (see functions/commands.py)
            words = text.split()                     # for the commands: ["/rename", "old", "new"]

            if what == "exit":
                break                                # leave the loop: the program ends below

            elif what == "new":
                server.send("close", conversation=current)   # the one you leave stays saved in the server
                new_conversation()

            elif what == "list":
                list_conversations()

            elif what == "open":
                name = words[1]
                server.send("open", conversation=name)
                answer = wait_for("opened", "problem")       # a problem (no such conversation) is printed by handle
                if answer["kind"] == "opened":
                    if current != name:
                        server.send("close", conversation=current)
                    current = name
                    print("opened " + name + ": " + str(answer["messages"]) + " messages")
                    busy = answer["busy"]
                    if busy:                         # it is in the middle of a task: what the task did so far,
                        print("[it is working right now. so far:]")   # then the loop above follows it to its end
                        for event in answer["live"]:
                            if event["kind"] == "user":
                                print("\n> " + event["text"])
                            else:
                                printer.show(event)

            elif what == "rename":
                server.send("rename", old=words[1], new=words[2])
                wait_for("renamed", "problem")       # both are printed by handle

            elif what == "delete":
                name = words[1]
                if input("delete '" + name + "' with everything in it? there is no undo. type yes: ").strip() != "yes":
                    print("not deleted")
                else:
                    server.send("delete", conversation=name)
                    wait_for("deleted", "problem")   # handle prints it, and starts a new one if it was this one

            elif what == "stop":                     # only useful from another client: this one is busy printing
                server.send("stop", conversation=current)   # while its conversation works, and ctrl+c stops it
                answer = server.next(0.5)            # nothing runs: the server says so right away
                if answer is not None:
                    handle(answer)

            elif what == "sandbox":                  # /sandbox ...: the server does it, for this conversation's
                server.send("sandbox", conversation=current, **sandbox_request(words))   # sandbox (or, stop all,
                if words[1:2] == ["open"]:           # for every one)
                    print("[opening " + words[2] + " ... the first time builds its image, which can take minutes]")
                wait_for("sandbox", "problem")       # both are printed by handle

            elif what == "message":
                busy = True                          # until the server says "done" (or that it failed)
                server.send("message", conversation=current, text=text)
                follow()                             # prints the answer while it arrives

            # what == "skip": nothing to do, just ask for the next input
    except (KeyboardInterrupt, EOFError):            # ctrl+c, or ctrl+d / the input ended: leave quietly
        print()

    server.close()                                   # the conversations stay in the server, also a working one
    print("bye")
