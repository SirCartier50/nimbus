"""The single source of truth for which AWS resource types Nimbus can manage.

Every field below was confirmed against the botocore service models actually
installed in this project (see verification notes in DECISIONS.md / the DEV-4
section of docs/archive/HANDOFF-2026-07-18.md), not
assumed from memory — AWS is inconsistent enough across services that
guessing here would silently corrupt delete/describe calls. In particular:

  - Describe vs. delete take DIFFERENT id-parameter shapes for several
    EC2 sub-resources: DescribeVpcs takes `VpcIds` (list) but DeleteVpc takes
    `VpcId` (singular). Same pattern for Subnet/SecurityGroup/NatGateway.
    EC2 *instances* are the exception within EC2 itself — both
    DescribeInstances and TerminateInstances take `InstanceIds` (list).
  - Tagging-at-create works one of five different ways depending on the
    service: EC2's `TagSpecifications` wrapper (keyed by a resource-type
    string like "instance"/"vpc"), a flat `Tags=[{Key,Value}]` list (RDS,
    ELBv2, DynamoDB, ElastiCache, IAM), a flat `tags=[{key,value}]` list with
    lowercase keys (ECS only), a `Tags={str: str}` map (Lambda, API Gateway
    v2), or no tagging support on the create call at all — S3 and CloudFront
    require a separate post-create tagging call with yet another distinct
    shape (S3: PutBucketTagging/Tagging.TagSet; CloudFront: TagResource/
    Tags.Items).
  - The resource id is sometimes only present in the create response under a
    nested path (e.g. `Vpc.VpcId`), and sometimes never echoed back at all
    because it was caller-supplied (S3's bucket name, DynamoDB's table name).

This module only holds verified facts and pure helpers over them — no boto3
calls happen here. `executor.py` is what actually calls AWS.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TagStrategy(Enum):
    NONE = "none"
    EC2_TAG_SPEC = "ec2_tag_spec"            # TagSpecifications=[{ResourceType, Tags:[{Key,Value}]}]
    LIST_KV_CAPITALIZED = "list_kv_capitalized"  # <tag_param>=[{"Key": k, "Value": v}, ...]
    LIST_KV_LOWERCASE = "list_kv_lowercase"      # <tag_param>=[{"key": k, "value": v}, ...]  (ECS only)
    MAP = "map"                                  # <tag_param>={k: v, ...}
    POST_CREATE_S3 = "post_create_s3"
    POST_CREATE_CLOUDFRONT = "post_create_cloudfront"


@dataclass(frozen=True)
class ResourceSpec:
    resource_type: str
    service: str                       # botocore service name, e.g. "ec2"
    create_operation: str
    describe_operation: str
    delete_operation: str
    describe_id_param: str
    describe_id_is_list: bool
    delete_id_param: str
    delete_id_is_list: bool
    create_id_path: str                # dotted/bracket path into the create response, e.g. "Vpc.VpcId"
    tag_strategy: TagStrategy = TagStrategy.NONE
    tag_param: str = "Tags"            # create-call param tags are injected into (ignored for post-create strategies)
    ec2_tag_resource_type: Optional[str] = None  # only for EC2_TAG_SPEC, e.g. "instance", "vpc", "security-group"
    list_operation: Optional[str] = None         # only set when listing-all differs from describe-with-no-id
    delete_requires_etag: bool = False           # CloudFront: DeleteDistribution needs the IfMatch ETag from a prior Get
    post_create_tag_id_path: Optional[str] = None  # path into the create response for the id the tag call needs,
                                                    # when it differs from the resource id itself (CloudFront's
                                                    # TagResource needs the distribution ARN, not its Id)
    notes: str = ""


REGISTRY: dict[str, ResourceSpec] = {
    "ec2_instance": ResourceSpec(
        resource_type="ec2_instance",
        service="ec2",
        create_operation="RunInstances",
        describe_operation="DescribeInstances",
        delete_operation="TerminateInstances",
        describe_id_param="InstanceIds",
        describe_id_is_list=True,
        delete_id_param="InstanceIds",
        delete_id_is_list=True,
        create_id_path="Instances[0].InstanceId",
        tag_strategy=TagStrategy.EC2_TAG_SPEC,
        tag_param="TagSpecifications",
        ec2_tag_resource_type="instance",
    ),
    "s3_bucket": ResourceSpec(
        resource_type="s3_bucket",
        service="s3",
        create_operation="CreateBucket",
        describe_operation="HeadBucket",
        delete_operation="DeleteBucket",
        describe_id_param="Bucket",
        describe_id_is_list=False,
        delete_id_param="Bucket",
        delete_id_is_list=False,
        create_id_path=None,  # CreateBucket's response has no bucket name field — it's caller-supplied
        list_operation="ListBuckets",
        tag_strategy=TagStrategy.POST_CREATE_S3,
        notes="Bucket name comes from the input Bucket param, not the create response. "
              "Empty the bucket (paginated) before DeleteBucket.",
    ),
    "rds_instance": ResourceSpec(
        resource_type="rds_instance",
        service="rds",
        create_operation="CreateDBInstance",
        describe_operation="DescribeDBInstances",
        delete_operation="DeleteDBInstance",
        describe_id_param="DBInstanceIdentifier",
        describe_id_is_list=False,
        delete_id_param="DBInstanceIdentifier",
        delete_id_is_list=False,
        create_id_path="DBInstance.DBInstanceIdentifier",
        tag_strategy=TagStrategy.LIST_KV_CAPITALIZED,
        tag_param="Tags",
    ),
    "lambda_function": ResourceSpec(
        resource_type="lambda_function",
        service="lambda",
        create_operation="CreateFunction",
        describe_operation="GetFunction",
        delete_operation="DeleteFunction",
        describe_id_param="FunctionName",
        describe_id_is_list=False,
        delete_id_param="FunctionName",
        delete_id_is_list=False,
        create_id_path="FunctionName",
        list_operation="ListFunctions",
        tag_strategy=TagStrategy.MAP,
        tag_param="Tags",
    ),
    "vpc": ResourceSpec(
        resource_type="vpc",
        service="ec2",
        create_operation="CreateVpc",
        describe_operation="DescribeVpcs",
        delete_operation="DeleteVpc",
        describe_id_param="VpcIds",
        describe_id_is_list=True,
        delete_id_param="VpcId",
        delete_id_is_list=False,
        create_id_path="Vpc.VpcId",
        tag_strategy=TagStrategy.EC2_TAG_SPEC,
        tag_param="TagSpecifications",
        ec2_tag_resource_type="vpc",
    ),
    "subnet": ResourceSpec(
        resource_type="subnet",
        service="ec2",
        create_operation="CreateSubnet",
        describe_operation="DescribeSubnets",
        delete_operation="DeleteSubnet",
        describe_id_param="SubnetIds",
        describe_id_is_list=True,
        delete_id_param="SubnetId",
        delete_id_is_list=False,
        create_id_path="Subnet.SubnetId",
        tag_strategy=TagStrategy.EC2_TAG_SPEC,
        tag_param="TagSpecifications",
        ec2_tag_resource_type="subnet",
    ),
    "security_group": ResourceSpec(
        resource_type="security_group",
        service="ec2",
        create_operation="CreateSecurityGroup",
        describe_operation="DescribeSecurityGroups",
        delete_operation="DeleteSecurityGroup",
        describe_id_param="GroupIds",
        describe_id_is_list=True,
        delete_id_param="GroupId",
        delete_id_is_list=False,
        create_id_path="GroupId",
        tag_strategy=TagStrategy.EC2_TAG_SPEC,
        tag_param="TagSpecifications",
        ec2_tag_resource_type="security-group",
    ),
    "ecs_cluster": ResourceSpec(
        resource_type="ecs_cluster",
        service="ecs",
        create_operation="CreateCluster",
        describe_operation="DescribeClusters",
        delete_operation="DeleteCluster",
        describe_id_param="clusters",
        describe_id_is_list=True,
        delete_id_param="cluster",
        delete_id_is_list=False,
        create_id_path="cluster.clusterArn",
        list_operation="ListClusters",
        tag_strategy=TagStrategy.LIST_KV_LOWERCASE,
        tag_param="tags",
        notes="ECS is the only service in this registry using lowercase field names "
              "(clusters/cluster/tags) instead of PascalCase.",
    ),
    "load_balancer": ResourceSpec(
        resource_type="load_balancer",
        service="elbv2",
        create_operation="CreateLoadBalancer",
        describe_operation="DescribeLoadBalancers",
        delete_operation="DeleteLoadBalancer",
        describe_id_param="LoadBalancerArns",
        describe_id_is_list=True,
        delete_id_param="LoadBalancerArn",
        delete_id_is_list=False,
        create_id_path="LoadBalancers[0].LoadBalancerArn",
        tag_strategy=TagStrategy.LIST_KV_CAPITALIZED,
        tag_param="Tags",
    ),
    "api_gateway": ResourceSpec(
        resource_type="api_gateway",
        service="apigatewayv2",
        create_operation="CreateApi",
        describe_operation="GetApi",
        delete_operation="DeleteApi",
        describe_id_param="ApiId",
        describe_id_is_list=False,
        delete_id_param="ApiId",
        delete_id_is_list=False,
        create_id_path="ApiId",
        list_operation="GetApis",
        tag_strategy=TagStrategy.MAP,
        tag_param="Tags",
        notes="HTTP API (apigatewayv2), not the older REST API (apigateway) service.",
    ),
    "dynamodb_table": ResourceSpec(
        resource_type="dynamodb_table",
        service="dynamodb",
        create_operation="CreateTable",
        describe_operation="DescribeTable",
        delete_operation="DeleteTable",
        describe_id_param="TableName",
        describe_id_is_list=False,
        delete_id_param="TableName",
        delete_id_is_list=False,
        create_id_path="TableDescription.TableName",
        list_operation="ListTables",
        tag_strategy=TagStrategy.LIST_KV_CAPITALIZED,
        tag_param="Tags",
    ),
    "elasticache": ResourceSpec(
        resource_type="elasticache",
        service="elasticache",
        create_operation="CreateCacheCluster",
        describe_operation="DescribeCacheClusters",
        delete_operation="DeleteCacheCluster",
        describe_id_param="CacheClusterId",
        describe_id_is_list=False,
        delete_id_param="CacheClusterId",
        delete_id_is_list=False,
        create_id_path="CacheCluster.CacheClusterId",
        tag_strategy=TagStrategy.LIST_KV_CAPITALIZED,
        tag_param="Tags",
        notes="CacheClusterId is caller-supplied and required on create, unlike most other ids here.",
    ),
    "cloudfront": ResourceSpec(
        resource_type="cloudfront",
        service="cloudfront",
        create_operation="CreateDistribution",
        describe_operation="GetDistribution",
        delete_operation="DeleteDistribution",
        describe_id_param="Id",
        describe_id_is_list=False,
        delete_id_param="Id",
        delete_id_is_list=False,
        create_id_path="Distribution.Id",
        list_operation="ListDistributions",
        tag_strategy=TagStrategy.POST_CREATE_CLOUDFRONT,
        delete_requires_etag=True,
        post_create_tag_id_path="Distribution.ARN",
        notes="DeleteDistribution requires IfMatch (the ETag from a GetDistribution call) and the "
              "distribution must already be disabled and fully deployed — both are executor-level "
              "preconditions, not something the registry can encode.",
    ),
    "nat_gateway": ResourceSpec(
        resource_type="nat_gateway",
        service="ec2",
        create_operation="CreateNatGateway",
        describe_operation="DescribeNatGateways",
        delete_operation="DeleteNatGateway",
        describe_id_param="NatGatewayIds",
        describe_id_is_list=True,
        delete_id_param="NatGatewayId",
        delete_id_is_list=False,
        create_id_path="NatGateway.NatGatewayId",
        tag_strategy=TagStrategy.EC2_TAG_SPEC,
        tag_param="TagSpecifications",
        ec2_tag_resource_type="natgateway",
    ),
    "iam_role": ResourceSpec(
        resource_type="iam_role",
        service="iam",
        create_operation="CreateRole",
        describe_operation="GetRole",
        delete_operation="DeleteRole",
        describe_id_param="RoleName",
        describe_id_is_list=False,
        delete_id_param="RoleName",
        delete_id_is_list=False,
        create_id_path="Role.RoleName",
        list_operation="ListRoles",
        tag_strategy=TagStrategy.LIST_KV_CAPITALIZED,
        tag_param="Tags",
    ),
}


def get_spec(resource_type: str) -> ResourceSpec:
    try:
        return REGISTRY[resource_type]
    except KeyError:
        raise ValueError(
            f"Unknown resource_type '{resource_type}'. Supported: {sorted(REGISTRY)}"
        )


# ---------------------------------------------------------------------------
# Pure helpers — id extraction and id-parameter construction
# ---------------------------------------------------------------------------


def extract_path(data: dict, path: str):
    """Walk a dotted/bracket path like 'Instances[0].InstanceId' through a dict."""
    current = data
    for part in path.replace("]", "").split("."):
        if "[" in part:
            key, idx = part.split("[")
            current = current[key][int(idx)]
        else:
            current = current[part]
    return current


def extract_resource_id(resource_type: str, create_response: dict, input_params: dict) -> str:
    """Pull the resource's id out of a create call's response.

    Falls back to the input params when the AWS API doesn't echo the id back
    (S3's bucket name is caller-supplied and never appears in CreateBucket's
    response body).
    """
    spec = get_spec(resource_type)
    if spec.create_id_path:
        return extract_path(create_response, spec.create_id_path)
    return input_params[spec.describe_id_param]


def build_id_kwargs(resource_type: str, resource_id: str, op_kind: str) -> dict:
    """Build the {param_name: value_or_[value]} kwargs for a describe/delete call.

    op_kind is "describe" or "delete" — the two calls take different shapes
    for several EC2 sub-resources (see module docstring).
    """
    spec = get_spec(resource_type)
    if op_kind == "describe":
        param, is_list = spec.describe_id_param, spec.describe_id_is_list
    elif op_kind == "delete":
        param, is_list = spec.delete_id_param, spec.delete_id_is_list
    else:
        raise ValueError("op_kind must be 'describe' or 'delete'")
    return {param: [resource_id] if is_list else resource_id}


# ---------------------------------------------------------------------------
# Pure helpers — tagging
# ---------------------------------------------------------------------------


def merge_tags_into_config(resource_type: str, config: dict, tags: dict) -> dict:
    """Return a copy of `config` with `tags` merged into it for create-time tag
    strategies. Tags we own (e.g. ManagedBy=Nimbus) win over anything the model
    already put in `config` for the same key. No-op for post-create strategies
    — call get_post_create_tag_call() for those instead, after the resource exists.
    """
    spec = get_spec(resource_type)
    config = dict(config)

    if spec.tag_strategy == TagStrategy.NONE or spec.tag_strategy in (
        TagStrategy.POST_CREATE_S3,
        TagStrategy.POST_CREATE_CLOUDFRONT,
    ):
        return config

    if spec.tag_strategy == TagStrategy.EC2_TAG_SPEC:
        tag_specs = list(config.get(spec.tag_param, []))
        existing = next(
            (ts for ts in tag_specs if ts.get("ResourceType") == spec.ec2_tag_resource_type), None
        )
        if existing is None:
            existing = {"ResourceType": spec.ec2_tag_resource_type, "Tags": []}
            tag_specs.append(existing)
        existing_keys = {t["Key"] for t in existing["Tags"]}
        existing["Tags"] = [t for t in existing["Tags"] if t["Key"] not in tags] + [
            {"Key": k, "Value": v} for k, v in tags.items()
        ]
        config[spec.tag_param] = tag_specs
        return config

    if spec.tag_strategy == TagStrategy.LIST_KV_CAPITALIZED:
        existing = list(config.get(spec.tag_param, []))
        existing = [t for t in existing if t.get("Key") not in tags]
        existing += [{"Key": k, "Value": v} for k, v in tags.items()]
        config[spec.tag_param] = existing
        return config

    if spec.tag_strategy == TagStrategy.LIST_KV_LOWERCASE:
        existing = list(config.get(spec.tag_param, []))
        existing = [t for t in existing if t.get("key") not in tags]
        existing += [{"key": k, "value": v} for k, v in tags.items()]
        config[spec.tag_param] = existing
        return config

    if spec.tag_strategy == TagStrategy.MAP:
        merged = dict(config.get(spec.tag_param, {}))
        merged.update(tags)
        config[spec.tag_param] = merged
        return config

    return config


def get_post_create_tag_call(resource_type: str, create_response: dict, resource_id: str, tags: dict):
    """For resources whose create call can't carry tags (S3, CloudFront), build
    the (operation, params) for the follow-up tagging call. Returns None for
    every other resource type, since their tags were already applied at create.

    `create_response` is needed because CloudFront's TagResource takes the
    distribution's ARN, not its Id (the value extract_resource_id() returns) —
    post_create_tag_id_path resolves that distinction when it applies.
    """
    spec = get_spec(resource_type)
    if spec.tag_strategy not in (TagStrategy.POST_CREATE_S3, TagStrategy.POST_CREATE_CLOUDFRONT):
        return None

    target_id = (
        extract_path(create_response, spec.post_create_tag_id_path)
        if spec.post_create_tag_id_path
        else resource_id
    )

    if spec.tag_strategy == TagStrategy.POST_CREATE_S3:
        return {
            "operation": "PutBucketTagging",
            "params": {
                "Bucket": target_id,
                "Tagging": {"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]},
            },
        }

    return {
        "operation": "TagResource",
        "params": {
            "Resource": target_id,
            "Tags": {"Items": [{"Key": k, "Value": v} for k, v in tags.items()]},
        },
    }
