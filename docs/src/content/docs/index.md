---
title: pipeapi
description: Talk to an on-device FastAPI backend over a Windows named pipe, a Unix domain socket or a token-protected loopback port.
template: splash
hero:
  tagline: An on-device app talks to its FastAPI backend over a Windows named pipe, a Unix domain socket or a token-protected loopback port.
  actions:
    - text: Reference
      link: /pipeapi/reference/
      icon: right-arrow
    - text: GitHub
      link: https://github.com/jaARke/pipeapi
      icon: github
      variant: minimal
---

pipeapi lets an on-device app talk to a FastAPI backend over a Windows named pipe, a Unix domain socket or a token-protected loopback port. The wire format stays plain HTTP/1.1, so FastAPI, Pydantic validation and OpenAPI work unchanged.

pipeapi also owns the parts every on-device backend otherwise reinvents: spawning or attaching to the backend, verifying it, readiness, lifetime and client identity. Its connectors give Node and Electron, .NET, Rust, Go and Python apps an HTTP client their OpenAPI generators already accept.

pipeapi is in early development and has no releases yet. The [issues](https://github.com/jaARke/pipeapi/issues) hold the design and the work toward the first release.
