.PHONY: install lint test generate generate-small clean daily publish simulator-deploy simulator-run infra-init infra-plan infra-apply infra-destroy sources-up

TF_DEV := terraform -chdir=infra/terraform/envs/dev
REGION := us-east-1

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

# --- Daily source simulator. Publishing needs boto3, psycopg[binary] and paramiko.

# Split the one-year calendar into day folders and upload them (once, about 6 minutes plus upload).
daily:
	python -m data_generator.daily --out output/daily
	aws s3 sync output/daily s3://$$(aws ssm get-parameter --name /supporthub/dev/s3/simulator_bucket --query Parameter.Value --output text)/days/

# Publish pending days from this machine (the Databricks job does this every morning).
publish:
	python -m data_generator.publish --verbose

simulator-deploy:
	databricks bundle deploy

simulator-run:
	databricks bundle run source_simulator

# --- AWS sources (Terraform). Shares RetailPulse's RDS instance and SFTP server, which must be
# running for plan and apply: inside 06:00 to 08:00 UTC, or after `make sources-up`.

infra-init:
	$(TF_DEV) init -backend-config=backend.hcl

infra-plan:
	$(TF_DEV) plan -out=dev.tfplan

infra-apply:
	$(TF_DEV) apply dev.tfplan

# Removes SupportHub's sources and data; RetailPulse's servers are untouched.
infra-destroy:
	$(TF_DEV) destroy

# Start the shared servers outside the daily window (RetailPulse's schedule stops them at 08:00 UTC).
sources-up:
	aws rds start-db-instance --region $(REGION) --db-instance-identifier retailpulse-dev-orders
	aws ec2 start-instances --region $(REGION) --instance-ids $$(aws ssm get-parameter --name /retailpulse/dev/sftp/instance_id --query Parameter.Value --output text)
	aws rds wait db-instance-available --region $(REGION) --db-instance-identifier retailpulse-dev-orders
