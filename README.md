# pipeapi

pipeapi lets an on-device app talk to a FastAPI backend over a Windows named pipe, a Unix domain socket or a token-protected loopback port. The wire format stays plain HTTP/1.1, so FastAPI, Pydantic validation and OpenAPI work unchanged. pipeapi also owns the parts every on-device backend otherwise reinvents: spawning or attaching to the backend, verifying it, readiness, lifetime and client identity. Its connectors give Node and Electron, .NET, Rust, Go and Python apps an HTTP client their OpenAPI generators already accept.

pipeapi is in early development and has no releases yet. The [guide site](https://jaarke.github.io/pipeapi/) documents it, starting with its protocol and the connector API every language shares, and the [issues](https://github.com/jaARke/pipeapi/issues) hold the design and the work toward the first release.

## Contributing

Contributions are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) explains how to set up for development, report bugs, propose changes and open pull requests, and [SECURITY.md](SECURITY.md) how to report a vulnerability privately.

## License

pipeapi is released under the [MIT License](LICENSE).
