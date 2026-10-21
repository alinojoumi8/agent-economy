# Checkpoint SIGBUS repair

Preserve failed e6a199f source/replay artifacts. Reproduce the native crash using private copies and traceback diagnostics before implementation. Fix the demonstrated cause without altering canonical digests, economic behavior, resource guards, checkpoint integrity/atomicity, or v1 compatibility.

- Bounded subprocess regression fails under old code and passes after repair; verify valid/invalid boundaries.
- Exact replay, source/checkpoint immutability and retained receipt from one fresh unchanged308-agent20tick canary after candidate gates.
- Required focused/full local and static/CI gates, CodeRabbit against actual PR base.
- Preserve failures, memory and timing limitations; no new1000tick experiment or observatory.
