# Security policy

## Reporting a vulnerability

Please **don't** open a public issue for security problems, for example a way the password could leak
or a restart could be triggered unintentionally. Use GitHub's private vulnerability reporting instead
(*Security → Report a vulnerability* on the repository page).

Include what you found, how to reproduce it, and its impact. Don't include real credentials.

## Scope

The handling of router credentials, log contents, the scheduled task, and anything that could
cause unintended or repeated router restarts.

## If you think your router password was exposed

Change it in the router's web interface, then run `.\scripts\Configure.ps1` to store the new one.
If it was ever committed to a Git repository, rewriting history isn't enough on its own, because
copies may already exist elsewhere. Change the password.

How credentials are handled is described in [docs/security.md](docs/security.md).
