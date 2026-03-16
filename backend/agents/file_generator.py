import json
from datetime import datetime, timezone


def generate_files(plan: dict, results: list) -> dict:
    files = {}
    successful = [r for r in results if r.get("success")]

    if not successful:
        return files

    files["nimbus-infra.json"] = _infra_manifest(plan, results)
    files["setup.sh"] = _setup_script(successful)
    files["teardown.sh"] = _teardown_script(successful)

    has_ec2 = any(r.get("resource_type") == "ec2" for r in successful)
    has_lambda = any(r.get("resource_type") == "lambda" for r in successful)
    has_dynamodb = any(r.get("resource_type") == "dynamodb" for r in successful)

    if has_ec2:
        files["docker-compose.yml"] = _docker_compose(successful)

    if has_lambda:
        files["deploy-lambda.sh"] = _lambda_deploy_script(successful)

    if has_dynamodb:
        files["seed-data.py"] = _dynamo_seed_script(successful)

    files["README.md"] = _readme(plan, successful)

    return files


def _infra_manifest(plan: dict, results: list) -> str:
    manifest = {
        "nimbus_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan": plan,
        "resources": [
            {
                "type": r.get("resource_type"),
                "id": r.get("resource_id"),
                "name": r.get("name"),
                "success": r.get("success"),
            }
            for r in results
        ],
    }
    return json.dumps(manifest, indent=2)


def _setup_script(results: list) -> str:
    lines = [
        "#!/bin/bash",
        "# Nimbus Infrastructure Setup Script",
        f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "# This script verifies and describes your deployed resources.",
        "",
        'set -e',
        "",
        'echo "Verifying Nimbus resources..."',
        "",
    ]

    for r in results:
        rtype = r.get("resource_type")
        rid = r.get("resource_id", "")
        name = r.get("name", "")

        if rtype == "ec2":
            lines.append(f'echo "Checking EC2 instance: {name} ({rid})"')
            lines.append(f'aws ec2 describe-instances --instance-ids {rid} --query "Reservations[0].Instances[0].State.Name" --output text')
            lines.append("")
        elif rtype == "s3":
            lines.append(f'echo "Checking S3 bucket: {rid}"')
            lines.append(f"aws s3 ls s3://{rid}/ 2>/dev/null && echo 'Bucket exists' || echo 'Bucket not accessible'")
            lines.append("")
        elif rtype == "dynamodb":
            lines.append(f'echo "Checking DynamoDB table: {rid}"')
            lines.append(f'aws dynamodb describe-table --table-name {rid} --query "Table.TableStatus" --output text')
            lines.append("")
        elif rtype == "lambda":
            lines.append(f'echo "Checking Lambda function: {rid}"')
            lines.append(f'aws lambda get-function --function-name {rid} --query "Configuration.State" --output text')
            lines.append("")

    lines.append('echo "All resources verified."')
    return "\n".join(lines)


def _teardown_script(results: list) -> str:
    lines = [
        "#!/bin/bash",
        "# Nimbus Infrastructure Teardown Script",
        f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "# WARNING: This will delete all resources created by this deployment.",
        "",
        'read -p "Are you sure you want to delete all Nimbus resources? (y/N) " confirm',
        '[ "$confirm" != "y" ] && echo "Cancelled." && exit 0',
        "",
        'echo "Tearing down Nimbus resources..."',
        "",
    ]

    for r in reversed(results):
        rtype = r.get("resource_type")
        rid = r.get("resource_id", "")

        if rtype == "ec2":
            lines.append(f'echo "Terminating EC2 instance: {rid}"')
            lines.append(f"aws ec2 terminate-instances --instance-ids {rid}")
        elif rtype == "s3":
            lines.append(f'echo "Deleting S3 bucket: {rid}"')
            lines.append(f"aws s3 rb s3://{rid} --force")
        elif rtype == "dynamodb":
            lines.append(f'echo "Deleting DynamoDB table: {rid}"')
            lines.append(f"aws dynamodb delete-table --table-name {rid}")
        elif rtype == "lambda":
            lines.append(f'echo "Deleting Lambda function: {rid}"')
            lines.append(f"aws lambda delete-function --function-name {rid}")

        lines.append("")

    lines.append('echo "All resources deleted."')
    return "\n".join(lines)


