# Sandboxes

A sandbox is a throwaway Linux container ([Podman](https://podman.io)) where an agent runs everything: commands, installs, terminals, notebooks. It never runs anything on your computer itself.

Every conversation has its own. Its agent opens and closes it with its tools (`open_sandbox`, `close_sandbox`); you never have to. An agent can only reach its own sandbox, never another conversation's.

| Sandbox | What it is |
|---|---|
| `python` | Python 3.12 with numpy, pandas and matplotlib. The one notebooks need. |
| `ubuntu` | Plain Ubuntu 24.04. No Python. |
| `ai-lab` | PyTorch with CUDA, transformers and friends. Gets your NVIDIA GPU (`sandbox.json`). |

## How a sandbox looks

One folder per sandbox, with a file always called `Containerfile`, and optionally its settings, `sandbox.json`:

```
Sandboxes/
└── python/
    ├── Containerfile
    └── sandbox.json        optional
```

```dockerfile
FROM docker.io/library/python:3.12-slim
RUN pip install --no-cache-dir numpy pandas matplotlib
```

The folder's name is the sandbox's name: lowercase letters, digits and `-` only (Podman's rule for image names). The agent reads the Containerfiles (`check_sandbox`) to pick the sandbox that fits a task.

## sandbox.json: a sandbox's settings

Most sandboxes need none: then the defaults in `config.py` apply (2 GB memory, no GPU, network off). A sandbox that needs more gets a `sandbox.json` next to its Containerfile. **You** write it; the agent can read it (`check_sandbox`) but never change it: this folder can never be mounted into a sandbox, and no tool writes here.

```json
{
  "_about": "anything starting with _ is a note for you, and is skipped",
  "memory": "8g",
  "gpu": true,
  "network": false
}
```

| Setting | What it does | Left out |
|---|---|---|
| `_about` | A note for you. Skipped. | |
| `memory` | How much memory it may use, like `"4g"` or `"512m"`. | `SANDBOX_MEMORY` (2g) |
| `gpu` | `true`: it gets your NVIDIA GPUs. Needs a one-time setup, below. `false`: none. | no GPU |
| `network` | `true`: its network is **on** whenever the agent opens it, so you don't have to type `/sandbox net on`. You can still switch it off with `/sandbox net off`. `false`: off. | off |

Only these exist. Anything else (a typo too) makes the sandbox unusable until it is fixed, and `check_sandbox` and `/sandbox` say what is wrong, so nothing you didn't mean can reach Podman.

## The network

Off whenever the agent opens a sandbox (unless its `sandbox.json` says `"network": true`). Only you switch it, for the conversation you are in:

```
/sandbox net on
/sandbox net off
/sandbox            what runs here, and its network
```

You can also open and stop sandboxes yourself, though you never have to:

```
/sandbox open python     open that sandbox for the conversation you are in
/sandbox stop            stop this conversation's sandbox
/sandbox stop all        stop every running sandbox, in every conversation
```

The model is told with your next message what you did.

The agent has no tool for it. It asks you in the chat (and plays a sound, `notify_user`), and is told with your next message that you switched it. Your choice stays through a restart of the sandbox (mounting a folder), and ends when the sandbox is closed.

## The GPU (`"gpu": true`)

The sandbox gets every NVIDIA GPU, the same way on every system: `--device nvidia.com/gpu=all` (CDI). Podman can only do that once the NVIDIA Container Toolkit is set up, once per computer:

- **Linux:** install the NVIDIA driver and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Then check `nvidia-ctk cdi list` shows your GPUs; if not, `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`. Fedora and other SELinux systems also need `sudo setsebool -P container_use_devices=true`.
- **Windows:** install the NVIDIA driver on Windows (nothing else there). The toolkit goes into Podman's machine: `podman machine ssh`, install the toolkit in there, then `nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`.
- **Mac:** no NVIDIA GPUs exist there. Set `"gpu": false`.

Test it once by hand: `podman run --rm --device nvidia.com/gpu=all ubuntu nvidia-smi -L` must list your GPUs. If the toolkit is missing, opening the sandbox fails with a message that says so.

## What happens when an agent opens one

1. The image is built from the Containerfile. The first time takes a while; after that Podman's cache makes it quick, and a change you made to the Containerfile is in the very next start.
2. A container starts from it, with `--rm` (deleted when it stops), `no-new-privileges`, a few capabilities taken away, and limits: memory from its `sandbox.json` or `config.py`, and `SANDBOX_CPUS`, `SANDBOX_PIDS`. None of your environment variables are passed in (so no API key), and no port is opened.
3. Its network is disconnected right away, and checked. If it can't be sealed, the sandbox is stopped again.
4. It sees only the folders from `settings/folders.json`, each at `/workspace/<name>`, all `nosuid,nodev`:

| In `folders.json` | Inside | |
|---|---|---|
| `always` | `/workspace/<name>` | in every sandbox, read-only or read-write as you wrote it |
| `exclusive`, `shared` | `/workspace/<name>` | only what the agent mounted. An `exclusive` one is in one sandbox at a time |
| one project from `projects` | `/workspace/<project>` | read-write. One per sandbox, and no other sandbox can have it meanwhile |

Nothing installed at runtime survives a stop. If the agent needs a package often, add it to the Containerfile.

## When a sandbox ends

- The agent closes it (`close_sandbox`), you stop it (`/sandbox stop`, `/sandbox stop all`), its conversation is deleted, or the server stops (Ctrl+C, a closed terminal). A sandbox keeps running when you only close a client: the conversation's task may still need it. `/sandbox` shows every conversation that has one.
- The container is deleted with everything in it. **The folders on your computer are never touched** by that.
- A server that was killed hard can't stop its sandboxes. The next server start removes them first. Containers you started yourself are never touched: the program only removes the ones carrying its own labels.

## What keeps your computer safe

- **Rootless only.** If Podman runs with root rights, no sandbox starts (`SANDBOX_ROOTLESS_ONLY` in `config.py`): "root" inside a sandbox must only ever be you, never the real root.
- **Only the folders you named**, and never the program's own folders or your home folder (`settings/README.md`).
- **The program never runs anything from a mounted folder on your computer.** What the agent runs from there, it runs inside its sandbox.
- **You** are the last step: don't run files the agent wrote on your own computer without reading them.

## A new sandbox

Make a folder here with a `Containerfile` inside. Notebooks need `python3` in it; `sandbox_shell` and `terminal` need `bash` and `timeout` (coreutils), which every Debian- or Ubuntu-based image has. The agent sees the new sandbox the next time it calls `check_sandbox`.

Editing a Containerfile leaves the old image behind on disk, without a name. `podman image prune` removes such leftovers (of all your images, not only these).
