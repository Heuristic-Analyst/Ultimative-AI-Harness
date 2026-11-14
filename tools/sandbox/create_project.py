# tools/sandbox/create_project.py — a new, empty project folder. the logic is in classes/sandbox.py


def run(agent, name):
    return agent.sandbox.create_project(name)


TOOL = {
    "name": "create_project",
    "description": "Create a new, empty project: a folder in the user's projects folder. Then mount it "
                   "(mount_project, or open_sandbox with project). Check check_projects first: if the work belongs to "
                   "an existing project, use that one. Only works when the user has set up a projects folder. Tell "
                   "the user in one short sentence what you created.",
    "parameters": {"type": "object",
                   "properties": {"name": {"type": "string",
                                           "description": "letters, digits, - _ . only, e.g. sales-2026"}},
                   "required": ["name"]},
}
