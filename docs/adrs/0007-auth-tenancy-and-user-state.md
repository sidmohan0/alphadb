# ADR 0007: Auth, Tenancy, And User State

- Status: Accepted
- Date: 2026-03-09

## Context

Local file-backed saves are enough for a standalone TUI, but not for a production multi-client product. The backend service needs a user model that works for both web and terminal clients.

## Decision

Adopt external identity with backend-issued session handling and a first-class user-state domain.

Authentication:

- OIDC-compatible identity provider for humans
- service tokens for internal workers
- device-code or personal access token flow for the TUI

Authorization:

- start with single-user ownership semantics
- make multi-tenant boundaries explicit in schema and API contracts
- default to least privilege for service credentials

Persisted user state:

- watchlists
- recents
- saved searches
- alert rules
- layout and preference settings

## Consequences

Positive:

- the TUI can become a real client, not a disconnected local toy
- web and TUI share the same state model
- future collaboration features stay possible

Negative:

- auth complexity arrives earlier
- TUI onboarding gets harder than a no-auth local CLI

## Notes

Do not delay tenancy boundaries until after launch if the backend will hold user state. Retrofits are expensive and risky.
