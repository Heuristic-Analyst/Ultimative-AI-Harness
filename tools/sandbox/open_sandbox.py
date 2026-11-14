# tools/sandbox/open_sandbox.py — build and start this conversation's sandbox. the logic is in classes/sandbox.py


def run(agent, name, folders=None, project=None):
    return agent.sandbox.open(name, folders or None, project or None)


TOOL = {
    "name": "open_sandbox",
    "description": "Build and start your sandbox, so sandbox_shell, terminal and the notebooks work. Pick it by what it "
                   "is made of (check_sandbox shows every Containerfile and its settings). One sandbox per "
                   "conversation, and only you can open or close it: to switch, close_sandbox first. Every start is "
                   "clean, exactly as its Containerfile says, with the network OFF (only the user can switch it on). "
                   "The folders the user put into every sandbox are mounted by themselves, each at /workspace/<name>. "
                   "Give every other folder and the project the work needs here: mounting one later restarts the "
                   "sandbox. The first start of a sandbox builds its image, which can take minutes.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "the sandbox, e.g. python"},
                                  "folders": {"type": "array", "items": {"type": "string"},
                                              "description": "optional: names of folders to mount, each at "
                                              "/workspace/<name> (check_sandbox lists the ones you can mount)"},
                                  "project": {"type": "string",
                                              "description": "optional: ONE existing project to mount at "
                                              "/workspace/<project> (check_projects lists them). it becomes the "
                                              "working folder"}},
                   "required": ["name"]},
}
