#!/usr/bin/env python3
"""CDK app entry point for Backcast's AWS infrastructure."""

import os

import aws_cdk as cdk

from backcast_infra.stack import BackcastStack

app = cdk.App()

BackcastStack(
    app,
    "BackcastStack",
    description="Backcast — agentic SRE memory: Lambda + Bedrock + S3 + EventBridge over CockroachDB",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)

app.synth()
