# classes

| File | What it is |
|---|---|
| `agent.py` | The `Agent`: one conversation with one model. It sends the conversation to the model, runs the tools, logs every message, asks for checkpoints, and says everything that happens as events. |
| `hub.py` | The `Hub`: the layer between the clients and the agents. It holds the agents of the conversations in use, runs each task in its own thread, and passes every event on to the clients that have that conversation open. Every request and event is listed at its top. |
| `connection.py` | The `Connection`: how a client talks to the server. `send(type, ...)` sends one request, `next(timeout)` gives the next event. |
| `printer.py` | The `Printer`: shows events in a terminal, the way the program always printed (`THINKING:`, `ANSWER:`, `TOOL CALL: ...`). Used by `main.py`. |

`server.py` writes `new_agent`, and the hub calls it to make one `Agent` per conversation. For every message a client sends, the hub calls `agent.ask(text)` in a thread of its own. Everything the agent needs comes in as a parameter, so `agent.py` itself knows nothing about folders, files, servers or clients.

## Who talks to whom

```
 client  ── request ──>  server.py  ──>  hub.handle()  ──>  agent.ask()          (in a new thread)
 client  <── event ────  server.py  <──  hub.event()   <──  agent.send()  =  agent.output(event)
```

The agent has one way out: `self.output`, a function that takes one event. The hub gives it its own `event` function. So the agent never prints and never knows who listens, and the hub decides who gets what.

## Making an agent

```python
agent = Agent(MODEL, API_KEY, instructions=soul, stream=STREAM, effort=EFFORT,
              tools=tools, skills=skills, conversation=messages,
              log_file=..., results_dir=..., checkpoint_file=..., context_limit=CONTEXT_LIMIT,
              output=hub.event, name=name)
```

| Parameter | What it is | Left out |
|---|---|---|
| `model`, `api_key` | which model, and the key for it (from `config.py`) | required |
| `instructions` | who the agent is: the soul, the start of its system prompt | no soul |
| `stream` | send the answer piece by piece while it arrives | all at once |
| `effort` | how hard the model thinks | the model's default |
| `tools` | the tools it may use: name -> `{"schema", "run"}` (`functions/load_tools.py`) | no tools |
| `skills` | the skills it may load: name -> `{"description", "path"}` (`functions/load_skills.py`) | no skills |
| `conversation` | a saved list of messages to go on with (`/open`) | a new conversation |
| `log_file` | where every message is written (`log.jsonl`) | no log |
| `results_dir` | where long tool results are saved (`results/`) | long results are given whole |
| `checkpoint_file` | where the checkpoint is (`checkpoint.md`) | no checkpoints |
| `context_limit` | tokens the conversation may have | no checkpoints are asked for |
| `output` | where every event goes: a function that takes one event (a dict) | the agent says nothing |
| `name` | the conversation's name, written on every event | `None` |

Pass them by name (`stream=STREAM`), never by position: then a value can never land in the wrong parameter.

## What it holds

| Variable | What it holds |
|---|---|
| `conversation` | the list of messages: the only thing the model ever knows. The system prompt is always at position 0 |
| `tokens` | how big the conversation is, as the provider counted it with the last answer |
| `stop_requested` | set to `True` from outside (the hub) to stop the running task. Set back to `False` by whoever starts the next one |
| `told` | the last message the program itself sent to the model, so it can be taken back if nobody answers it |
| `logged_system` | the system prompt as it was last written into the log, so it is only logged again when it changes |
| `checkpoint_asked` | `None`, or why a checkpoint was asked for: `"end"` or `"emergency"` |
| `cleared` | `True` right after the `checkpoint` tool emptied the conversation |

The parameters above are kept under the same names (`agent.model`, `agent.tools`, ...). Tools get the agent as their first argument, so they can use all of this: `load_skill` reads `agent.skills`, `read_result` uses `agent.results_dir`, `checkpoint` empties `agent.conversation`.

