# tools/sandbox/mount_folder.py — mount one more of the user's folders into the sandbox. the logic is in classes/sandbox.py


def run(agent, name):
    return agent.sandbox.mount_folder(name)


TOOL = {
    "name": "mount_folder",
    "description": "Mount one more folder into your sandbox, at /workspace/<name>. Only the folders the user allows "
                   "can be mounted (check_sandbox lists them, with whether each is read-only); what is mounted "
                   "already stays. Some folders can only be in one sandbox at a time: if another sandbox has it, "
                   "it can't be mounted now. This RESTARTS the sandbox (a running one can't get a new folder): "
                   "whatever was installed or started inside is gone, open notebooks and terminals are closed. So "
                   "mount first, then install and work. (A project? mount_project.)",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "the folder's name, as check_sandbox "
                                           "shows it, e.g. data"}},
                   "required": ["name"]},
}
