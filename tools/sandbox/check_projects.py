# tools/sandbox/check_projects.py — list the projects and who has them. the logic is in classes/sandbox.py


def run(agent):
    return agent.sandbox.check_projects()


TOOL = {
    "name": "check_projects",
    "description": "List the projects (the folders in the user's projects folder), and for each whether it is free, "
                   "mounted by you, or mounted by another sandbox (then you can't mount it now). Also says when "
                   "the user has set up no projects folder: then there are no projects at all. Call it before "
                   "create_project, mount_project, or open_sandbox with a project.",
    "parameters": {"type": "object", "properties": {}},
}
