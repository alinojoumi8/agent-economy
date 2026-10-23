# Lessons

## Preserve the runtime source during long experiments

A running Python process can retain already imported modules after its worktree
is removed, then fail at a later lazy import or spawned worker. A clean Git
status does not mean a checkout is unused, and ignored logs/receipts are not
recoverable from a commit.

Lock an active Git worktree. Keep a frozen runtime checkout, its virtual
environment, control scripts and experiment evidence outside managed cleanup
directories. Bind them to the validated commit and source hashes. Check required
checkpoint imports and their physical source files before starting a formal run.
Preserve incomplete runs and their claims; start a separately authorized run
rather than replacing its artifacts. Failed checkpoint calls are not latency
samples.
