# AI Harness as a server, from scratch

A small AI assistant, built step by step so that every line is understood. It builds on the [Basic AI Harness](https://github.com/Heuristic-Analyst/Basic-AI-Harness): the same agent, tools, skills, conversations and checkpoints, but now it runs as a **server**, and everything you chat with is a **client** of it: a terminal (`main.py`), a window (`gui.py`), or anything you build yourself. Several conversations can work at the same time.

It talks to any model through [LiteLLM](https://github.com/BerriAI/litellm), can use tools, loads skills when it needs them, saves every conversation, and keeps working when a conversation gets too long for the model.

## Features

- **A server and its clients.** `server.py` holds the agents. `main.py` (terminal) and `gui.py` (window) only send what you type and show what comes back. Several clients can be connected at once, also to the same conversation.
- **Several conversations at once.** Each one works in its own thread. Start a long task in one, and go on in another.
- **Stop.** A running task can be stopped at any time: Ctrl+C in the terminal, the Stop button in the window. What was said so far is kept.
- **Tasks outlive their client.** Close the window in the middle of a task: it goes on in the server, and is there when you come back.
- **Any model.** One line in `settings/model.json` picks it: DeepSeek, Anthropic, OpenAI, a local Ollama model, or anything else LiteLLM supports.
- **Streaming and thinking.** The answer is printed while it arrives, and the model's thinking can be shown or hidden.
- **Tools.** One Python file per tool in `tools/`, found automatically. Several tool calls in one answer run at the same time, and their results go back in the order the model asked.
- **Skills.** Step-by-step instructions in `skills/`. Only their names and one-line descriptions are in the system prompt; the model loads a skill's full text when a task matches it.
- **Conversations.** Every conversation is a folder, saved after every message. You can list, open, rename and delete them.
- **A log.** Every message ever said is written into the conversation's `log.jsonl`, and nothing in it is ever changed.
- **Long results.** A tool result that is too long is saved in parts. The model gets a preview, and reads or searches the rest (`read_result`, `search_result`).
- **Checkpoints.** When a conversation gets too full, the model writes down where it stands, and the conversation starts fresh from those notes.
- **Retries.** A busy or unreachable provider is tried again, waiting longer each time.
- **Sandboxes.** Every conversation has its own throwaway Linux container (Podman), opened and closed by its agent. Everything the agent runs happens in there: commands, installs, terminals that stay open, Jupyter notebooks. Nothing is ever run on your computer.
- **Folders you choose.** A sandbox sees only the folders you name in `settings/folders.json`, each read-only or read-write: some in every sandbox, some the agent can mount (one sandbox at a time, or shared), and one project out of your projects folder.
- **The network is yours.** It is off whenever a sandbox opens. Only you switch it: `/sandbox net on|off`.
- **A sound when it needs you.** `notify_user` calls you back when the agent has to stop for something only you can do.

## How it fits together

```
 main.py (terminal) ──┐                                         ┌── Agent "trip"     (in its own thread
 gui.py (window) ─────┼── requests ──>  server.py + the Hub ────┼── Agent "taxes"     while it works)
 anything you build ──┘ <── events ───                          └── Agent "20261112-20-07-01"
```

- **`server.py`**: start it first, and leave it running. It loads the soul, the tools and the skills, and listens on `127.0.0.1:8765` (`HOST` and `PORT` in `config.py`). It only carries lines of JSON between the clients and the hub.
- **`classes/hub.py`**: the layer in between. Clients send it **requests** (open this conversation, here is a message, stop it), agents send it **events** (a piece of the answer, a tool call, a tool result). It passes every event of a conversation on to the clients that have that conversation open. It starts one thread per working conversation, refuses a message for a conversation that is still working, and saves the conversation to `state.json` after every task, also a failed one.
- **`main.py`** and **`gui.py`**: clients. They hold no agent and call no model. `main.py` prints the events the way the program always printed (`classes/printer.py`); `gui.py` draws them in a window, with markdown (`functions/markdown.py`). Both talk to the server through `classes/connection.py`.
- **`classes/agent.py`**: the heart of the program. `ask()` is the loop: call the model, add its answer to the conversation, run the tools it asked for, and go again until it answers without tools. `call_model()` tries again on errors that may go away by themselves (3 times, after 1, 2 and 4 seconds). The agent never prints: everything it has to say goes as an event to `agent.output`, a function the hub gave it. `agent.stop_requested` is how the hub stops a running task.
- **The system prompt**: built fresh from four parts, always in this order: `Ego/SOUL.md`, the skills menu, `checkpoint.md`, and what runs in the conversation's sandbox. It is never saved in `state.json`. The same order always gives the same text, so the provider's prompt cache stays valid.
- **Tools**: one file each in `tools/`, with `TOOL` (what the model sees) and `run(agent, **args)` (what the program does). They are found at the start, with no list to edit. All tool calls of one answer run at the same time, each in its own thread. Their results go back in the order the model asked, each with its call's id. Any problem comes back as a text starting with `error:`, so every call always gets an answer.
- **Skills**: only the name and description of each `SKILL.md` are in the system prompt. When a task matches, the model calls `load_skill` and gets the whole text back as a tool result. No skills: no `load_skill` either.
- **Long results**: a tool result longer than 8,000 characters is saved in 4,000-character parts as `results/results-<n>.json`. The model gets a preview with the start, the end and the number of parts. It reads one part with `read_result`, or finds lines with `search_result`, a grep with grep's options (`-E -i -w -v -A -B -o -c -m`). If a search answer is too long itself, it is saved as a new result.
- **Checkpoints**: the conversation's size comes from the token count the provider sends with every answer. A task that ended above 60% of `ContextLimit` gets a checkpoint request. Above 80% in the middle of a task, an emergency request comes right after the tool results. The model writes its notes in fixed sections (Goal, Decisions, Facts, Done, Failed, Open, Files, Last exchange) and gives them to the `checkpoint` tool. The tool saves `checkpoint.md`, empties the conversation, and builds the system prompt again with the checkpoint in it. The tool refuses when nobody asked, and the program asks at most twice per task.
- **Saving**: every conversation is a folder. `state.json` is what the model carries right now, written to a temporary file first and then swapped in. `log.jsonl` gets every message ever said, and the system prompt whenever it changed. It is only ever added to, and the program never reads it.
- **Sandboxes** (`classes/sandbox.py`): one `Workspace` for the server, and one `Sandbox` per conversation, which the agent gets as `agent.sandbox`. The tools in `tools/sandbox/` and `tools/notebook/` only call it. It builds the image from `Sandboxes/<name>/Containerfile`, starts a container that is deleted when it stops, mounts the folders from `settings/folders.json`, and keeps track of who has which exclusive folder, project and notebook. A sandbox stays until its agent closes it, its conversation is deleted, or the server stops. See `Sandboxes/README.md` and `settings/README.md`.
- **Safety**:
  - The agent runs nothing on your computer. Every command goes into its own rootless Podman container: no new privileges, limits on memory, CPUs and processes, none of your environment variables, no open ports. No sandbox starts if Podman runs with root rights.
  - A sandbox sees only the folders in `settings/folders.json`. Each is mounted `nosuid,nodev`, read-only where you say so. The program's own folders, your home folder, and anything above them are refused, and one mistake in the file stops every sandbox from starting.
  - The program never runs or opens what the agent wrote into those folders. On your side it only creates, renames and deletes project folders.
  - The network of a sandbox is off unless you switch it on. No tool can.
  - `calculate` only accepts digits and math symbols, and runs in its own isolated Python process (`-I`) that is stopped after 5 seconds.
  - Conversation, result and time zone names are checked against a pattern, so the model can never point the program at another folder or file.
  - The API key is read from `.env`, but never put into the environment.

## Requirements

- Python 3.10 or newer
- An API key for your model provider (not needed for local models such as Ollama)
- [Podman](https://podman.io), rootless, for the sandboxes (mac and windows: `podman machine start` once). Without it everything else still works: the sandbox and notebook tools and their skills are simply left out.

## Quick start

In the project's folder:

```bash
pip install -r requirements.txt
```

Create a file called `.env` next to `main.py` with the key for your provider. The name is the provider part of the model, in capitals, followed by `_API_KEY`:

```
DEEPSEEK_API_KEY=sk-...
```

The key is only ever read from this file and passed to LiteLLM directly. It never goes into your environment variables, and `.gitignore` keeps it off GitHub.

Then start the server, and leave it running:

```bash
python server.py
```

```
model: deepseek/deepseek-flash | tools: calculate, checkpoint, get_time, load_skill, read_result, search_result | skills: stepwise-calculation
the server listens on 127.0.0.1:8765. clients: python main.py (terminal), python gui.py (window). ctrl+c stops the server
```

And in another terminal, a client. Either the terminal:

```bash
python main.py
```

```
model: deepseek/deepseek-flash | tools: calculate, checkpoint, get_time, load_skill, read_result, search_result | skills: stepwise-calculation
conversation: 20261024-01-10-05   (/help for commands)

> what is 17% of 2340?
```

or the window (needs tkinter, which comes with Python on Windows and Mac; Debian/Ubuntu: `sudo apt install python3-tk`):

```bash
python gui.py
```

You can run both, and more than one of each. The model, the tools and the skills belong to the server: after changing one of them, restart the server, not the clients.

## Commands

Anything that doesn't start with `/` is a message to the model.

| Command | What it does |
|---|---|
| `/new` | Start a new conversation. The current one stays saved. |
| `/list` | Show the saved conversations. `*` marks the one you are in. |
| `/open <name>` | Continue a saved conversation. |
| `/rename <old> <new>` | Rename a saved conversation, also the one you are in. |
| `/delete <name>` | Delete a conversation with everything in it. Asks first: type `yes`. |
| `/stop` | Stop the running task. In the terminal you can't type while the model works: there, **Ctrl+C stops the task**. In the window, the Send button turns into Stop. |
| `/sandbox` | What runs in this conversation's sandbox (folders, project, network), which other conversations have one running, and every sandbox there is. |
| `/sandbox net on\|off` | Switch the internet of this conversation's sandbox. It is off whenever the agent opens one. Only you can do this; in the window also while the agent works. The model is told with your next message. |
| `/sandbox open <name>` | Open that sandbox for this conversation yourself, with the `always` folders. The agent does this on its own too; this is for when you want it ready, or want to pick which one. |
| `/sandbox stop` | Stop this conversation's sandbox. The container is deleted, its folders stay. |
| `/sandbox stop all` | Stop every running sandbox, in every conversation. |
| `/help` | Show the command list. |
| `/exit`, `/quit` | Leave. Ctrl+C (while nothing works) or Ctrl+D leave too. Everything is saved already, and what is still working goes on in the server. |

In the window, also: click a conversation on the left to open it, right-click it to rename or delete it, and click a `▸` line to open the thinking or a tool call. `/rename <new>` renames the conversation you are in, `/delete` deletes it.

## Settings

### `settings/model.json`

```json
{
  "Model": "deepseek/deepseek-flash",
  "Stream": true,
  "Effort": "high",
  "PrintThinking": true,
  "ContextLimit": 100000
}
```

| Setting | Meaning |
|---|---|
| `Model` | **Required.** Any LiteLLM model string: `provider/model`, e.g. `anthropic/...`, `openai/...`, `ollama/llama3`. |
| `Stream` | `true` = the answer is printed piece by piece while it arrives. Default `false`. |
| `Effort` | How hard the model thinks: `low`, `medium`, `high` (DeepSeek: `low`, `high`, `max`). Left out = the model's own default. A model that can't think simply ignores it. |
| `PrintThinking` | `true` = the model's thinking is shown too, not only its answer (in the terminal; the window always has it, folded). It is always kept in the conversation and the log. Default `false`. |
| `ContextLimit` | Tokens a conversation may have at most. **Set it to your model's real context window, or below.** Default 100,000. |

### `settings/folders.json`

The only folders of your computer a sandbox can see. Each has a `name` (it appears at `/workspace/<name>`), a `path` (absolute, or relative to the program's folder) and an `access`: `"ro"` or `"rw"`. `settings/README.md` has all of it.

| Key | What it is |
|---|---|
| `always` | In every sandbox, from its start. Any number of sandboxes at once. `Common` and the read-only `Notebook_Engine` are here. |
| `exclusive` | The agent can mount them. One sandbox at a time. |
| `shared` | The agent can mount them. Any number of sandboxes at once. |
| `projects` | One path: the folder that holds the projects. Never mounted itself: a sandbox mounts one project out of it, read-write, one sandbox per project. Left out: no projects, and nothing creates that folder. |

### `Sandboxes/<name>/sandbox.json`

Optional, next to a sandbox's `Containerfile`. Only these keys: `_about` (a note for you), `memory` (`"8g"`), `gpu` (`true`/`false`), `network` (`true` = on when the agent opens it). Anything else makes that sandbox unusable until it is fixed. See `Sandboxes/README.md`.

### `config.py`

| Setting | Default | Meaning |
|---|---|---|
| `HOST`, `PORT` | `127.0.0.1`, `8765` | Where the server listens, and the clients connect. `127.0.0.1` means: only programs on this computer. |
| `HISTORY_EVENTS` | `600` | Opening a conversation shows at most this many of its newest events. The rest stays in its `log.jsonl`. |
| `CHECKPOINT_AT` | `0.6` | A task ended above this share of `ContextLimit`: the model writes its checkpoint. |
| `EMERGENCY_AT` | `0.8` | Above this share in the middle of a task: the checkpoint is written right away, and the task goes on from it. |
| `RESULT_LIMIT` | `8_000` | A tool result longer than this (in characters) is saved in parts, and the model gets a preview. |
| `RESULT_PART` | `4_000` | The size of each saved part, in characters. Must be at least 500 smaller than `RESULT_LIMIT`. |
| `RESULT_PREVIEW` | `300` | How many characters of a saved result's start, and of its end, are in the preview. |
| `CONTAINER_CMD` | `podman` | The container program. |
| `SANDBOX_ROOTLESS_ONLY` | `True` | No sandbox starts when Podman runs with root rights. `False` only for a Podman machine you set up rootful on purpose. |
| `SANDBOX_MEMORY`, `SANDBOX_CPUS`, `SANDBOX_PIDS` | `2g`, `2`, `2048` | The limits of a sandbox. Memory can be set per sandbox in its `sandbox.json`. |
| `COMMAND_TIMEOUT` | `600` | Seconds a command in a sandbox may run before it is stopped. |
| `NOTEBOOK_ENGINE` | `Notebook_Engine` | The name, in `folders.json`, of the folder with the notebook engine. The `nb_*` tools find it by this name. |

All folders and files are defined in `config.py` too. To move or rename one, change it there.

### `Ego/SOUL.md`

Who the assistant is: the start of its system prompt. You write it. If the file is missing or empty, a one-line fallback is used.

## Project layout

```
.
├── server.py                # start here: the server. it holds the agents, the clients connect to it
├── main.py                  # a client: the chat in a terminal, and the /commands
├── gui.py                   # a client: the chat in a window, several conversations at once
├── config.py                # every setting and path, read once at the start
├── requirements.txt
├── .env                     # your API key. create it yourself, never commit it
├── classes/
│   ├── agent.py             # the Agent: the model calls, the tool loop, the events, the log, checkpoints, stopping
│   ├── hub.py               # the Hub: the layer between clients and agents. who gets which event
│   ├── connection.py        # the Connection: how a client talks to the server
│   ├── printer.py           # the Printer: shows events in a terminal (main.py)
│   ├── sandbox.py           # the Workspace and the Sandbox: every conversation's own podman container
│   └── terminal.py          # the Terminal: a shell that stays open inside a sandbox
├── functions/               # small helpers, mostly one job each
│   ├── commands.py          #   what you typed: a message, or which command
│   ├── conversations.py     #   the conversation folders: save, load, list, rename, delete
│   ├── history.py           #   a conversation's log as events, for a client that opens it
│   ├── markdown.py          #   markdown as pieces the window can draw
│   ├── results.py           #   long tool results: save in parts, preview, load
│   ├── folders.py           #   settings/folders.json: which folders a sandbox may see, checked
│   ├── load_tools.py        #   find and load every tool in tools/
│   ├── load_skills.py       #   find every skill in skills/
│   ├── read_front_matter.py #   the header of a SKILL.md
│   ├── read_json.py, read_text.py, write_text.py
│   └── environment.py       #   the API key from .env
├── settings/
│   ├── model.json           # which model, and how to talk to it
│   └── folders.json         # the only folders of your computer a sandbox can see
├── Sandboxes/               # one folder per sandbox: a Containerfile, and optionally a sandbox.json
│   ├── python/, ubuntu/, ai-lab/
├── Shared Folder/           # the folders the default folders.json points to
│   ├── Notebook_Engine/     #   the notebook engine (kernel.py, client.py): in every sandbox, read-only
│   ├── Common/              #   in every sandbox, read-write. made when first needed. never on GitHub
│   └── Projects/            #   the projects folder. made when first needed. never on GitHub
├── Ego/
│   └── SOUL.md              # who the assistant is
├── tools/                   # one file per tool (tools/README.md explains how to write one)
│   ├── basic/               #   calculate, get_time, load_skill, checkpoint, notify_user
│   ├── results/             #   read_result, search_result
│   ├── sandbox/             #   check_sandbox, open_sandbox, close_sandbox, sandbox_shell, terminal, close_terminal,
│   │                        #   mount_folder, unmount_folder, check_projects, create_project, mount_project,
│   │                        #   unmount_project, rename_project, delete_project
│   └── notebook/            #   nb_create, nb_open, nb_close, nb_add, nb_edit, nb_remove, nb_run, nb_rerun, nb_show
├── skills/                  # one folder per skill (skills/README.md explains how to write one)
│   ├── stepwise-calculation/SKILL.md
│   ├── sandbox/SKILL.md, projects/SKILL.md, notebook/SKILL.md
└── Conversations/           # your conversations, created with the first one. never on GitHub
    ├── last_input.json      #   when you last wrote into each conversation (ms). the window sorts its list by it
    └── <name>/
        ├── state.json       #   what the model carries right now: what /open loads
        ├── log.jsonl        #   every message ever said, one line each. only ever added to
        ├── checkpoint.md    #   the model's notes, once it wrote a checkpoint
        └── results/         #   long tool results: results-1.json, results-2.json, ...
```

## A conversation, drawn

The conversation is one list of messages, and the whole list is sent to the model with every call. Here is one task: you ask something, the model thinks, uses tools, and answers. On the right: which file each part comes from, or goes to.

```
 THE CONVERSATION (what the model gets, every call)                       ON YOUR DISK
 +------------------------------------------------------------------+
 | [0] system   built fresh from parts, always in this order:       |
 |     +--------------------------------------------------------+   |
 |     | 1. who you are, how you work                           |<--+------ Ego/SOUL.md
 |     | 2. your skills: one line each                          |<--+------ skills/*/SKILL.md (only the header)
 |     |    - stepwise-calculation: Use when a calculation ...  |   |
 |     | 3. <checkpoint> your notes </checkpoint>               |<--+------ checkpoint.md (once there is one)
 |     +--------------------------------------------------------+   |
 +------------------------------------------------------------------+
 | [1] user        "A jacket costs 120 €, 20% off, plus 19% tax.    |
 |                  What do I pay? And what does the shop say?"     |
 +------------------------------------------------------------------+
 | [2] assistant   thinking: "a calculation in steps: there is a    |
 |                 skill for that. and I need the shop's page."     |
 |                 tool calls:                                      |
 |                   id call_1  load_skill("stepwise-calculation")  |
 |                   id call_2  fetch_page("shop.example/jacket")   |  (an example tool, see below)
 +------------------------------------------------------------------+
 |                 both run at the same time. their results come    |
 |                 back in the order asked, each with its call's id |
 | [3] tool        id call_1  "---                                  |<---------- skills/stepwise-calculation/SKILL.md
 |                 name: stepwise-calculation ... 1. Write down..." |            (now the whole text)
 | [4] tool        id call_2  "[this result is too long (52,300     |----------> results/results-1.json
 |                 characters). it is saved as results-1, in 14     |            {"1": "...", "2": "...", ...
 |                 parts ... its start and its end:] <html> ..."    |             "14": "..."}
 +------------------------------------------------------------------+
 | [5] assistant   thinking: "step 1: the discount. and find the    |
 |                 price in the page."                              |
 |                 tool calls:                                      |
 |                   id call_3  calculate("120 * 0.8")              |
 |                   id call_4  search_result("results-1", "price") |
 | [6] tool        id call_3  "96.0"                                |
 | [7] tool        id call_4  "part 3, line 212: price 120 € ..."   |<---------- results/results-1.json
 +------------------------------------------------------------------+
 | [8] assistant   tool calls:                                      |
 |                   id call_5  calculate("96 * 1.19")              |
 | [9] tool        id call_5  "114.24"                              |
 +------------------------------------------------------------------+
 | [10] assistant  thinking: "all steps done."                      |
 |                 answer: "1. 20% off: 120 * 0.8 = 96              |
 |                          2. plus 19% tax: 96 * 1.19 = 114.24     |
 |                          You pay 114.24 €. The shop says ..."    |
 +------------------------------------------------------------------+
         |                                          |
         | every message, the moment it arrives     | the whole list without [0], after every message
         v                                          v
   log.jsonl  (one line each, never changed)    state.json  (what /open loads again)
```

And when the conversation gets too full, the model writes its checkpoint, and the list starts over:

```
 BEFORE: [0] system  [1] user  [2] ... [80] assistant         (e.g. 61,000 of 100,000 tokens)
                                    |
                                    |  "[from the program] CHECKPOINT ..."  ->  the model calls checkpoint("## Goal ...")
                                    v
 AFTER:  [0] system   1. who you are   2. skills   3. <checkpoint> ## Goal ... ## Open ... </checkpoint>
                                                         ^
                                                         +---- checkpoint.md
         (everything before is still in log.jsonl and results/)
```

### The same, in words

- **The system prompt comes first, and is built from parts.** First the soul, from `Ego/SOUL.md`: who the assistant is and how it works. Then the skills menu: one line per skill, taken from the header of each `skills/<name>/SKILL.md`. Then, once the model has written one, its checkpoint from `checkpoint.md`. The system prompt is built again from these files whenever needed, never edited by hand.
- **Your question comes next**, as a `user` message.
- **The model answers, maybe with thinking first.** Its thinking is kept in the conversation and the log; whether you see it is set by `PrintThinking`. Instead of answering right away, the model can ask for tools. Each tool call has an id, like `call_1`.
- **Tools run, and their results come back with the same id.** Several calls in one answer run at the same time. Their results go into the list in the order the model asked, and the id tells the model which result belongs to which call.
- **Skills arrive as a tool result.** The system prompt only lists them. When a task matches one, the model calls `load_skill`, and the skill's whole text comes back like any other tool result, here `[3]`. From then on, the model follows it.
- **A long result is pointed to, not given whole.** If a result is longer than `RESULT_LIMIT` characters, like the shop's page in `[4]`, it is saved as `results/results-1.json` in parts, and the model only gets a preview saying where it is. It finds what it needs with `search_result` (`[7]`) and reads a part with `read_result`. `fetch_page` is only an example here: any tool with a long answer is handled like this.
- **The final answer is a message without tool calls.** That ends the task (`[10]`).
- **Everything is logged.** Every message, the moment it arrives, is written as one line into `log.jsonl`, and the system prompt is written too whenever it changed. Nothing in the log is ever changed or removed.
- **The conversation is saved.** After every message, the whole list (without the system prompt, which is built fresh) is written into `state.json`. `/open` loads it again.
- **When it gets too full, it starts over from a checkpoint.** The model writes down where it stands and gives it to the `checkpoint` tool. The list is emptied down to a new system prompt with that checkpoint in it. The log and the results stay, so nothing is lost.

## How it works

### The server, the hub and the clients

The agent never prints. Whatever it has to say, it sends as an **event**: a small dict like `{"conversation": "trip", "kind": "answer", "text": "Hi"}`. It sends it to `agent.output`, a function it was given, and never knows who listens.

The one who listens is the **hub** (`classes/hub.py`). It knows which clients have which conversation open (its *watchers*), and passes every event of a conversation on to them. Usually that is one client: the one that sent the message. Open the same conversation in the window and in a terminal, and both show the answer while it arrives.

A client sends **requests**: `{"type": "message", "conversation": "trip", "text": "hello"}`. Requests and events travel as lines of JSON over a socket, one object per line (`server.py`, `classes/connection.py`).

| A client sends | | The server answers |
|---|---|---|
| `hello` | who it is | `hello`: its client number, the model, the tools, the skills |
| `new` | start a conversation | `opened` |
| `open` | open a saved one | `opened`: what was said so far, as events, and whether it is working |
| `close` | stop watching one | |
| `message` | a message for the model | the task's events: `user`, `thinking`, `answer`, `answer_end`, `tool_call`, `tool_result`, `note`, `error`, and `done` last. Or `refused`, if it is still working |
| `stop` | stop the running task | the task ends with the note `stopped`, then `done` |
| `list`, `rename`, `delete` | | `list` (every conversation with `busy`, `saved` and `last`: when you last wrote into it, in milliseconds), `renamed`, `deleted` (the last two go to every client) |
| `sandbox` | nothing more: what runs in the conversation's sandbox. `net` `"on"` / `"off"`: switch its network. `do` `"open"` with `name`, `"stop"`, `"stop_all"`: open or stop sandboxes | `sandbox`: the answer as text. A change goes to every client that has the conversation open |

All of them, with their fields, are listed at the top of `classes/hub.py`.

- **Several conversations work at once.** Each task runs in its own thread, with its own call to the model. One conversation does one task at a time: a message for one that is still working is refused, with a standard text.
- **A task doesn't need its client.** The hub keeps a working conversation in memory even when nobody watches it. A client that opens it in the middle gets the history from the log, and the running task's events so far, and then the rest as it happens.
- **Stopping.** `stop` sets `agent.stop_requested`. The agent looks at it at its safe points: before every model call, between two pieces of a streaming answer, and while it waits for a retry. The part of the answer that had arrived is kept, as the model's message, with a line saying the user stopped it. A half-received tool call is dropped, and tools that are running finish first, so the conversation stays one the provider accepts.

### Writing your own client

A client is any program that connects to the server and speaks those lines. In Python, `Connection` does the socket part:

```python
from classes.connection import Connection

server = Connection("127.0.0.1", 8765, "my-client")
server.send("new")                                   # start a conversation
name = None
while True:
    event = server.next()                            # waits for the next event
    if event["kind"] == "opened":
        name = event["conversation"]
        server.send("message", conversation=name, text="what is 17% of 2340?")
    elif event["kind"] == "answer":
        print(event["text"], end="", flush=True)     # a piece of the answer
    elif event["kind"] == "done":
        break
```

A Telegram bot, a web page or a script that runs every morning would all be this: a loop that turns something into requests, and events into something.

### The loop

Everything happens in `Agent.ask` in `classes/agent.py`:

1. Your message is added to the conversation, a list of messages.
2. The whole list is sent to the model. Its answer is printed while it arrives, then added to the list.
3. Did the model ask for tools? Then they run, their results are added, and it goes back to step 2.
4. No tools: that was the final answer, and the task is done.

The model only knows what is in that list. After every task, the hub saves it to `state.json`.

### The system prompt

It is built from parts, always in the same order, and is always the first message:

1. the soul (`Ego/SOUL.md`)
2. the skills menu: every skill's name and its one-line description
3. the checkpoint, once there is one
4. the workspace: what runs in the conversation's sandbox right now, what is mounted, and which sandboxes, folders and projects there are (only with Podman)

The same parts always give exactly the same text, so the provider's prompt cache stays valid. It is not saved in `state.json`: when a conversation is opened again, it gets a freshly built one, so a changed soul or a new skill is used right away. The log keeps every version of it.

### Tools

A tool is one Python file with two things: `TOOL`, which the model sees (name, description, arguments), and `run`, which the program executes. `functions/load_tools.py` finds every file in `tools/` at the start; there is no list to edit. The model never runs anything itself: it only asks, and the tool's code decides what really happens.

- All tool calls of one answer run at the same time, each in its own thread. The program waits until every one is done, then adds the results in the order the model asked, each with the id of its call.
- A tool never crashes the program. A wrong tool name, broken arguments or an error inside a tool comes back to the model as a text starting with `error:`, so every call always gets an answer.

See [`tools/README.md`](tools/README.md) for how to write one.

### Skills

A skill is a folder in `skills/` with a `SKILL.md` inside: a short header with `name` and `description`, then the instructions. Only the header goes into the system prompt. When a task matches, the model calls `load_skill` and gets the whole text. If there are no skills, the model doesn't get `load_skill` either.

See [`skills/README.md`](skills/README.md) for how to write one.

### Long results

A tool result longer than `RESULT_LIMIT` characters is saved as `results/results-<n>.json`, cut into parts of `RESULT_PART` characters. The model gets a preview: the result's name, its size, how many parts it has, and its start and end. Then:

- `search_result` searches it like `grep`, with grep's options (regex, ignore case, whole word, invert, lines before and after, only matching, count, max count). Every hit says its part and line number.
- `read_result` shows one whole part, never more, so a huge result can't fill the conversation.

If an answer from `search_result` is too long itself, it is saved as a new result, so the model can search that one again, narrower. Everything here is counted in characters, so it works the same with every model.

### Checkpoints

After every answer, the program checks how big the conversation is, using the token count the provider sends with every answer:

- **At the end of a task, above `CHECKPOINT_AT`:** the program asks the model for its checkpoint.
- **In the middle of a task, above `EMERGENCY_AT`:** right after the tool results, the program asks for an emergency checkpoint, in which the model also says where it is in the task.

The model writes its checkpoint in fixed sections (goal, decisions, facts, done, failed, open, files, last exchange) and gives it to the `checkpoint` tool. The tool saves it as `checkpoint.md`, empties the conversation, and builds the system prompt again, with the checkpoint in it. In an emergency, one message tells the model to go on from its checkpoint, and the task continues.

- The log and the saved results are never touched: every word is still there.
- `state.json` becomes empty with the next save, so `/open` starts from the checkpoint too.
- The checkpoint tool refuses when it wasn't asked for.
- A model that ignores the request is asked twice, then left alone for that task, so it is never asked forever.

### The log

`Conversations/<name>/log.jsonl` gets one line for every message: your questions, the model's answers (with their thinking and tool calls), tool results, and the program's own messages to the model. Before a message, the system prompt is written too, but only when it changed. The log is only ever added to, never changed, and never read by the program: whatever happens to the conversation, a message taken back, a checkpoint, a deleted `state.json`, what was said stays in it.

### When things fail

- A busy provider, a timeout or a lost connection is tried again up to 3 times, after 1, 2 and 4 seconds. A wrong key or a bad request is not.
- If a call fails before anything happened, your message is taken back, so you can simply send it again. Work that tools already did stays. The client gets an `error` event, and the conversation goes on.
- A client that sends something wrong (broken JSON, an unknown request, a bad name) gets a `problem` event. The server goes on.
- The server stops in the middle of a task: that task is cut off and not saved half-done. The conversation opens again as it was before the task, and everything the task said is in its `log.jsonl`.
- `state.json` and `checkpoint.md` are written into a temporary file first, then swapped in. A crash in the middle of writing never leaves half a file.

## Extending it

- **A tool:** a new `.py` file in `tools/`, with `TOOL` and `run`. See [`tools/README.md`](tools/README.md).
- **A skill:** a new folder in `skills/` with a `SKILL.md`. See [`skills/README.md`](skills/README.md).
- **A command:** one line in `COMMANDS` in `functions/commands.py`, and its part in `main.py` (and in `command` in `gui.py`).
- **A client:** see "Writing your own client" above.

Tools and skills are read once, when the server starts: restart it after adding or changing one.
