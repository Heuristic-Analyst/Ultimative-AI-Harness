# tools/sandbox/sandbox_shell.py — run a bash command INSIDE the sandbox, never on the user's computer.
# the logic is in classes/sandbox.py (exec). a long answer is saved as a result, like every tool's (functions/results.py)

from config import COMMAND_TIMEOUT


def run(agent, command):
    return agent.sandbox.exec(command)


TOOL = {
    "name": "sandbox_shell",
    "description": "Run a bash command inside your sandbox (a Linux container, you are root in it) and get what "
                   "it printed. Use it for single, independent commands (a quick look with ls or grep, one install, "
                   "one script run), and when you want several at once: several calls in one reply run at the same "
                   "time. Every call is a fresh shell: cd, variables and an activated venv are gone afterwards, so put "
                   "what belongs together into one command (cd src && python run.py). When steps build on each other "
                   "over several calls (working in one folder, in a venv, with variables set), use the terminal tool "
                   "instead. It starts in the mounted project, or in the first folder you can write in. "
                   "Only the folders mounted under /workspace are kept (and the read-only ones can't be changed); "
                   "everything else inside is yours to install and build in, and gone when the sandbox stops. "
                   "Commands get no keyboard input: use flags like -y. A command still running after "
                   + str(COMMAND_TIMEOUT) + " seconds is stopped: start longer jobs in the background with their output "
                   "in a file (nohup python job.py > job.log 2>&1 &) and check the file later.",
    "parameters": {"type": "object",
                   "properties": {"command": {"type": "string", "description": "the bash command, e.g. ls -la"}},
                   "required": ["command"]},
}
