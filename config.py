import os
from functions.read_json import read_json
from functions.environment import read_key

# Paths
HERE = os.path.dirname(os.path.abspath(__file__))   # the folder this file lives in. .env is found from here
ENV_FILE = os.path.join(HERE, ".env")
MODEL_FILE = os.path.join(HERE, "settings", "model.json")
SOUL_FILE = os.path.join(HERE, "Ego", "SOUL.md")     # who the agent is: the start of its system prompt. you write it
TOOLS_DIR = os.path.join(HERE, "tools")              # tools/<name>.py = one tool each (see functions/load_tools.py)
SKILLS_DIR = os.path.join(HERE, "skills")            # skills/<name>/SKILL.md = one skill each (see functions/load_skills.py)
CONVERSATIONS_DIR = os.path.join(HERE, "Conversations")   # Conversations/<name>/state.json = one conversation each
                                                          # (see functions/conversations.py). created with the first one

SANDBOXES_DIR = os.path.join(HERE, "Sandboxes")      # Sandboxes/<name>/Containerfile = one sandbox each (classes/sandbox.py)
FOLDERS_FILE = os.path.join(HERE, "settings", "folders.json")   # the ONLY folders of your computer a sandbox can see:
                                                     # which ones, under which name, read-only or read-write. you
                                                     # write it (see settings/README.md and functions/folders.py)
NOTEBOOK_ENGINE = "Notebook_Engine"                  # the NAME (in folders.json) of the folder with the notebook
                                                     # engine. the nb_* tools find it by this name

# Sandbox (see classes/sandbox.py). limits for a running sandbox, so a runaway script can't take your computer down.
# one sandbox can have its own memory: Sandboxes/<name>/sandbox.json (see Sandboxes/README.md)
CONTAINER_CMD = "podman"   # the container program. podman is rootless: "root" inside the sandbox is just you outside
SANDBOX_ROOTLESS_ONLY = True   # True: no sandbox starts when podman runs with root rights (then "root" inside would
                           # be the real root). False only for a podman machine (mac, windows) you set up as rootful
SANDBOX_MEMORY = "2g"      # memory a sandbox may use
SANDBOX_CPUS = "2"         # CPU cores a sandbox may use
SANDBOX_PIDS = 2048        # processes (and threads) a sandbox may have at once. stops a runaway script that copies
                           # itself; pytorch alone uses several hundred threads
COMMAND_TIMEOUT = 600      # seconds a command in the sandbox (sandbox_shell, a notebook call) may run, then it is stopped

# The server (server.py): the one program that holds the agents. every other program (main.py in a terminal, gui.py
# in a window, later e.g. a telegram bot) is a client that connects to it here
HOST = "127.0.0.1"         # 127.0.0.1 = only programs on this computer can connect, nothing from the network
PORT = 8765                # any free port number. the server listens on it, the clients connect to it
HISTORY_EVENTS = 600       # opening a conversation shows at most this many of its newest events (messages, tool
                           # calls, ...). the older ones stay in its log.jsonl

# Model settings: read the file once, then take what we need from it
MODEL_SETTINGS = read_json(MODEL_FILE)
MODEL = MODEL_SETTINGS["Model"]                        # required: without a model nothing works
STREAM = MODEL_SETTINGS.get("Stream", False)           # optional: True = print the answer piece by piece as it arrives
EFFORT = MODEL_SETTINGS.get("Effort")                  # optional: how hard the model thinks ("low", "medium", "high").
                                                       # None = the model's own default
PRINT_THINKING = MODEL_SETTINGS.get("PrintThinking", False)   # optional: True = show the thinking too, not only the answer.
                                                       # used by main.py (the terminal). the window always has it, folded
CONTEXT_LIMIT = MODEL_SETTINGS.get("ContextLimit", 100_000)   # optional: tokens a conversation may have at most. keep it
                                                       # at or below your model's real limit. tokens, not characters:
                                                       # the model's window is counted in tokens

# Checkpoints (see tools/basic/checkpoint.py): when the conversation gets too full, the model writes down where it
# stands, and the conversation starts fresh with that checkpoint in its system prompt
CHECKPOINT_AT = 0.6        # a task ended above 60% of CONTEXT_LIMIT: the model writes its checkpoint
EMERGENCY_AT = 0.8         # above 80% in the middle of a task: the checkpoint is written right away, and the task
                           # goes on from it

# Long tool results (see functions/results.py). in characters, not tokens: the same for every model
RESULT_LIMIT = 8_000       # x: a tool result longer than this is saved into the conversation's results/ folder,
                           #    and the model only gets a short preview of it
RESULT_PART = 4_000        # y: a saved result is cut into parts of this size. read_result shows one part at a time
RESULT_PREVIEW = 300       # how many characters of the result's start, and of its end, are in the preview
if RESULT_PART > RESULT_LIMIT - 500:                   # a part (+ read_result's first line) must stay below the limit,
    raise SystemExit("config.py: RESULT_PART must be at least 500 smaller than RESULT_LIMIT")   # or reading a part
                                                       # would be too long again, and be saved again

# Provider name
provider = MODEL.split("/")[0].upper()               # "deepseek/deepseek-flash" -> "DEEPSEEK"

# API key for using the model from the provider
API_KEY = read_key(provider, ENV_FILE)
