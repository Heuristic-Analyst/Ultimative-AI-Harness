# tools/sandbox/close_sandbox.py — stop this conversation's sandbox. the logic is in classes/sandbox.py


def run(agent):
    return agent.sandbox.close()


TOOL = {
    "name": "close_sandbox",
    "description": "Stop your sandbox. The container is deleted: everything installed or started inside is gone, open "
                   "notebooks and terminals are closed. The files in the mounted folders and in the project stay on "
                   "the user's computer, untouched, and what only you had mounted is free for other sandboxes again. "
                   "Needed before open_sandbox can start a different one. Close it when the work is done: it uses "
                   "the user's memory while it runs.",
    "parameters": {"type": "object", "properties": {}},
}