## What it does

| Function | What it does |
|---|---|
| `ask(text)` | **The loop.** Adds your message, then: call the model, add its answer, run the tools it asked for, again, until it answers without tools. Checks the size after every answer and asks for a checkpoint when needed. Returns the final answer as text. |
| `call_model()` | One call to the model, with the whole conversation and the tools. A busy provider, a timeout or a lost connection is tried again after 1, 2 and 4 seconds. |
| `show(response)` | Sends the thinking and the answer as events while they arrive (streaming) or at once, and returns the finished response. Between two pieces it looks whether the user asked to stop. |
| `send(kind, ...)` | Sends one event to `output`: `thinking`, `answer`, `answer_end`, `tool_call`, `tool_result` or `note`. |
| `check_stop()` | Called at the safe points of a task. If `stop_requested` is set, it leaves `ask()` from there. |
| `stopped(said)` | Ends a stopped task cleanly: what was said so far becomes the model's last message, with a line saying the user stopped it. |
| `count_tokens(response)` | The conversation's size, from the provider's count in the answer. No count: litellm's estimate. |
| `run_tools(tool_calls)` | Runs all tool calls of one answer at the same time, waits for all of them, and adds their results in the order the model asked, each with its call's id. Long results are shortened first (`functions/results.py`). |
| `run_tool(call, results)` | Runs one tool call, in its own thread. Never fails: every problem becomes an `error:` text for the model. |
| `build_system()` | Puts the system prompt together: the soul, the skills menu, the checkpoint. Changes nothing. |
| `refresh_system()` | Builds the system prompt and puts it at position 0: replaces the old one, or adds it. No text: no system message. |
| `log(message)` | Writes one message into the log, with the system prompt before it if it changed. Only ever adds. |
| `too_full(share)` | Is the conversation above this share of the context limit? |
| `ask_for_checkpoint(why)` | Adds the request for a checkpoint (`"end"` or `"emergency"`) as the next message to the model. |
| `tell_model(text)` | Adds a message from the program (not from you) to the conversation and the log. |

## One message, from start to end

```
ask("what is 17% of 2340?")
 |
 |  add your message to the conversation, and log it
 v
 +-> call_model()  ->  show()  ->  add the answer, log it, count the tokens
 |        |
 |        +-- tools asked for?  yes: run_tools() -> results added (in order, with their ids)
 |        |                          - the checkpoint tool emptied the conversation?
 |        |                              end of a task: done.   in a task: "go on", back to the top
 |        |                          - above EMERGENCY_AT: add the emergency request
 |        |                          back to the top
 |        |
 |        +-- no tools: the final answer
 |                 - above CHECKPOINT_AT: add the request, back to the top
 +---------------- - otherwise: return the answer
```

If the model call fails before anything happened, your message is taken back, so the conversation is as before and you can send it again. If tools already ran, their work stays. A checkpoint request that was never answered is taken back too.

## Stopping

The user can stop a task at any moment, but the agent only stops at a **safe point**, where the conversation is whole: before a model call, between two pieces of a streaming answer, or while waiting for a retry. What happens then:

- **In the middle of an answer:** the text so far is kept as the model's message, followed by `[The user stopped me here, before I was done.]`. A tool call that was only half received is never added.
- **While tools run:** they finish first (a running thread can't be stopped from outside), their results are added, then the task ends. A tool call without its result would make the provider reject every later request.
- **The conversation always ends with a message of the model**, so your next message follows it the normal way. Some providers reject two user messages in a row.

## The texts at the top of the file

- `CHECKPOINT_REQUEST`, `EMERGENCY_NOTE`, `GO_ON` are what the program says to the model about checkpoints. They start with `[from the program, not the user]`, so the model doesn't think you wrote them. Change the wording there.
- `RETRIES` and `RETRY_ON` say how often, and for which errors, a model call is tried again.