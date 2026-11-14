# tools/sandbox/unmount_project.py — unmount the project from the sandbox. the logic is in classes/sandbox.py


def run(agent):
    return agent.sandbox.unmount_project()


TOOL = {
    "name": "unmount_project",
    "description": "Unmount the project from your sandbox, so other sandboxes can mount it (and so you can mount, "
                   "rename or delete it). Its files stay on the user's computer; the folders stay mounted. This "
                   "RESTARTS the sandbox: whatever was installed or started inside is gone, open notebooks and "
                   "terminals are closed.",
    "parameters": {"type": "object", "properties": {}},
}
