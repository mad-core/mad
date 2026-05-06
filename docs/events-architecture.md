# Events Architecture

```mermaid
flowchart TD
    Client(["Client / HTTP"])

    subgraph HTTP ["mad.adapters.inbound.http"]
        R_Sessions["POST /v1/sessions/:id/message"]
        R_Events_List["GET /v1/events"]
        R_Events_Stream["GET /v1/events/stream (SSE)"]
    end

    subgraph Core ["mad.core"]
        SendMsg["SendUserMessageUseCase"]
        QueryEvents["QueryEventsUseCase"]
        StreamEvents["StreamEventsUseCase"]

        subgraph Ports ["Ports (Protocols)"]
            P_Bus["EventBus"]
            P_Query["EventLogQuery"]
            P_Repo["SessionRepository"]
            P_Launcher["AgentLauncher"]
        end
    end

    subgraph Adapters_Out ["mad.adapters.outbound"]
        Bus["InMemoryEventBus\n(subscribers + queues)"]
        LogQuery["JsonlEventLogQuery\n(lee el JSONL)"]
        Repo["JsonlSessionRepository\n(JSONL file log)"]
        LauncherImpl["ClaudeCliLauncher\nspawns: claude --dangerously-skip-permissions"]
    end

    subgraph External ["Externo"]
        Agent(["claude CLI\n(proceso externo)"])
        JSONL[("session.jsonl\n(log en disco)")]
    end

    %% HTTP → Use cases
    Client --> R_Sessions --> SendMsg
    Client --> R_Events_List --> QueryEvents
    Client --> R_Events_Stream --> StreamEvents

    %% SendUserMessage → ports
    SendMsg -->|"append_event"| P_Repo --> Repo --> JSONL
    SendMsg -->|"publish(event)"| P_Bus --> Bus
    SendMsg -->|"run(prompt, emit)"| P_Launcher --> LauncherImpl --> Agent

    %% Agent devuelve output via callback emit()
    Agent -->|"stdout → emit(agent.output)"| SendMsg

    %% Query/Stream → ports
    QueryEvents --> P_Query --> LogQuery --> JSONL
    StreamEvents --> P_Bus

    %% Bus → StreamEvents subscribers
    Bus -->|"AsyncIterator[Event]"| StreamEvents
    Bus -->|"fan-out a subscribers"| R_Events_Stream
```

## Flujos principales

**Escritura** — El mensaje entra por HTTP, `SendUserMessage` persiste en JSONL, publica al bus,
y le pasa el control al launcher externo. El launcher devuelve líneas de stdout via el callback
`emit()`, que vuelve a pasar por el mismo ciclo.

**Lectura histórica** — `GET /v1/events` va directo al JSONL via `JsonlEventLogQuery`,
sin tocar el bus.

**Streaming en vivo** — `GET /v1/events/stream` se subscribe al `InMemoryEventBus`
y recibe eventos a medida que se publican.
