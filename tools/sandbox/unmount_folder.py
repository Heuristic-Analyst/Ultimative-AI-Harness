# tools/sandbox/unmount_folder.py — unmount a folder the agent mounted. the logic is in classes/sandbox.py


def run(agent, name):
    return agent.sandbox.unmount_folder(name)


TOOL = {
    "name": "unmount_folder",
    "description": "Unmount one folder you mounted from your sandbox, so another sandbox can have it. Its files stay on "
                   "the user's computer; everything else stays mounted. The folders that are in every sandbox can't "
                   "be unmounted. This RESTARTS the sandbox: whatever was installed or started inside is gone, open "
                   "notebooks and terminals are closed.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "the folder to unmount"}},
                   "required": ["name"]},
}
