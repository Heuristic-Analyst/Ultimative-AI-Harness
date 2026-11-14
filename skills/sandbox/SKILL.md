---
name: sandbox
description: Use before you run code, install packages, or create, read or change files, and before you mount or unmount a folder.
---

# Working in the sandbox

Your sandbox is a throwaway Linux container. Everything you run happens there, never on the user's computer: you have no other way to run anything. You are root inside it. It belongs to this conversation alone: only you open and close it, and you can't reach any other conversation's sandbox.

## What you see of the user's computer

Only the folders the user wrote into `settings/folders.json`, each at `/workspace/<name>`. You can't change that list. `check_sandbox` shows it:

- **In every sandbox, always.** Mounted by themselves at every start. Other sandboxes see them too, so someone else may be working in them.
- **Folders you can mount** (`mount_folder`, or `open_sandbox` with `folders`). Some can only be in one sandbox at a time: if another sandbox has it, it is not available now.
- **One project** (`mount_project`, or `open_sandbox` with `project`). See the projects skill.

Each folder is either **read and write** or **read-only**. In a read-only one you can't create, change, rename or delete anything: don't try, and never work around it. The notebook engine (`Notebook_Engine`) is such a folder.

## What is kept and what is not

- Files in the mounted folders are the user's real files, and they stay. Closing the sandbox never touches them.
- Everything else inside (installed packages, files in /tmp or /root, running programs) is gone when the sandbox stops or restarts.
- Files in a read-write folder can be run like anywhere else, also programs you compiled and a venv you made there. All of it runs inside the sandbox.

## Steps

1. **Look first.** Your system prompt says what ran when this context started; later tool results are newer. If unsure: `check_sandbox` (which sandbox runs, what each one contains, the folders).
2. **Decide what to mount before you start.** Give every folder and the project the work needs to `open_sandbox(name, folders=[...], project="...")` right away: `mount_folder`, `unmount_folder`, `mount_project` and `unmount_project` restart the sandbox, which loses installs, running programs, open notebooks and terminals.
3. **Pick the sandbox by its Containerfile and settings.** It is exactly what you get. Notebooks need one with python3 (e.g. `python`). Its settings come from the user: memory, a GPU (`GPU yes`), the network. You can't change them; if a task needs more, tell the user.
4. **Work with sandbox_shell or terminal.** Small steps, read what each command prints. Big output: write it to a file in /workspace and search it with grep, instead of printing it all.
   - `sandbox_shell`: a fresh shell every call. Good for single, independent commands; several run at the same time.
   - `terminal`: a shell that stays open, like a terminal window. Use it when steps build on each other: `cd` into a folder, `export` variables, `source .venv/bin/activate`, then work there over many calls. Each answer ends with the folder it is in now. More than one at once: give them names (`terminal="server"`). Commands get no keyboard input, so use `-y` and similar flags.
5. **Long jobs** (over the time limit): start them in the background with their output in a file, `nohup python job.py > job.log 2>&1 &`, then check the file.
6. **When done**, tell the user where the results are, as the path on their computer that `check_sandbox` shows for that folder, and `close_sandbox`: it uses their memory while it runs.

## Good to know

- **The network is off.** Installing (`pip install`, `apt-get install`) needs it, and only the user can switch it on: they type `/sandbox net on`. You have no tool for it. Ask them, say what you want to install, call `notify_user`, and end your reply. If a package is needed often, suggest adding it to the sandbox's Containerfile, so it is there at every start.
- One sandbox per conversation. To switch to another kind, `close_sandbox`, then `open_sandbox`.
- Terminals end when the sandbox stops or restarts: after that, `cd` and activate again.
- A folder or project another sandbox has can't be mounted now: pick another one, or tell the user.
- The sandbox may stop by itself (out of memory). The files in the mounted folders are still there; open it again.
- After a checkpoint, your notes don't need to repeat what runs (the system prompt shows that), but they must say which files and notebooks matter and what each one is for.
