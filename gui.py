# run it:  python gui.py         (the server must be running: python server.py)
# the chat in a window: the conversations on the left, the one you are in on the right. several conversations can
# work at the same time: send a message in one, click another one and go on there. a dot marks the ones that work.
#
# this is a CLIENT, like main.py: it holds no agent, calls no model and saves nothing. it sends what you do to the
# server (classes/connection.py) and draws the events that come back. close the window in the middle of a task: the
# task goes on in the server, and is there when you open the window again.
#
# how it is built:
#   Gui    the window: the list on the left, the top line, the input box. it reads the events from the server and
#          gives each one to the View of its conversation
#   View   one conversation: its own text area, and how each event is drawn into it. every conversation you opened
#          keeps its View, also while another one is shown, so an answer keeps arriving in the background
# markdown is read by functions/markdown.py, which says what each piece of text is ("bold", "h1", ...). how that
# looks is decided here, in View.styles.

import sys
import webbrowser

try:
    import tkinter as tk
    from tkinter import ttk, font as tkfont, messagebox, simpledialog
except ImportError:
    raise SystemExit("this window needs tkinter, which this python does not have.\n"
                     "  windows/mac: install python from python.org (it brings tkinter along)\n"
                     "  debian/ubuntu: sudo apt install python3-tk\n"
                     "main.py works in a terminal without it")

from config import HOST, PORT
from classes.connection import Connection
from functions.markdown import parse

# --- the look: change THEME to "dark" for a dark window ---
THEME = "light"
THEMES = {
    "light": {"page": "#FFFFFF", "side": "#F5F5F7", "picked": "#E3E3E8", "text": "#1D1D1F", "muted": "#6E6E73",
              "faint": "#A1A1A6", "line": "#E5E5EA", "accent": "#4F46E5", "accent_dark": "#4338CA",
              "on_accent": "#FFFFFF", "user": "#EEF0FF", "code": "#F4F4F6", "error": "#C0392B", "stop": "#D9483B",
              "select": "#C7D2FE"},
    "dark": {"page": "#1E1E22", "side": "#17171A", "picked": "#2C2C33", "text": "#ECECF1", "muted": "#9A9AA5",
             "faint": "#6B6B76", "line": "#2E2E36", "accent": "#818CF8", "accent_dark": "#6366F1",
             "on_accent": "#111114", "user": "#2A2B45", "code": "#27272D", "error": "#F87171", "stop": "#EF6A5B",
             "select": "#3F4580"},
}
C = THEMES[THEME]                                    # the colours in use, e.g. C["accent"]

SIDE_WIDTH = 250                                     # how wide the list of conversations is, in pixels
COLUMN = 820                                         # how wide the text of a conversation is at most: in a wider
                                                     # window it stays in the middle, so lines stay readable
TEXT_FONTS = ["Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Noto Sans", "Ubuntu", "DejaVu Sans"]
CODE_FONTS = ["Cascadia Code", "SF Mono", "Menlo", "JetBrains Mono", "Consolas", "DejaVu Sans Mono", "Courier New"]
DOTS = "\u00b7\u00b7\u00b7"                            # the three dots at the right of every conversation in the list
HINT = "Enter sends  ·  Shift+Enter makes a new line  ·  /help shows the commands"
HELP = """commands:
  /new                   start a new conversation
  /open <name>           continue a saved conversation (or click it on the left)
  /list                  show the conversations
  /rename <new>          rename this conversation.  /rename <old> <new>: another one
  /delete [name]         delete this conversation, or the one named, with everything in it
  /stop                  stop the running task (the same as the Stop button)
  /sandbox               this conversation's sandbox (folders, network), and all sandboxes
  /sandbox net on|off    switch its internet on or off. only you can, also while the agent works
  /sandbox open <name>   open that sandbox for this conversation yourself (the agent does it too)
  /sandbox stop          stop this conversation's sandbox. its folders stay
  /sandbox stop all      stop every running sandbox, in every conversation
  /help                  show this list
  /exit                  close the window (what is working goes on in the server)
click the three dots of a conversation on the left (or right-click it) to rename or delete it. click a ▸ line to open the thinking or a tool call."""


