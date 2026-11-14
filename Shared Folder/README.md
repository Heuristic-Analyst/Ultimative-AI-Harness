# Shared Folder

The folders the default `settings/folders.json` points to. A sandbox never sees this folder itself, only the ones named there:

| Folder | In `folders.json` | What it is |
|---|---|---|
| `Notebook_Engine/` | `always`, read-only | The program that runs Jupyter notebooks inside a sandbox (`kernel.py`, `client.py`). Part of the harness. No sandbox can change it. |
| `Common/` | `always`, read-write | A place every sandbox can read and write. Made when a sandbox first needs it. |
| `Projects/` | `projects` | The projects. The agent creates them, and a sandbox mounts one at a time. Made when first needed. |

You can point `folders.json` anywhere else instead: see `settings/README.md`.

Nothing in here is ever run on your computer by the program. Read what the agent wrote before you run it yourself.
