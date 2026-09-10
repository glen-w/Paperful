# Sci-Hub

Sci-Hub occupies a **legal grey zone in some jurisdictions**. paperful does
not enable it unless you opt in. You are responsible for complying with the
laws that apply to you. The authors and distributors of this tool do not
encourage copyright infringement.

Opt in either way (Sci-Hub is then tried last, after open-access sources and
EZProxy):

- add `"scihub"` at the end of `sources` in `config.toml`, or
- pass `--scihub` on a single `run`.

A yellow disclaimer is printed whenever Sci-Hub is in the source list for
that run. `paperful mirrors` pings configured hostnames even when Sci-Hub is
off; it does not turn the source on.

When enabled, mirrors are tried in the configured order. A mirror that fails
on the network `mirror_failures_before_skip` times in a row is skipped for the
rest of the run. Sci-Hub's robot check (ALTCHA proof-of-work) is solved
automatically; if it still cannot be passed the item is marked `captcha` and
retried next run. Repeated CAPTCHAs also trip the run-wide
[circuit breaker](sources.md) for `scihub`. A
definitive "not found" is final for the run since all mirrors share one
database. Coverage after ~2021 is thin.