def first_font(wanted, fallback):
    """the first of these fonts this computer has"""
    have = set(tkfont.families())
    for family in wanted:
        if family in have:
            return family
    return fallback


class View:
    """one conversation in the window: a text area, and how every event is drawn into it"""

    def __init__(self, gui, name):
        self.gui = gui
        self.name = name
        self.busy = False                            # is this conversation working right now?
        self.empty = True                            # nothing said in it yet?
        self.tokens = 0                              # how big it is, as of its last answer
        self.live = None                             # what is streaming in right now: {"kind": "answer", "text":
                                                     # ..., "dirty": ...} or {"kind": "thinking", "fold": n}
        self.folds = {}                              # fold number -> is it open? (the ▸ lines: thinking, tool calls)
        self.tools = {}                              # tool call id -> its fold number, to put the result there
        self.links = 0                               # how many links were drawn, for their tag names
        self.live_links = []                         # the link tags of the answer that is streaming in

        self.frame = tk.Frame(gui.body, bg=C["page"])    # the text area and its scrollbar. shown or hidden as one
        self.text = tk.Text(self.frame, wrap="word", bd=0, highlightthickness=0, padx=28, pady=18,
                            bg=C["page"], fg=C["text"], font=gui.fonts["text"], spacing1=2, spacing3=2,
                            selectbackground=C["select"], selectforeground=C["text"],
                            inactiveselectbackground=C["select"], insertwidth=0,
                            state="disabled")        # disabled = you can't type in it. the program switches that
                                                     # off for a moment whenever it writes (see write)
        scroll = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview,
                               style="Thin.Vertical.TScrollbar")
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.bind("<Button-1>", lambda event: self.text.focus_set(), add="+")   # so ctrl+c copies a selection
        self.text.bind("<Configure>", self.center)
        self.styles()

    def center(self, event):
        """the window changed its size: keep the text in a column in the middle"""
        side = max(28, (event.width - COLUMN) // 2)
        if side != int(self.text.cget("padx")):      # only when it really changes: changing it asks for a new layout
            self.text.configure(padx=side)

    def styles(self):
        """how each kind of text looks. a "tag" is a name for a look: text is written with tags, and gets theirs.
        when two tags of one piece both set the font, the one made LATER here wins (code over bold)"""
        t, f = self.text, self.gui.fonts
        t.tag_configure("gap", font=f["gap"])                            # an empty line, but only half as high
        t.tag_configure("user", background=C["user"], lmargin1=14, lmargin2=14, rmargin=14, spacing1=9, spacing3=9)
        t.tag_configure("note", foreground=C["faint"], font=f["small"])
        t.tag_configure("error", foreground=C["error"])
        t.tag_configure("fold_head", foreground=C["muted"], font=f["small"], spacing1=3, spacing3=3)
        t.tag_configure("fold_body", foreground=C["muted"], font=f["code_small"], background=C["code"],
                        lmargin1=16, lmargin2=16, rmargin=16)
        # markdown (the tag names come from functions/markdown.py)
        t.tag_configure("italic", font=f["italic"])
        t.tag_configure("bold", font=f["bold"])
        t.tag_configure("quote", foreground=C["muted"], lmargin1=18, lmargin2=18, font=f["italic"])
        t.tag_configure("list1", lmargin1=14, lmargin2=32)               # lmargin2: where a wrapped line goes on
        t.tag_configure("list2", lmargin1=38, lmargin2=56)
        t.tag_configure("list3", lmargin1=62, lmargin2=80)
        t.tag_configure("h3", font=f["h3"], spacing1=8, spacing3=3)
        t.tag_configure("h2", font=f["h2"], spacing1=10, spacing3=4)
        t.tag_configure("h1", font=f["h1"], spacing1=12, spacing3=5)
        t.tag_configure("code", font=f["code"], background=C["code"])
        t.tag_configure("codeblock", font=f["code"], background=C["code"], lmargin1=14, lmargin2=14, rmargin=14,
                        spacing1=1, spacing3=1, wrap="char")
        t.tag_configure("table", font=f["code"], lmargin1=14, lmargin2=14, wrap="char")
        t.tag_configure("rule", font=f["rule"], background=C["line"])    # a line across: a very low, grey line
        t.tag_configure("link", foreground=C["accent"], underline=True)
        t.tag_raise("sel")                           # what you select with the mouse shows over every background

    # --- writing into the text area ---
    def write(self, text, tags=(), at="end-1c"):
        """put text into the text area, at its end (or at `at`). if you were reading the end, it scrolls along"""
        at_end = self.text.yview()[1] > 0.995        # is the end visible? (you scrolled up: stay where you are)
        self.text.configure(state="normal")
        self.text.insert(at, text, tags)
        self.text.configure(state="disabled")
        if at_end:
            self.text.see("end")

    def markdown(self, text):
        """write markdown at the end. returns the tags of the links in it"""
        made = []
        for piece, tags, link in parse(text):
            if link:                                 # every link gets a tag of its own, which knows its address
                self.links += 1
                tag = "link-" + str(self.links)
                self.text.tag_bind(tag, "<Button-1>", lambda event, url=link: webbrowser.open(url))
                self.text.tag_bind(tag, "<Enter>", lambda event: self.text.configure(cursor="hand2"))
                self.text.tag_bind(tag, "<Leave>", lambda event: self.text.configure(cursor=""))
                tags = tags + (tag,)
                made.append(tag)
            self.write(piece, tags)
        return made

    # --- folds: a line with ▸ in front. click it, and what is under it shows or hides ---
    def fold(self, title):
        """start a fold with this title, closed. returns its number. what belongs under it is written with
        self.body(number) as tags"""
        number = len(self.folds) + 1
        self.folds[number] = False
        head, body = "head-" + str(number), "body-" + str(number)
        self.text.tag_configure(body, elide=True)    # elide = hidden
        self.text.tag_bind(head, "<Button-1>", lambda event: self.toggle(number))
        self.text.tag_bind(head, "<Enter>", lambda event: self.text.configure(cursor="hand2"))
        self.text.tag_bind(head, "<Leave>", lambda event: self.text.configure(cursor=""))
        self.write("▸ " + title + "\n", ("fold_head", head))
        return number

    def body(self, number):
        return ("fold_body", "body-" + str(number))

    def toggle(self, number):
        """open or close a fold: show or hide what is under it, and turn its arrow"""
        self.folds[number] = not self.folds[number]
        head = "head-" + str(number)
        self.text.tag_configure("body-" + str(number), elide=not self.folds[number])
        start = self.text.tag_ranges(head)[0]        # where the fold's line starts: its first character is the arrow
        self.text.configure(state="normal")
        self.text.delete(start, str(start) + " +1c")
        self.text.insert(start, "▾" if self.folds[number] else "▸", ("fold_head", head))
        self.text.configure(state="disabled")

    # --- the events (they are listed in classes/agent.py and classes/hub.py) ---
    def draw(self, event):
        """draw one event of this conversation"""
        kind = event["kind"]
        if kind == "user":                           # a message to the model: yours, or one from another client
            self.end()
            self.empty = False
            self.write("\n", ("gap",))
            self.write(event["text"] + "\n", ("user",))
            self.write("\n", ("gap",))
        elif kind == "thinking":                     # a piece of thinking: under a fold, as it arrives
            if not self.live or self.live["kind"] != "thinking":
                self.end()
                self.live = {"kind": "thinking", "fold": self.fold("Thinking")}
            self.write(event["text"], self.body(self.live["fold"]))
        elif kind == "answer":                       # a piece of the answer: collected, and drawn as markdown a
            if not self.live or self.live["kind"] != "answer":   # few times a second (see flush)
                self.end()
                self.write("\n", ("gap",))
                self.text.mark_set("live", "end-1c")           # a mark = a place in the text that we can find
                self.text.mark_gravity("live", "left")         # again. left: it stays in front of what is written
                self.live = {"kind": "answer", "text": "", "dirty": False}   # at its place: where the answer starts
            self.live["text"] += event["text"]
            self.live["dirty"] = True
        elif kind == "answer_end":
            self.end()
        elif kind == "tool_call":                    # a fold: the tool's name on the line, its arguments under it
            self.end()
            args = " ".join(event["args"].split())   # on one line
            number = self.fold(event["name"] + "  " + (args if len(args) <= 90 else args[:90] + " …"))
            self.write(event["name"] + "(" + event["args"] + ")", self.body(number))
            mark = "result-" + str(number)           # where the result goes when it arrives: right behind the call,
            self.text.mark_set(mark, "end-1c")       # also when other things were written below it meanwhile
            self.text.mark_gravity(mark, "left")
            self.write("\n", self.body(number))
            self.tools[event["id"]] = number
        elif kind == "tool_result":
            number = self.tools.pop(event["id"], None)
            if number is None:                       # a result whose call we never saw: under a fold of its own
                number = self.fold(event["name"] + "  (result)")
                self.write(event["text"] + "\n", self.body(number))
            else:
                self.write("\n→ " + event["text"], self.body(number), at="result-" + str(number))
        elif kind in ("note", "refused"):            # something the program says
            self.end()
            self.write(event["text"] + "\n", ("note",))
        elif kind == "error":
            self.end()
            self.write("error: " + event["text"] + "\n", ("error",))

    def flush(self):
        """draw the answer that is streaming in again, as markdown, if new pieces arrived since the last time:
        everything from where it starts (the mark "live") to the end is replaced. markdown can't be drawn piece by
        piece: "**bo" only becomes bold once "ld**" has arrived"""
        if not self.live or self.live["kind"] != "answer" or not self.live["dirty"]:
            return
        self.live["dirty"] = False
        top, bottom = self.text.yview()              # which part of the text is visible now (0 = start, 1 = end)
        at_end = bottom > 0.995
        self.text.configure(state="normal")
        self.text.delete("live", "end-1c")
        self.text.configure(state="disabled")
        for tag in self.live_links:                  # the links of the old drawing are gone with it
            self.text.tag_delete(tag)
        self.live_links = self.markdown(self.live["text"])
        if at_end:
            self.text.see("end")
        else:                                        # you scrolled up to read: stay exactly where you were
            self.text.yview_moveto(top)

    def end(self):
        """what was streaming in is complete: draw it one last time, and nothing is "live" anymore"""
        if self.live and self.live["kind"] == "answer":
            self.live["dirty"] = True
            self.flush()
            self.live_links = []
        elif self.live and self.live["kind"] == "thinking":
            self.write("\n", self.body(self.live["fold"]))
        self.live = None


class Gui:
    def __init__(self, root, server):
        self.root = root
        self.server = server                         # the connection to the server (classes/connection.py)
        self.me = None                               # this client's number at the server
        self.model = ""
        self.limit = 0                               # tokens a conversation may have (the server's ContextLimit)
        self.views = {}                              # conversation name -> its View: every one you opened
        self.current = None                          # the name of the one that is shown
        self.working = set()                         # the names of the conversations that work right now
        self.picking = False                         # True while the program itself selects a line in the list
        self.closed = False                          # the server is gone

        family = first_font(TEXT_FONTS, "TkDefaultFont")
        mono = first_font(CODE_FONTS, "TkFixedFont")
        self.fonts = {"text": tkfont.Font(family=family, size=11),
                      "bold": tkfont.Font(family=family, size=11, weight="bold"),
                      "italic": tkfont.Font(family=family, size=11, slant="italic"),
                      "small": tkfont.Font(family=family, size=10),
                      "tiny": tkfont.Font(family=family, size=9),
                      "title": tkfont.Font(family=family, size=12, weight="bold"),
                      "h1": tkfont.Font(family=family, size=17, weight="bold"),
                      "h2": tkfont.Font(family=family, size=14, weight="bold"),
                      "h3": tkfont.Font(family=family, size=12, weight="bold"),
                      "code": tkfont.Font(family=mono, size=10),
                      "code_small": tkfont.Font(family=mono, size=9),
                      "gap": tkfont.Font(family=family, size=5),
                      "rule": tkfont.Font(family=family, size=1)}
        self.build()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)   # the window's own close button
        self.poll()

    # --- building the window ---
    def build(self):
        self.root.title("AI Harness")
        self.root.geometry("1120x740")
        self.root.minsize(720, 460)
        self.root.configure(bg=C["page"])

        style = ttk.Style()
        style.theme_use("clam")                      # the one ttk theme whose colours can all be changed
        style.configure("Side.Treeview", background=C["side"], fieldbackground=C["side"], foreground=C["text"],
                        rowheight=34, borderwidth=0, font=self.fonts["small"])
        style.map("Side.Treeview", background=[("selected", C["picked"])], foreground=[("selected", C["text"])])
        style.layout("Side.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])   # no border around the list
        style.configure("Thin.Vertical.TScrollbar", troughcolor=C["page"], background=C["line"],
                        bordercolor=C["page"], lightcolor=C["line"], darkcolor=C["line"], width=10)
        style.map("Thin.Vertical.TScrollbar", background=[("active", C["faint"])])
        style.layout("Thin.Vertical.TScrollbar",     # only the bar itself, no arrows at its ends
                     [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                         ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])

        # the left side: the conversations
        side = tk.Frame(self.root, bg=C["side"], width=SIDE_WIDTH)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)                   # keep the width, whatever is inside
        tk.Label(side, text="AI Harness", bg=C["side"], fg=C["text"], font=self.fonts["title"],
                 anchor="w").pack(fill="x", padx=18, pady=(18, 10))
        self.button(side, "+  New conversation", self.new, C["accent"], C["on_accent"]).pack(fill="x", padx=14)
        tk.Label(side, text="CONVERSATIONS", bg=C["side"], fg=C["faint"], font=self.fonts["tiny"],
                 anchor="w").pack(fill="x", padx=18, pady=(18, 4))
        self.list = ttk.Treeview(side, style="Side.Treeview", show="tree", selectmode="browse", columns=("more",))
        self.list.column("#0", stretch=True)         # the name: takes all the room there is
        self.list.column("more", width=34, minwidth=34, stretch=False, anchor="center")   # the three dots at the
        self.list.pack(fill="both", expand=True, padx=(6, 6), pady=(0, 10))               # right of every line
        self.list.tag_configure("working", foreground=C["accent"])
        self.list.bind("<<TreeviewSelect>>", self.picked)
        self.list.bind("<Button-1>", self.list_click)    # a click on the three dots: the menu (rename, delete)
        self.list.bind("<Motion>", self.list_hover)      # a hand over the dots, so they look like a button
        self.list.bind("<Button-3>", self.list_menu)     # right click (windows, linux)
        self.list.bind("<Button-2>", self.list_menu)     # right click on some macs
        tk.Frame(self.root, bg=C["line"], width=1).pack(side="left", fill="y")   # a thin line next to the list

        # the right side: the top line, the conversation, the input box
        main = tk.Frame(self.root, bg=C["page"])
        main.pack(side="left", fill="both", expand=True)

        top = tk.Frame(main, bg=C["page"])
        top.pack(fill="x", padx=24, pady=(14, 10))
        self.title = tk.Label(top, text="", bg=C["page"], fg=C["text"], font=self.fonts["title"])
        self.title.pack(side="left")
        self.state = tk.Label(top, text="", bg=C["page"], fg=C["accent"], font=self.fonts["small"])
        self.state.pack(side="left", padx=10)
        self.info = tk.Label(top, text="", bg=C["page"], fg=C["faint"], font=self.fonts["small"])
        self.info.pack(side="right")
        tk.Frame(main, bg=C["line"], height=1).pack(fill="x")

        bottom = tk.Frame(main, bg=C["page"])        # packed BEFORE the conversation, so it keeps its room when
        bottom.pack(side="bottom", fill="x", padx=24, pady=(8, 12))   # the window gets small
        box = tk.Frame(bottom, bg=C["page"], highlightthickness=1, highlightbackground=C["line"],
                       highlightcolor=C["accent"])   # the frame around the input: accent-coloured while you type
        box.pack(fill="x")
        self.send_button = self.button(box, "Send", self.send_or_stop, C["accent"], C["on_accent"])
        self.send_button.pack(side="right", padx=8, pady=8, anchor="s")
        self.entry = tk.Text(box, height=3, wrap="word", bd=0, highlightthickness=0, padx=12, pady=10,
                             bg=C["page"], fg=C["text"], insertbackground=C["text"], font=self.fonts["text"],
                             selectbackground=C["select"], selectforeground=C["text"], undo=True)
        self.entry.pack(side="left", fill="both", expand=True)
        self.entry.bind("<Return>", self.on_return)
        self.entry.bind("<FocusIn>", lambda event: box.configure(highlightbackground=C["accent"]))
        self.entry.bind("<FocusOut>", lambda event: box.configure(highlightbackground=C["line"]))
        self.hint = tk.Label(bottom, text=HINT, bg=C["page"], fg=C["faint"], font=self.fonts["tiny"], anchor="w")
        self.hint.pack(fill="x", pady=(6, 0))

        self.body = tk.Frame(main, bg=C["page"])     # the Views are put in here, one shown at a time
        self.body.pack(fill="both", expand=True)
        self.entry.focus_set()

    def button(self, parent, text, action, colour, text_colour):
        """a flat button. (a Label, because tkinter's own Button can't be coloured on a mac)"""
        label = tk.Label(parent, text=text, bg=colour, fg=text_colour, font=self.fonts["small"], padx=16, pady=7,
                         cursor="hand2")
        label.bind("<Button-1>", lambda event: action())
        return label

    # --- the events from the server ---
    def poll(self):
        """25 times a second: take what the server sent, and draw the answers that are streaming in"""
        for _ in range(400):                         # at most 400 events per round, so the window stays awake
            event = self.server.next(0)
            if event is None:
                break
            try:
                self.handle(event)
            except tk.TclError:                      # the window is closing
                return
        for view in self.views.values():
            view.flush()
        self.root.after(40, self.poll)

    def handle(self, event):
        """do what one event from the server asks for"""
        kind = event["kind"]
        name = event.get("conversation")
        view = self.views.get(name)

        if kind == "hello":                          # the server's answer to our connecting
            self.me, self.model, self.limit = event["client"], event["model"], event["limit"]
            self.server.send("new")                  # a new conversation at every start, like main.py
            self.server.send("list")
        elif kind == "opened":                       # a conversation we asked for: everything about it
            self.opened(event)
        elif kind == "list":
            self.fill_list(event["conversations"])
        elif kind == "status":                       # some conversation started or ended a task
            if event["busy"]:
                self.working.add(name)
            else:
                self.working.discard(name)
            if view:
                view.busy = event["busy"]
            self.server.send("list")                 # the list shows who works, and a new one may be saved now
            self.update_top()
        elif kind == "done":                         # a task ended: how big the conversation is now
            if view:
                view.end()
                view.tokens = event["tokens"]
            self.update_top()
        elif kind == "renamed":
            if event["old"] in self.views:
                self.views[event["new"]] = self.views.pop(event["old"])
                self.views[event["new"]].name = event["new"]
            if self.current == event["old"]:
                self.current = event["new"]
            self.server.send("list")
            self.update_top()
        elif kind == "deleted":
            if view:
                view.frame.destroy()
                del self.views[name]
            if self.current == name:                 # the one that was shown is gone: start a new one
                self.current = None
                self.server.send("new")
            self.server.send("list")
        elif kind == "problem":                      # a request that could not be done: the server says why
            self.note(event["text"])
        elif kind == "sandbox":                      # the answer to /sandbox, or someone switched the network
            if view:
                view.draw({"kind": "note", "text": event["text"]})
        elif kind == "closed":                       # the server is gone: nothing works without it
            self.closed = True
            self.note("the server was stopped. start it again (python server.py), then this window")
            self.state.configure(text="no server", fg=C["error"])
        elif view:                                   # everything else is drawn in its conversation: user, thinking,
            view.draw(event)                         # answer, tool_call, tool_result, note, error, refused

    def opened(self, event):
        """a conversation was opened: make its View, draw what was said so far, and show it"""
        name = event["conversation"]
        if name in self.views:                       # opened before: start it over, from what the server says now
            self.views[name].frame.destroy()
        view = View(self, name)
        self.views[name] = view
        for old in event["history"] + event["live"]:     # history: what was said. live: the task that runs now
            view.draw(old)
        if not event["busy"]:
            view.end()
        view.busy = event["busy"]
        view.tokens = event["tokens"]
        view.empty = not event["history"] and not event["live"]
        view.text.see("end")
        self.show(name)

    # --- showing a conversation ---
    def show(self, name):
        """put this conversation's View in front"""
        old = self.views.get(self.current)
        if old and self.current != name:
            old.frame.pack_forget()
            if old.empty and not old.busy:           # a new one in which nothing was said: forget it, so empty
                self.server.send("close", conversation=self.current)   # ones don't pile up
                old.frame.destroy()
                del self.views[self.current]
                self.server.send("list")
        self.current = name
        self.views[name].frame.pack(fill="both", expand=True)
        self.update_top()
        self.pick_in_list()
        self.entry.focus_set()

    def update_top(self):
        """the top line and the button: which conversation, is it working, how full is it"""
        view = self.views.get(self.current)
        if self.closed or not view:
            return
        self.title.configure(text=self.current)
        self.state.configure(text="working …" if view.busy else "", fg=C["accent"])
        self.info.configure(text=(format(view.tokens, ",") + " / " + format(self.limit, ",") + " tokens   ·   "
                                  if self.limit else "") + self.model)
        self.send_button.configure(text="Stop" if view.busy else "Send",
                                   bg=C["stop"] if view.busy else C["accent"])

    def note(self, text):
        """a line from the program, in the conversation that is shown"""
        view = self.views.get(self.current)
        if view:
            view.draw({"kind": "note", "text": text})

    # --- the list on the left ---
    def fill_list(self, conversations):
        """draw the list again: the one you wrote into last on top, a dot in front of the ones that work"""
        self.working = {c["name"] for c in conversations if c["busy"]}
        self.picking = True                          # deleting the lines "unselects": that is not you picking
        self.list.delete(*self.list.get_children())
        ordered = sorted(conversations, key=lambda c: c["name"], reverse=True)   # same time: the newer name first
        ordered.sort(key=lambda c: (c["saved"], -(c.get("last") or 0)))   # then by when you last wrote into it
                                                     # ("last", from Conversations/last_input.json), newest first.
                                                     # a new one, with nothing said yet (not saved), is on top
        for c in ordered:
            self.list.insert("", "end", iid=c["name"], text=("●  " if c["busy"] else "    ") + c["name"],
                             values=(DOTS,), tags=("working",) if c["busy"] else ())
        self.picking = False
        self.pick_in_list()

    def pick_in_list(self):
        """mark the conversation that is shown in the list"""
        self.picking = True
        if self.current and self.list.exists(self.current):
            self.list.selection_set(self.current)
            self.list.see(self.current)
        self.root.after_idle(self.picked_done)       # the list tells about the selection a moment later

    def picked_done(self):
        self.picking = False

    def picked(self, event):
        """you clicked a conversation: show it. not opened in this window yet: ask the server for it first"""
        chosen = self.list.selection()
        if self.picking or not chosen or chosen[0] == self.current:
            return
        self.go_to(chosen[0])

    def go_to(self, name):
        if name in self.views:
            self.show(name)
        else:
            self.server.send("open", conversation=name)   # answered with "opened", which shows it

    def on_dots(self, event):
        """the conversation whose three dots the mouse is on, or None"""
        if self.list.identify_column(event.x) != "#1":   # "#1" = the first column after the name: the dots
            return None
        return self.list.identify_row(event.y) or None

    def list_hover(self, event):
        self.list.configure(cursor="hand2" if self.on_dots(event) else "")

    def list_click(self, event):
        """a click in the list. on a line's three dots: its menu, and the line is not opened. anywhere else: nothing
        here, the list picks the line itself (see picked)"""
        if self.on_dots(event):
            self.list_menu(event)
            return "break"                           # "break" = the list doesn't also select the line
        return None

    def list_menu(self, event):
        """the three dots of a conversation, or a right click on it: rename or delete it"""
        name = self.list.identify_row(event.y)
        if not name:
            return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Rename …", command=lambda: self.rename(name))
        menu.add_command(label="Delete …", command=lambda: self.delete(name))
        menu.tk_popup(event.x_root, event.y_root)

    # --- what you do ---
    def new(self):
        self.server.send("new")                      # answered with "opened", which shows it

    def rename(self, old, new=None):
        if new is None:
            new = simpledialog.askstring("Rename", "A new name for " + old + ":\n(letters, digits and - _ . only)",
                                         initialvalue=old, parent=self.root)
        if new and new.strip() and new.strip() != old:
            self.server.send("rename", old=old, new=new.strip())

    def delete(self, name):
        if messagebox.askyesno("Delete", "Delete '" + name + "' with everything in it?\nThere is no undo.",
                               parent=self.root):
            self.server.send("delete", conversation=name)

    def on_return(self, event):
        """Enter sends. Shift+Enter makes a new line (that is what the box does by itself)"""
        if event.state & 0x1:                        # 0x1 = the shift key is held
            return None
        self.send_or_stop(only_send=True)
        return "break"                               # "break" = don't also put a new line into the box

    def send_or_stop(self, only_send=False):
        """the button: Send, or Stop while the conversation works. Enter only ever sends"""
        view = self.views.get(self.current)
        if self.closed or not view:
            return
        if view.busy and not only_send:
            self.server.send("stop", conversation=self.current)
            return
        text = self.entry.get("1.0", "end-1c").strip()
        if not text:
            return
        if text.startswith("/"):
            self.entry.delete("1.0", "end")
            self.command(text)
        elif view.busy:                              # one task at a time per conversation: what you typed stays
            self.hint.configure(text="this conversation is still working: wait, or stop it. your text stays here",
                                fg=C["stop"])
            self.root.after(4000, lambda: self.hint.configure(text=HINT, fg=C["faint"]))
        else:
            self.entry.delete("1.0", "end")
            self.server.send("message", conversation=self.current, text=text)   # comes back as a "user" event,
                                                                                # which draws it
    def command(self, text):
        """a /command typed into the box"""
        words = text.split()
        command = words[0].lower()
        if command in ("/exit", "/quit"):
            self.quit()
        elif command == "/new":
            self.new()
        elif command == "/open" and len(words) == 2:
            self.go_to(words[1])
        elif command == "/list":
            self.note("conversations:\n" + "\n".join(
                ("* " if name == self.current else "  ") + name + (" (working)" if name in self.working else "")
                for name in self.list.get_children()))
        elif command == "/rename" and len(words) in (2, 3):
            self.rename(words[1] if len(words) == 3 else self.current, words[-1])
        elif command == "/delete" and len(words) in (1, 2):
            self.delete(words[1] if len(words) == 2 else self.current)
        elif command == "/stop":
            self.server.send("stop", conversation=self.current)
        elif command == "/sandbox" and len(words) == 1:
            self.server.send("sandbox", conversation=self.current)
        elif command == "/sandbox" and len(words) == 3 and words[1] == "net" and words[2] in ("on", "off"):
            self.server.send("sandbox", conversation=self.current, net=words[2])
        elif command == "/sandbox" and len(words) == 3 and words[1] == "open":
            self.note("opening " + words[2] + " ... (the first time builds its image, which can take minutes)")
            self.server.send("sandbox", conversation=self.current, do="open", name=words[2])
        elif command == "/sandbox" and words[1:] == ["stop"]:
            self.server.send("sandbox", conversation=self.current, do="stop")
        elif command == "/sandbox" and words[1:] == ["stop", "all"]:
            self.server.send("sandbox", conversation=self.current, do="stop_all")
        elif command == "/help":
            self.note(HELP)
        else:
            self.note("command not found, or typed the wrong way: " + text + "\n" + HELP)

    def quit(self):
        """close the window. the conversations stay in the server, also the ones that are working"""
        self.server.close()
        self.root.destroy()


if __name__ == "__main__":                           # runs only when you start gui.py directly
    try:
        server = Connection(HOST, PORT, "gui")
    except OSError:
        raise SystemExit("no server is running on " + HOST + ":" + str(PORT) + ". start it first, in a terminal: "
                         "python server.py")
    if sys.platform == "win32":                      # windows: a sharp window on a high-resolution screen
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise SystemExit("could not open a window: " + str(e) + " (this needs a desktop)")
    Gui(root, server)
    root.mainloop()
