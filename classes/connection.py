# connection.py — the Connection: how a client (main.py, gui.py, anything you build) talks to the server.
#
# the server and its clients talk in lines of text: every line is one json object.
#   the client sends requests:   {"type": "message", "conversation": "trip", "text": "hello"}
#   the server sends events:     {"kind": "answer", "conversation": "trip", "text": "Hi"}
# all of them are listed at the top of classes/hub.py.
#
# a client only needs two things from here:
#   connection.send("message", conversation="trip", text="hello")     send one request
#   event = connection.next(0.2)                                      the next event, or None if none came in time
# events arrive at any moment (an answer comes in many small pieces), so a thread reads them the whole time and puts
# them into a queue. next() takes them out of it, in the order they came.

import json
import queue
import socket
import threading


class Connection:
    def __init__(self, host, port, kind):
        """connect to the server, and say who we are. kind: "cli", "gui", ... raises OSError if no server runs"""
        self.socket = socket.create_connection((host, port), timeout=5)
        self.socket.settimeout(None)               # the 5 seconds were only for connecting: reading waits forever
        self.events = queue.Queue()                # what the server sent, until next() takes it
        self.lock = threading.Lock()               # one request at a time is written, also from several threads
        threading.Thread(target=self.read, daemon=True).start()   # daemon: it never keeps the program from ending
        self.send("hello", kind=kind)              # answered with a "hello" event: our number, the model, ...

    def read(self):
        """the whole time: every line the server sends becomes one event in the queue. the server is gone (or we
        closed the connection): one last event, {"kind": "closed"}"""
        try:
            with self.socket.makefile("r", encoding="utf-8") as lines:
                for line in lines:
                    self.events.put(json.loads(line))
        except (OSError, ValueError):              # the connection broke
            pass
        self.events.put({"kind": "closed"})

    def send(self, type, **fields):
        """send one request, e.g. send("open", conversation="trip"). False if the server is gone"""
        request = dict(fields, type=type)
        try:
            with self.lock:
                self.socket.sendall((json.dumps(request) + "\n").encode("utf-8"))   # one line. json writes a line
            return True                                                              # break inside a text as \n
        except OSError:
            return False

    def next(self, timeout=None):
        """the next event from the server. waits up to timeout seconds for one (None: as long as it takes,
        0: not at all). nothing came: None"""
        try:
            if timeout == 0:
                return self.events.get_nowait()
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)  # wakes the reading thread too
        except OSError:
            pass
        self.socket.close()
