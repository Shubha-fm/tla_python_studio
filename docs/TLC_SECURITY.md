# TLC execution safety

The Docker image includes a pinned TLC JAR and Java runtime, but it **does not execute user-supplied TLC programs on the public website**. TLC may evaluate user-provided specifications. A subprocess timeout, small Java heap, or temporary directory alone is NOT an adequate isolation boundary.

To offer public TLC execution:
1. Deploy a dedicated worker behind a queue and authenticated gateway, separate from the web process.
2. Run one job per disposable isolated container or VM with an unprivileged UID, read-only root, no network, minimal mounts, memory/CPU/PID quotas, disk quotas, and an enforced wall-time limit.
3. Provide each worker only its job's .tla and .cfg files; accept filenames from the service, never from the user.
4. Restrict module/config sizes and requests per user, cancel runaway jobs, avoid sharing data between sessions.
5. Record tool versions and limits in every evidence report; return TLC logs with clear success/violation/error distinction.
6. Only then add an authenticated worker adapter for POST /api/tlc/run.

Until these conditions are satisfied, the endpoint is intentionally disabled regardless of whether TLC_JAR is installed.

For local trusted testing, run TLC directly in a disposable container with resource/network restrictions rather than enabling the endpoint on Render.
