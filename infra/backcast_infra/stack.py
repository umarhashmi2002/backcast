"""The Backcast AWS stack.

Serverless and cost-frugal: three container Lambdas (ingest / commander /
consolidate) share one image, reason with Amazon Bedrock, store artifacts in S3,
read the CockroachDB DSN from Secrets Manager, and are scheduled + observed via
EventBridge and CloudWatch. IAM is least-privilege per function.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    SecretValue,
    Stack,
)
from aws_cdk import (
    aws_cloudwatch as cw,
)
from aws_cdk import (
    aws_ecr_assets as ecr_assets,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as targets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_secretsmanager as sm,
)
from constructs import Construct

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Intended reasoning model. Override at deploy time with
#   cdk deploy -c bedrock_model_id=<id>
# e.g. us.amazon.nova-pro-v1:0 until Anthropic use-case access is enabled.
_BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-5"
_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"


class BackcastStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- S3: raw alert artifacts + signed incident packages --------------
        artifacts = s3.Bucket(
            self,
            "Artifacts",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,  # demo convenience
            auto_delete_objects=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(90))],
        )

        # --- Secrets Manager: the CockroachDB DSN ----------------------------
        # Created with a placeholder; set the real value after deploy:
        #   aws secretsmanager put-secret-value --secret-id backcast/database-url \
        #       --secret-string '{"url":"postgresql://...:26257/backcast?sslmode=verify-full"}'
        db_secret = sm.Secret(
            self,
            "DbSecret",
            secret_name="backcast/database-url",
            description="CockroachDB DSN used by Backcast Lambdas",
            secret_string_value=SecretValue.unsafe_plain_text('{"url":"REPLACE_ME"}'),
        )

        model_id = self.node.try_get_context("bedrock_model_id") or _BEDROCK_MODEL_ID
        common_env = {
            "BACKCAST_ENV": "prod",
            "BACKCAST_LOG_LEVEL": "INFO",
            "BACKCAST_DATABASE_SECRET": db_secret.secret_name,
            "BACKCAST_ARTIFACT_BUCKET": artifacts.bucket_name,
            "BACKCAST_BEDROCK_MODEL_ID": model_id,
            "BACKCAST_EMBEDDING_MODEL_ID": _EMBEDDING_MODEL_ID,
        }

        def make_fn(name: str, handler: str, memory: int, timeout_s: int) -> lambda_.DockerImageFunction:
            return lambda_.DockerImageFunction(
                self,
                name,
                code=lambda_.DockerImageCode.from_image_asset(
                    directory=str(_REPO_ROOT),
                    file="Dockerfile",
                    cmd=[handler],
                    platform=ecr_assets.Platform.LINUX_ARM64,
                ),
                architecture=lambda_.Architecture.ARM_64,
                memory_size=memory,
                timeout=Duration.seconds(timeout_s),
                environment=common_env,
            )

        ingest_fn = make_fn("IngestFn", "backcast.api.ingest.handler", 512, 30)
        commander_fn = make_fn("CommanderFn", "backcast.api.commander.handler", 1024, 120)
        consolidate_fn = make_fn("ConsolidateFn", "backcast.api.consolidate.handler", 512, 300)
        functions = [ingest_fn, commander_fn, consolidate_fn]

        # --- IAM: least privilege per function -------------------------------
        for fn in functions:
            db_secret.grant_read(fn)

        artifacts.grant_write(ingest_fn)
        artifacts.grant_read(commander_fn)
        artifacts.grant_read_write(consolidate_fn)

        bedrock_invoke = iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                "arn:aws:bedrock:*::foundation-model/anthropic.*",
                "arn:aws:bedrock:*::foundation-model/amazon.*",  # Titan embeddings + Nova
                f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
            ],
        )
        commander_fn.add_to_role_policy(bedrock_invoke)
        consolidate_fn.add_to_role_policy(bedrock_invoke)

        # --- HTTPS entry points (Lambda Function URLs) -----------------------
        cors = lambda_.FunctionUrlCorsOptions(
            allowed_origins=["*"], allowed_methods=[lambda_.HttpMethod.ALL]
        )
        ingest_url = ingest_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE, cors=cors
        )
        commander_url = commander_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE, cors=cors
        )

        # --- EventBridge: scheduled consolidation ----------------------------
        events.Rule(
            self,
            "ConsolidateSchedule",
            description="Hourly evidence-preserving consolidation of resolved incidents",
            schedule=events.Schedule.rate(Duration.hours(1)),
            targets=[targets.LambdaFunction(consolidate_fn)],
        )

        # --- CloudWatch: alarms + dashboard ----------------------------------
        for fn in functions:
            fn.metric_errors(period=Duration.minutes(5)).create_alarm(
                self,
                f"{fn.node.id}ErrorsAlarm",
                threshold=1,
                evaluation_periods=1,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                alarm_description=f"{fn.node.id} reported errors",
            )

        dashboard = cw.Dashboard(self, "Dashboard", dashboard_name="Backcast")
        dashboard.add_widgets(
            cw.GraphWidget(title="Invocations", left=[f.metric_invocations() for f in functions]),
            cw.GraphWidget(title="Errors", left=[f.metric_errors() for f in functions]),
            cw.GraphWidget(
                title="Duration p95",
                left=[f.metric_duration(statistic="p95") for f in functions],
            ),
        )

        # --- Outputs ---------------------------------------------------------
        CfnOutput(self, "IngestUrl", value=ingest_url.url, description="POST alerts here")
        CfnOutput(self, "CommanderUrl", value=commander_url.url, description="POST agent turns here")
        CfnOutput(self, "ArtifactBucket", value=artifacts.bucket_name)
        CfnOutput(self, "DatabaseSecretName", value=db_secret.secret_name)
