# conversations.py — the conversations on disk. each one is a folder in Conversations/, named after it:
#   Conversations/20261022-21-40-05/state.json     what the agent carries right now: what /open loads again.
#                                                  replaced after every message
#   Conversations/20261022-21-40-05/log.jsonl      every message ever said, one line each. only ever added to,
#                                                  never read by the program: it is for you (the agent writes it)
#   Conversations/20261022-21-40-05/results/       tool results too long for the context: results-1.json, ...
#                                                  (functions/results.py)
#   Conversations/20261022-21-40-05/checkpoint.md  the model's notes on where it stands, written when the
#                                                  conversation got too full (tools/basic/checkpoint.py)
# a new conversation is only written once something was said in it, so there are no empty folders.
# next to the folders, one file for all of them:
#   Conversations/last_input.json                  when YOU last wrote into each conversation, in milliseconds:
#                                                  {"20261022-21-40-05": 1794512405123, ...}. the window sorts its
#                                                  list by it, the one you used last on top (see touch, last_inputs)

import os
import re
import json
import time
import shutil
import datetime
from config import CONVERSATIONS_DIR
from functions.read_json import read_json

NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"                    # what a name may look like: letters, digits, - _ .
                                                        # and no / \ or .. : so it can never point outside the folder


LAST_INPUT_FILE = os.path.join(CONVERSATIONS_DIR, "last_input.json")   # a file, not a folder: never a conversation


def folder_of(name):
    return os.path.join(CONVERSATIONS_DIR, name)

def state_of(name):
    return os.path.join(CONVERSATIONS_DIR, name, "state.json")

def log_of(name):
    return os.path.join(CONVERSATIONS_DIR, name, "log.jsonl")

def results_of(name):
    return os.path.join(CONVERSATIONS_DIR, name, "results")      # tool results too long for the context

def checkpoint_of(name):
    return os.path.join(CONVERSATIONS_DIR, name, "checkpoint.md")   # in the system prompt, once there is one

def exists(name):
    return os.path.isdir(folder_of(name))


def new_name(taken=()):
    """a name for a new conversation: the time right now, e.g. 20261022-21-40-05. if a conversation with that
    name exists already (two in the same second): 20261022-21-40-05-2, -3, ...
    taken: names that are in use but have no folder yet (new conversations in which nothing was said so far)"""
    base = datetime.datetime.now().strftime("%Y%m%d-%H-%M-%S")
    name = base
    number = 2
    while exists(name) or name in taken:
        name = base + "-" + str(number)
        number += 1
    return name


def name_problem(name):
    """None if this is a good name for a conversation, otherwise what is wrong with it"""
    if not re.fullmatch(NAME, name) or len(name) > 60:
        return "invalid name: letters, digits and - _ . only, at most 60 characters, e.g. trip-planning"
    return None


def names():
    """every saved conversation: the folders in Conversations/ that have a state.json or a log, oldest first
    (the names start with the time they were made, so sorting them sorts them by time). a log without a state.json:
    a conversation whose only message failed. it has nothing to go on with yet, but it exists"""
    if not os.path.isdir(CONVERSATIONS_DIR):            # nothing saved yet: no folder yet
        return []
    return [name for name in sorted(os.listdir(CONVERSATIONS_DIR))
            if os.path.isfile(state_of(name)) or os.path.isfile(log_of(name))]


def save(name, agent):
    """write the conversation into Conversations/<name>/state.json, replacing what was there.
    the system prompt is NOT saved: it is built fresh when the conversation is opened again (the soul or the
    skills may have changed since). first into a temporary file, then swapped in: if the program dies in the
    middle of writing, the old state.json is still whole"""
    messages = agent.conversation
    if messages and messages[0]["role"] == "system":   # without the system prompt
        messages = messages[1:]
    if not messages and not os.path.isfile(state_of(name)):   # nothing said yet: nothing to save, no empty folder.
        return                                          # (emptied by a checkpoint: then state.json is emptied too)
    data = {"messages": messages, "tokens": agent.tokens}
    os.makedirs(folder_of(name), exist_ok=True)         # the folder appears with the first save
    temporary = state_of(name) + ".saving"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)   # ensure_ascii=False: ä, é, emoji stay readable
    os.replace(temporary, state_of(name))              # the swap: one step, never half a file


def load(name):
    """the saved conversation: {"messages": [...], "tokens": n}. only a log, no state.json yet: empty"""
    if not os.path.isfile(state_of(name)):
        return {"messages": [], "tokens": 0}
    return read_json(state_of(name))


def last_inputs():
    """when the user last wrote into each conversation: name -> milliseconds since 1970. a missing or broken file:
    nothing is known (the list then falls back to when each log was last written, see last_input)"""
    try:
        with open(LAST_INPUT_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_last_inputs(data):
    os.makedirs(CONVERSATIONS_DIR, exist_ok=True)
    temporary = LAST_INPUT_FILE + ".saving"             # first into a temporary file, then swapped in, like state.json
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(temporary, LAST_INPUT_FILE)


def touch(name):
    """the user just wrote into this conversation: remember when, to the millisecond. returns that time"""
    now = int(time.time() * 1000)
    data = last_inputs()
    data[name] = now
    write_last_inputs(data)
    return now


def last_input(name, known=None):
    """when the user last wrote into this conversation, in milliseconds. not written down (a conversation from
    before this file existed): when its log was last added to. nothing at all: None.
    known: last_inputs(), if the caller has it already (so the file is read once for a whole list)"""
    known = last_inputs() if known is None else known
    if isinstance(known.get(name), (int, float)):
        return int(known[name])
    for file in (log_of(name), state_of(name)):
        if os.path.isfile(file):
            return int(os.path.getmtime(file) * 1000)
    return None


def forget_input(name, new=None):
    """a conversation was deleted (new None) or renamed (to new): its line in last_input.json goes with it"""
    data = last_inputs()
    if name in data:
        value = data.pop(name)
        if new:
            data[new] = value
        write_last_inputs(data)


def rename(old, new):
    """rename a saved conversation's folder. returns None if it worked, otherwise what is wrong"""
    problem = name_problem(new)
    if problem:
        return problem
    if not exists(old):
        return "no conversation called '" + old + "'. /list shows them"
    if exists(new):
        return "a conversation called '" + new + "' exists already"
    os.rename(folder_of(old), folder_of(new))
    forget_input(old, new)                              # its time goes with it, under the new name
    return None


def delete(name):
    """delete a conversation: its folder, with everything in it. returns None if it worked, otherwise what is wrong"""
    if name_problem(name) or not exists(name):          # name_problem first: a name like ../x is never deleted
        return "no conversation called '" + name + "'. /list shows them"
    shutil.rmtree(folder_of(name))                      # the folder and everything in it. there is no undo
    forget_input(name)
    return None
