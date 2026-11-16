.PHONY: help test lint init service sandboxes workflow eval boundaries docker-build clean

PYTHON ?= python3
MODEL ?= gemini-2.5-flash

help:
	@echo "PRESCPTR: Gemini Agents under OpenShell Governance - Makefile"
	@echo ""
	@echo "Usage:"
	@echo "  make test           Run offline protocol and governance unit tests (26 test cases)"
	@echo "  make lint           Check code syntax and style"
	@echo "  make init           Initialize runtime credentials (default: MODEL=$(MODEL))"
	@echo "  make docker-build   Build agent Docker container image (prescptr-gemini:local)"
	@echo "  make service        Start host control plane service (terminal A)"
	@echo "  make sandboxes      Create and launch OpenShell sandboxes (terminal B)"
	@echo "  make workflow       Execute live end-to-end diagnosis -> prescription workflow"
	@echo "  make eval           Run live prompt-injection evaluation trial suite"
	@echo "  make boundaries     Run independent OpenShell network/filesystem boundary tests"
	@echo "  make clean          Clean local caches, temporary artifacts and pycache"

test:
	$(PYTHON) -m unittest discover -s tests -v

lint:
	@if command -v ruff > /dev/null 2>&1; then \
		ruff check app/ tests/ scripts/; \
	else \
		$(PYTHON) -m py_compile app/*.py scripts/*.py tests/*.py && echo "Syntax checks passed."; \
	fi

init:
	$(PYTHON) scripts/init.py --model $(MODEL)

docker-build:
	docker build -t prescptr-gemini:local .

service:
	@if [ -z "$$GEMINI_API_KEY" ]; then \
		echo "ERROR: GEMINI_API_KEY is not set in environment. Run 'export GEMINI_API_KEY=...' first." && exit 1; \
	fi
	$(PYTHON) -m app.service --bind 0.0.0.0 --lab-http

sandboxes:
	bash scripts/start.sh

workflow:
	$(PYTHON) scripts/workflow.py

eval:
	$(PYTHON) scripts/evaluate.py

boundaries:
	$(PYTHON) scripts/boundaries.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.py[cod]" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache 2>/dev/null || true
	rm -rf runtime/control.json runtime/audit.sqlite3* runtime/diagnosis runtime/prescriptive 2>/dev/null || true
	touch runtime/.gitkeep
