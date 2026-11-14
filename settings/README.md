# settings

How the program talks to the model, and which folders of your computer a sandbox may see. `model.json` is read once, when the server starts: change it, then start `python server.py` again. `folders.json` is read every time it is needed, so a change counts from the next sandbox start.

| File | What it is |
|---|---|
| `model.json` | Which model, and how to use it. |
| `folders.json` | The only folders of your computer a sandbox can see, and how. |

## model.json

```json
{
  "Model": "deepseek/deepseek-flash",
  "Stream": true,
  "Effort": "high",
  "PrintThinking": true,
  "ContextLimit": 100000
}
```

| Setting | Required | Default | What it does |
|---|---|---|---|
| `Model` | yes | | The model, as LiteLLM names it: `provider/model`. |
| `Stream` | no | `false` | `true`: the answer is printed piece by piece while it arrives. `false`: all at once, when it is complete. |
| `Effort` | no | the model's own | How hard the model thinks before it answers: `low`, `medium` or `high` (DeepSeek: `low`, `high`, `max`). A model that can't think simply ignores it. |
| `PrintThinking` | no | `false` | `true`: the model's thinking is printed too, under `THINKING:`. `false`: only the answer. This is about `main.py`, the terminal: the window (`gui.py`) always has the thinking, folded under a line you can click. Either way it is kept in the conversation and the log. |
| `ContextLimit` | no | `100000` | Tokens a conversation may have at most. Checkpoints are written at 60% and 80% of it (`CHECKPOINT_AT`, `EMERGENCY_AT` in `config.py`). **Set it to your model's real context window, or a bit below**: too high, and the model's real limit is hit before any checkpoint. |

`config.py` reads this file into `MODEL`, `STREAM`, `EFFORT`, `PRINT_THINKING` and `CONTEXT_LIMIT`. A missing `model.json` stops the program at the start with an error naming the file, and so does a file that isn't valid JSON (the error says where in the file).

## Changing the model

Only `Model` has to change, plus the key in `.env` if it's a new provider:

| Provider | `Model` | Line in `.env` |
|---|---|---|
| DeepSeek | `deepseek/deepseek-flash` | `DEEPSEEK_API_KEY=sk-...` |
| Anthropic | `anthropic/<model>` | `ANTHROPIC_API_KEY=sk-ant-...` |
| OpenAI | `openai/<model>` | `OPENAI_API_KEY=sk-...` |
| Ollama (local) | `ollama/llama3` | none needed |

The key's name is always the part before the `/` in capitals, plus `_API_KEY`. The key itself never goes in here: it belongs in `.env`, which is never uploaded. Then check `ContextLimit` and `Effort`: both depend on the model.

## Good to know

- **JSON is strict.** `true` and `false` in lowercase, text in double quotes `"..."`, a comma between settings but none after the last one, and no comments.
- **Tokens, not characters.** `ContextLimit` is the only size counted in tokens, because a model's window is counted in tokens. The sizes for long tool results (`RESULT_LIMIT` and the others in `config.py`) are counted in characters, so they work the same with every model.

## folders.json

The agent runs everything in a sandbox, and a sandbox sees nothing of your computer except the folders named here. You write this file. The agent can read what it says (`check_sandbox`), but it can't change it: no tool writes here, and `settings/` can never be mounted.

```json
{
  "always": [
    {"name": "Common", "path": "Shared Folder/Common", "access": "rw"},
    {"name": "Notebook_Engine", "path": "Shared Folder/Notebook_Engine", "access": "ro"}
  ],
  "exclusive": [
    {"name": "papers", "path": "~/Documents/papers", "access": "ro"}
  ],
  "shared": [
    {"name": "datasets", "path": "/mnt/data/sets", "access": "ro"}
  ],
  "projects": "Shared Folder/Projects"
}
```

| Key | Who gets it | How many sandboxes at once |
|---|---|---|
| `always` | every sandbox, from its start | any number |
| `exclusive` | a sandbox whose agent mounts it (`mount_folder`, or `open_sandbox` with `folders`) | **one** |
| `shared` | a sandbox whose agent mounts it | any number |
| `projects` | **one path**, the folder that holds the projects. It is never mounted itself: a sandbox mounts one project (one subfolder), always read-write | one sandbox per project, one project per sandbox |

Every folder in the three lists has exactly these settings:

| Setting | What it is |
|---|---|
| `name` | What the tools call it, and where it is inside: `/workspace/<name>`. Letters, digits, `- _ .` only. No name twice, in any spelling. |
| `path` | Absolute, or relative to the program's folder (where `config.py` is). `~` is your home folder. A folder that doesn't exist yet is made, empty, when a sandbox first needs it. |
| `access` | `"ro"`: read-only, nothing in it can be changed, renamed or deleted from inside. `"rw"`: read and write. |

Keys starting with `_` (like `_about`) are notes for you, and are skipped.

**Projects.** With `"projects"` set, the agent can list the projects (`check_projects`), create, mount, unmount, rename and delete them. Leave the key out (or `""`), and there are no projects at all: every project tool says so, and nothing creates a folder for you.

**The notebook engine.** The `nb_*` tools look for the folder *named* `Notebook_Engine` (`NOTEBOOK_ENGINE` in `config.py`) and run the `client.py` in it, inside the sandbox. Keep it in `always` and `"ro"`, so every sandbox has it and none can change it.

### What is refused

One mistake makes the whole file unusable, and then **no sandbox starts** until it is fixed. The server says what is wrong when it starts, and the agent is told when it tries to open a sandbox.

- **The program's own folder, anything above it, and its folders** (`classes`, `functions`, `tools`, `skills`, `settings`, `Sandboxes`, `Ego`, `Conversations`), not even read-only. A sandbox that could write there could change the code that runs on your computer, and one that could read there would see your `.env`.
- **Your home folder, or anything above it.** Writing `~/.bashrc` or `~/.ssh` would be running things on your computer. Name single folders inside it.
- **A folder inside another folder of this file** (or the same one twice). It would get around "read-only" and "one sandbox at a time".
- A path that is a file, an `access` other than `ro` / `rw`, an unknown key, a name used twice.

Links are followed before a path is checked, so a link into one of these places is refused too.

### Good to know

- **Mounting restarts the sandbox.** Podman can't add a folder to a running container. The agent knows, and is told to mount first and install afterwards.
- **The agent can run what it writes there, inside its sandbox.** Scripts, compiled programs, a venv: all of that works in a `"rw"` folder, and all of it happens in the container. The program itself never runs or opens what the agent wrote there.
- **Still your files.** In a `"rw"` folder the agent can change and delete everything. Give it folders you would give a colleague, and keep `"ro"` for anything it only has to read.
- **Don't run what the agent wrote on your own computer** without reading it. The sandbox protects you from the agent's code, but only as long as it stays in there.
- **SELinux (Fedora and others).** Podman relabels a mounted folder so the container may use it. One more reason to name single work folders, never a system folder.

