# Makefile. Owner: Srushti.
.PHONY: build test

build:
	python3 --version
	python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else \"Python 3.10+ required\")"
	python3 -m compileall -q src torturelib
	chmod +x kvdb torture
	@echo "BUILD OK"

test:
	python3 -m unittest -q
