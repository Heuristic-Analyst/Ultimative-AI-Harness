# tools/sandbox/check_sandbox.py — look at the sandboxes and the folders. changes nothing. the logic is in classes/sandbox.py


def run(agent, name=None):
    return agent.sandbox.check(name)


TOOL = {
    "name": "check_sandbox",
    "description": "Look at the sandboxes and folders without changing anything: each sandbox's whole Containerfile "
                   "(what is installed in it, so what it is good for), its settings from the user (memory, GPU, "
                   "network), whether its image is built, and which one runs in this conversation (at most one, and "
                   "it is yours alone). Then the folders of the user's computer a sandbox can see: the ones in every "
                   "sandbox, and the ones you can mount, each with its name, whether it is read-only, and whether "
                   "another sandbox has it. Call it to pick the right sandbox and folders before open_sandbox, and to "
                   "see whether one runs already.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string",
                                           "description": "optional: one sandbox. left out: all of them"}}},
}
