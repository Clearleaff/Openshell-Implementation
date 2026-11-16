# Security Policy

## Threat Model Overview

PRESCPTR is an open-source research and POC architecture designed to evaluate governance mechanisms over autonomous LLM agents in industrial operational technology (OT) workflows.

### Primary Threat Vectors Addressed
1. **Direct & Indirect Prompt Injection**: Untrusted telemetry notes, diagnostic attachments, or upstream outputs attempting to manipulate model decisions.
2. **Unauthorized Physical Actuation**: LLM agents attempting to issue commands to shut down machines, modify parameters, or bypass safety interlocks.
3. **Privilege Escalation & Cross-Machine Access**: A read-only diagnostic agent attempting to issue maintenance prescriptions, or an agent scoped to `CNC-01` accessing `PUMP-02`.
4. **Credential Theft & Exfiltration**: Malicious instructions attempting to access host environment variables (e.g., `GEMINI_API_KEY`) or exfiltrate tokens via unauthorized egress.
5. **Sandbox & Filesystem Escape**: Attempted access to host sockets, docker daemons, or restricted system paths.

### Security Guarantees
- The real `GEMINI_API_KEY` is **never** provided to agent sandboxes; it resides exclusively in the host control plane process.
- Each agent receives only a scoped Bearer service token.
- OpenShell enforces kernel Landlock filesystem isolation and eBPF egress filtering at the OS boundary.
- All actions require atomic SQLite WAL audit logging before execution.

## Reporting a Vulnerability

If you discover a security vulnerability, prompt injection bypass, or sandbox escape:

1. **Do not open a public issue.**
2. Send a detailed report to the security maintainers or open a private GitHub Security Advisory.
3. Include:
   - Reproduction script or prompt sequence.
   - Target component (OpenShell policy, control plane handler, or agent loop).
   - Trace output and audit database logs.
4. Maintainers will acknowledge within 48 hours and coordinate remediation.
