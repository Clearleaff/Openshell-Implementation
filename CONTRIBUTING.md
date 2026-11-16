# Contributing to PRESCPTR

Thank you for your interest in contributing to PRESCPTR! This project demonstrates how Gemini LLM agents operate under OpenShell sandboxing and strict external control plane governance in industrial and OT settings.

## Principles

1. **Defense-in-Depth**: Agent governance is enforced by multiple orthogonal layers:
   - Kernel and network level (OpenShell Landlock filesystem restrictions + eBPF network filtering).
   - Application gateway level (Bearer authentication, schema validation, rate limiter).
   - LLM level (System instructions, schema typing, untrusted data separation).
2. **Zero Third-Party Pip Dependencies**: The runtime relies entirely on the Python 3.12+ standard library (`urllib`, `sqlite3`, `hmac`, `secrets`, etc.) to keep the attack surface minimal and verifiable.
3. **No Rules-Based Fallback**: Agent tool-calling logic must be exercised by real LLM inference. Mocking is restricted to offline testing harnesses.
4. **Honest Evaluation Reporting**: Never fabricate pass rates or live execution outcomes. If quota runs out or tests fail, report them accurately.

## Development Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-org/prescptr-gemini-openshell.git
   cd prescptr-gemini-openshell
   ```

2. **Run Tests**:
   ```bash
   python3 -m unittest discover -s tests -v
   ```
   Or using the Makefile:
   ```bash
   make test
   ```

3. **Code Style & Formatting**:
   We recommend `ruff` for linting:
   ```bash
   make lint
   ```

## Pull Request Guidelines

1. Ensure all 26 offline protocol unit tests pass without regressions.
2. If introducing new attack vectors, add them to `fixtures/attacks.json` with a clear explanation of the target failure mode.
3. If altering OpenShell policies, update both `policies/diagnosis.yaml` and `policies/prescriptive.yaml` and test with `scripts/boundaries.py`.
4. Keep commits clean, atomic, and descriptive.