def _docker_compose(results: list) -> str:
    ec2_instances = [r for r in results if r.get("resource_type") == "ec2"]
    lines = [
        "# Docker Compose for Nimbus-deployed infrastructure",
        f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "# Use this as a local development mirror of your AWS setup.",
        "",
        "version: '3.8'",
        "",
        "services:",
    ]

    for inst in ec2_instances:
        name = inst.get("name", "app").replace(" ", "-").lower()
        lines.extend([
            f"  {name}:",
            "    image: amazonlinux:2",
            "    ports:",
            '      - "80:80"',
            '      - "443:443"',
            f"    # Mirrors EC2 instance: {inst.get('resource_id')}",
            "",
        ])

    dynamo = [r for r in results if r.get("resource_type") == "dynamodb"]
    if dynamo:
        lines.extend([
            "  dynamodb-local:",
            "    image: amazon/dynamodb-local:latest",
            "    ports:",
            '      - "8000:8000"',
            '    command: "-jar DynamoDBLocal.jar -sharedDb"',
            "",
        ])

    return "\n".join(lines)


def _lambda_deploy_script(results: list) -> str:
    lambdas = [r for r in results if r.get("resource_type") == "lambda"]
    lines = [
        "#!/bin/bash",
        "# Lambda Deployment Script",
        f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        'set -e',
        "",
    ]

    for fn in lambdas:
        name = fn.get("resource_id", "")
        lines.extend([
            f'echo "Updating Lambda function: {name}"',
            f"zip -j /tmp/{name}.zip index.py",
            f"aws lambda update-function-code --function-name {name} --zip-file fileb:///tmp/{name}.zip",
            "",
        ])

    return "\n".join(lines)


def _dynamo_seed_script(results: list) -> str:
    tables = [r for r in results if r.get("resource_type") == "dynamodb"]
    lines = [
        "#!/usr/bin/env python3",
        '"""Seed script for DynamoDB tables created by Nimbus."""',
        f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "import boto3",
        "",
        "dynamodb = boto3.resource('dynamodb')",
        "",
    ]

    for table in tables:
        name = table.get("resource_id", "")
        lines.extend([
            f"table = dynamodb.Table('{name}')",
            "table.put_item(Item={",
            "    'id': 'example-1',",
            "    'name': 'Sample Item',",
            "    'created_by': 'nimbus',",
            "})",
            f"print(f'Seeded table: {name}')",
            "",
        ])

    return "\n".join(lines)


def _readme(plan: dict, results: list) -> str:
    lines = [
        "# Nimbus Infrastructure",
        "",
        f"Generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by [Nimbus](https://github.com/nimbus-aws).",
        "",
        "## Resources",
        "",
    ]

    for r in results:
        rtype = r.get("resource_type", "").upper()
        name = r.get("name", "")
        rid = r.get("resource_id", "")
        lines.append(f"- **{rtype}**: {name} (`{rid}`)")

    lines.extend([
        "",
        "## Scripts",
        "",
        "| File | Description |",
        "|------|-------------|",
        "| `setup.sh` | Verify all deployed resources |",
        "| `teardown.sh` | Delete all resources (with confirmation) |",
        "| `nimbus-infra.json` | Full infrastructure manifest |",
        "",
        "## Quick Start",
        "",
        "```bash",
        "# Verify resources",
        "chmod +x setup.sh && ./setup.sh",
        "",
        "# Tear down when done",
        "chmod +x teardown.sh && ./teardown.sh",
        "```",
    ])

    explanation = plan.get("explanation", "")
    if explanation:
        lines.extend(["", "## Architecture", "", explanation])

    return "\n".join(lines)
