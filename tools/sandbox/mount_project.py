# tools/sandbox/mount_project.py — mount the one project into the running sandbox. the logic is in classes/sandbox.py


def run(agent, name):
    return agent.sandbox.mount_project(name)


TOOL = {
    "name": "mount_project",
    "description": "Mount a project into your sandbox, read and write, at /workspace/<name>. ONE project per sandbox: "
                   "if another one is mounted, unmount_project first. A project another sandbox has mounted can't be "
                   "mounted. Only the project's own folder is mounted, never the folder that holds all projects. "
                   "This RESTARTS the sandbox (a running one can't get a new folder): whatever was installed or "
                   "started inside is gone, open notebooks and terminals are closed. So mount first, then install "
                   "and work.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string", "description": "the project, e.g. website"}},
                   "required": ["name"]},
}
