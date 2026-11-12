# printer.py — the Printer: shows events in a terminal, the way the program always printed them.
# before there was a server, the agent printed all of this itself. now it sends events (classes/agent.py, send), and
# whoever shows them decides how. main.py uses this; the window (gui.py) draws the same events its own way.


class Printer:
    def __init__(self, print_thinking=False):
        self.print_thinking = print_thinking   # True = the thinking is printed too. False = only the answer
        self.printing = None                   # what kind of text was printed last: "THINKING", "ANSWER" or None

    def show(self, event):
        """print one event"""
        kind = event["kind"]
        if kind == "thinking":
            self.part("THINKING", event["text"])
        elif kind == "answer":
            self.part("ANSWER", event["text"])
        elif kind == "answer_end":             # the model's message is complete: end its line
            print()
            self.printing = None
        elif kind == "tool_call":
            print("\nTOOL CALL: " + event["name"] + "(" + event["args"] + ")")
        elif kind == "tool_result":
            print("TOOL RESULT: " + event["name"] + " -> " + event["text"])
        elif kind == "note":                   # something the program says: a retry, a checkpoint, stopped
            print("[" + event["text"] + "]")
        elif kind == "error":                  # \n first: a stream may have stopped in the middle of a line
            print("\nerror: " + event["text"])
            self.printing = None
        elif kind == "refused":
            print("[" + event["text"] + "]")

    def part(self, kind, text):
        """print one piece of THINKING or ANSWER text. a title appears whenever the kind changes"""
        if not text:                                       # no text of this kind in this piece: nothing to do
            return
        if kind == "THINKING" and not self.print_thinking: # thinking is hidden: skip it (it is still stored)
            return
        if kind != self.printing:                          # a different kind than the last piece: title first
            if self.printing:                              # something was printed before: an empty line between
                print("\n")
            print(kind + ":")
            self.printing = kind                           # remember: now we are in this kind
        print(text, end="", flush=True)                    # end="": no new line after each piece.
                                                           # flush: show it right now, not when python feels like it
