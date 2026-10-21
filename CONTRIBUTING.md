# Contributing

Thanks for helping. Support for more routers is the most useful contribution.

## Ground rules

- **Never post real passwords, cookies, session IDs, tokens, serial numbers or MAC addresses**, in
  issues, pull requests, logs, screenshots or test fixtures. Use placeholders such as
  `YOUR_ROUTER_PASSWORD` and documentation addresses such as `192.0.2.1`.
- Only add router flows you verified on a real device, and say exactly which firmware.
- Keep it small. The only runtime dependency is `requests`, so please discuss new ones first.

## Development setup

```powershell
.\scripts\Install.ps1
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests use a simulated router and a temporary data folder. They never contact a real router,
restart anything, or register scheduled tasks. A few Windows-only tests run PowerShell, and one
writes and deletes a throw-away Credential Manager entry, `RouterAutoRestart:selftest`.

## Adding a router adapter

Follow [docs/router-compatibility.md](docs/router-compatibility.md#adding-a-router). Each pull
request needs:

- the adapter module and its registration in `routers/__init__.py`;
- tests with simulated responses covering success, wrong password, busy session, timeouts and the
  restart request;
- a section in `docs/router-compatibility.md`.

## Style

- Python 3.9+ and standard library first. Follow the style of the surrounding code.
- PowerShell scripts must work in Windows PowerShell 5.1. Disruptive actions must support `-WhatIf`
  and ask for confirmation.
- Don't log secrets, request bodies or cookies.

## Pull requests

Describe what you changed and how you tested it, including on which device if hardware was involved.
