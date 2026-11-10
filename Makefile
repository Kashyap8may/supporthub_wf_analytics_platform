.PHONY: install lint test generate generate-small clean

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

test:
	pytest -q

# Generate the default dataset (90 days) into ./output
generate:
	python -m data_generator.simulate --out output

# Small dataset for a quick look
generate-small:
	python -m data_generator.simulate --out output --scale 0.1 --days 14

clean:
	rm -rf output .pytest_cache .ruff_cache
