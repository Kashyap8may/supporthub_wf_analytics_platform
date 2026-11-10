.PHONY: install lint test clean

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

test:
	pytest -q

clean:
	rm -rf output .pytest_cache .ruff_cache
