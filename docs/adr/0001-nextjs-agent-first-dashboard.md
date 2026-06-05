# Next.js is the Agent-First Dashboard Surface

Accepted. AlphaDB will commit to the supplied Next.js dashboard prototype as the user-facing Agent-first dashboard surface, while the existing Python target-platform services remain responsible for operational APIs, trading state, replay, registry, and live runtime behavior. We chose this over porting the prototype back into the current Python stdlib dashboard because the MVP needs fast UI iteration across Strategy Studio, Live Operations, Agent Terminal, Data Explorer, and Lab, and the prototype already embodies that product shape.

## Considered Options

- Commit to Next.js as the dashboard surface and use Python as the operational backend.
- Keep the Python dashboard as the UI surface and manually port the prototype ideas into stdlib HTML.

## Consequences

- The current Python dashboard should be treated as a backend/API bridge and compatibility surface, not the long-term UI shell.
- Deployment and local development now need to account for a frontend app alongside the Python target-platform services.
