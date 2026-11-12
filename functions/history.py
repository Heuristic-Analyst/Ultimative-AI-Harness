# history.py — what was said in a conversation so far, as EVENTS: the same kind of events the agent sends while it
# works (classes/agent.py, send). so a client draws an old conversation exactly the way it draws a running one, with
# the same code.
# it is read from the conversation's log.jsonl, not from state.json: the log has every message ever said, also the
# ones from before a checkpoint.

import os
import json

PROGRAM = "[from the program, not the user]"            # how the program's own messages to the model start


def events_of_log(log_file, name, upto=None, limit=None):
    """the events of the conversation called name, read from its log.
    upto: read only the first `upto` bytes of the file (the hub uses this while a task runs: the log as it was
          when the task started. the task's own events it has in memory). None = the whole file
    limit: at most this many events, the newest ones. None = all of them"""
    if not log_file or not os.path.isfile(log_file):
        return []
    with open(log_file, "rb") as f:                      # "rb" = as bytes, so `upto` cuts at exactly that byte
        data = f.read() if upto is None else f.read(upto)
    events = []
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:                               # a broken line (the program died while writing it): skip
            continue
        if entry.get("kind") == "message":               # the other kind, "system", is not shown
            events += events_of_message(entry["message"], name)
    if limit and len(events) > limit:
        events = ([{"conversation": name, "kind": "note",
                    "text": "earlier messages are not shown here. all of them are in the conversation's log.jsonl"}]
                  + events[-limit:])
    return events


def events_of_message(message, name):
    """one message from the log, as the events that showed it when it was new"""
    role = message.get("role")
    content = message.get("content") or ""
    if not isinstance(content, str):                     # not plain text (not made by this program): as text anyway
        content = str(content)

    if role == "user":
        if content.startswith(PROGRAM):                  # the program talking to the model, e.g. a checkpoint request
            first = content[len(PROGRAM):].strip().split("\n")[0]
            return [event(name, "note", text="the program to the model: " + first[:100])]
        return [event(name, "user", text=content, client=None)]   # client None: we don't know who sent it back then

    if role == "assistant":
        events = []
        if message.get("reasoning_content"):
            events.append(event(name, "thinking", text=message["reasoning_content"]))
        if content:
            events.append(event(name, "answer", text=content))
        events.append(event(name, "answer_end"))
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            events.append(event(name, "tool_call", id=call.get("id"), name=function.get("name") or "",
                                args=function.get("arguments") or ""))
        return events

    if role == "tool":
        return [event(name, "tool_result", id=message.get("tool_call_id"), name=message.get("name") or "",
                      text=content)]
    return []


def event(conversation, kind, **fields):
    made = {"conversation": conversation, "kind": kind}
    made.update(fields)
    return made
