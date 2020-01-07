import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *

# flake8: noqa
import boto3
import json
import datetime  # type: ignore
from botocore.config import Config
from botocore.parsers import ResponseParserError
import urllib3.util

# Disable insecure warnings
urllib3.disable_warnings()

"""PARAMETERS"""
AWS_DEFAULT_REGION = demisto.params().get('defaultRegion')
AWS_ROLE_ARN = demisto.params().get('roleArn')
AWS_ROLE_SESSION_NAME = demisto.params().get('roleSessionName')
AWS_ROLE_SESSION_DURATION = demisto.params().get('sessionDuration')
AWS_ROLE_POLICY = None
AWS_ACCESS_KEY_ID = demisto.params().get('access_key')
AWS_SECRET_ACCESS_KEY = demisto.params().get('secret_key')
VERIFY_CERTIFICATE = not demisto.params().get('insecure', True)
proxies = handle_proxy(proxy_param_name='proxy', checkbox_default_value=False)
config = Config(
    connect_timeout=1,
    retries=dict(
        max_attempts=5
    ),
    proxies=proxies
)

"""HELPER FUNCTIONS"""


def safe_load_json(o):
    kwargs = None
    if len(o) > 40:
        try:
            kwargs = json.loads(o)
        except json.decoder.JSONDecodeError as e:
            return_error(
                'Unable to parse JSON string. Please verify the JSON is valid. - ' + str(e))
    else:
        try:
            path = demisto.getFilePath(o)
            with open(path['path'], 'rb') as data:
                try:
                    kwargs = json.load(data)
                except:
                    kwargs = json.loads(data.read())
        except Exception as e:
            return_error('Unable to parse JSON file. Please verify the JSON is valid or the Entry'
                         'ID is correct. - ' + str(e))
    return kwargs


def myconverter(o):
    if isinstance(o, datetime.datetime):  # type: ignore
        return o.__str__()


def remove_empty_elements(d):
    """recursively remove empty lists, empty dicts, or None elements from a dictionary"""

    def empty(x):
        return x is None or x == {} or x == []

    if not isinstance(d, (dict, list)):
        return d
    elif isinstance(d, list):
        return [v for v in (remove_empty_elements(v) for v in d) if not empty(v)]
    else:
        return {k: v for k, v in ((k, remove_empty_elements(v)) for k, v in d.items()) if
                not empty(v)}


def parse_tag_field(tags_str):
    tags = []
    regex = re.compile(r'key=([\w\d_:.-]+),value=([ /\w\d@_,.*-]+)', flags=re.I)
    if demisto.args().get('tag_key') and demisto.args().get('tag_value'):
        if demisto.args().get('tags'):
            return_error(
                "Please select either the arguments 'tag_key' and 'tag_value' or only 'tags'.")
        tags.append({
            'Key': demisto.args().get('tag_key'),
            'Value': demisto.args().get('tag_value')
        })
    else:
        if tags_str is not None:
            for f in tags_str.split(';'):
                match = regex.match(f)
                if match is None:
                    demisto.log('could not parse field: %s' % (f,))
                    continue

                tags.append({
                    'Key': match.group(1),
                    'Value': match.group(2)
                })

    return tags


def aws_session(service='dynamodb', region=None, roleArn=None, roleSessionName=None,
                roleSessionDuration=None, rolePolicy=None):
    kwargs = {}
    if roleArn and roleSessionName is not None:
        kwargs.update({
            'RoleArn': roleArn,
            'RoleSessionName': roleSessionName,
        })
    elif AWS_ROLE_ARN and AWS_ROLE_SESSION_NAME is not None:
        kwargs.update({
            'RoleArn': AWS_ROLE_ARN,
            'RoleSessionName': AWS_ROLE_SESSION_NAME,
        })

    if roleSessionDuration is not None:
        kwargs.update({'DurationSeconds': int(roleSessionDuration)})
    elif AWS_ROLE_SESSION_DURATION is not None:
        kwargs.update({'DurationSeconds': int(AWS_ROLE_SESSION_DURATION)})

    if rolePolicy is not None:
        kwargs.update({'Policy': rolePolicy})
    elif AWS_ROLE_POLICY is not None:
        kwargs.update({'Policy': AWS_ROLE_POLICY})
    if kwargs and AWS_ACCESS_KEY_ID is None:

        if AWS_ACCESS_KEY_ID is None:
            sts_client = boto3.client('sts', config=config, verify=VERIFY_CERTIFICATE)
            sts_response = sts_client.assume_role(**kwargs)
            if region is not None:
                client = boto3.client(
                    service_name=service,
                    region_name=region,
                    aws_access_key_id=sts_response['Credentials']['AccessKeyId'],
                    aws_secret_access_key=sts_response['Credentials']['SecretAccessKey'],
                    aws_session_token=sts_response['Credentials']['SessionToken'],
                    verify=VERIFY_CERTIFICATE,
                    config=config
                )
            else:
                client = boto3.client(
                    service_name=service,
                    region_name=AWS_DEFAULT_REGION,
                    aws_access_key_id=sts_response['Credentials']['AccessKeyId'],
                    aws_secret_access_key=sts_response['Credentials']['SecretAccessKey'],
                    aws_session_token=sts_response['Credentials']['SessionToken'],
                    verify=VERIFY_CERTIFICATE,
                    config=config
                )
    elif AWS_ACCESS_KEY_ID and AWS_ROLE_ARN:
        sts_client = boto3.client(
            service_name='sts',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            verify=VERIFY_CERTIFICATE,
            config=config
        )
        kwargs.update({
            'RoleArn': AWS_ROLE_ARN,
            'RoleSessionName': AWS_ROLE_SESSION_NAME,
        })
        sts_response = sts_client.assume_role(**kwargs)
        client = boto3.client(
            service_name=service,
            region_name=AWS_DEFAULT_REGION,
            aws_access_key_id=sts_response['Credentials']['AccessKeyId'],
            aws_secret_access_key=sts_response['Credentials']['SecretAccessKey'],
            aws_session_token=sts_response['Credentials']['SessionToken'],
            verify=VERIFY_CERTIFICATE,
            config=config
        )
    else:
        if region is not None:
            client = boto3.client(
                service_name=service,
                region_name=region,
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                verify=VERIFY_CERTIFICATE,
                config=config
            )
        else:
            client = boto3.client(
                service_name=service,
                region_name=AWS_DEFAULT_REGION,
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                verify=VERIFY_CERTIFICATE,
                config=config
            )

    return client


def batch_get_item_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "RequestItems": json.loads(args.get("request_items", "{}")),
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.batch_get_item(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB BatchGetItem',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB BatchGetItem', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB BatchGetItem', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB BatchGetItem', response)
    return human_readable, outputs


def batch_write_item_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "RequestItems": json.loads(args.get("request_items", "{}")),
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None),
        "ReturnItemCollectionMetrics": args.get("return_item_collection_metrics", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.batch_write_item(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB BatchWriteItem',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB BatchWriteItem', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB BatchWriteItem', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB BatchWriteItem', response)
    return human_readable, outputs


def create_backup_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "BackupName": args.get("backup_name", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.create_backup(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.BackupDetails(val.BackupArn && val.BackupArn == obj.BackupArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB CreateBackup',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB CreateBackup', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB CreateBackup', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB CreateBackup', response)
    return human_readable, outputs


def create_global_table_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "GlobalTableName": args.get("global_table_name", None),
        "ReplicationGroup": safe_load_json(args.get("ReplicationGroup")) if args.get(
            "ReplicationGroup") else [{
            "Replica": {
                "RegionName": args.get("replica_region_name", None)
            },

        }],

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.create_global_table(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.GlobalTableDescription(val.GlobalTableArn && val.GlobalTableArn == '
        'obj.GlobalTableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB CreateGlobalTable',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB CreateGlobalTable', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB CreateGlobalTable', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB CreateGlobalTable', response)
    return human_readable, outputs


def create_table_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "AttributeDefinitions": safe_load_json(args.get("AttributeDefinitions")) if args.get(
            "AttributeDefinitions") else [{
            "AttributeDefinition": {
                "AttributeName": args.get("attribute_definition_attribute_name", None),
                "AttributeType": args.get("attribute_definition_attribute_type", None)
            },

        }],
        "TableName": args.get("table_name", None),
        "KeySchema": safe_load_json(args.get("KeySchema")) if args.get("KeySchema") else [{
            "KeySchemaElement": {
                "AttributeName": args.get("key_schema_element_attribute_name", None),
                "KeyType": args.get("key_schema_element_key_type", None)
            },

        }],
        "LocalSecondaryIndexes": safe_load_json(args.get("LocalSecondaryIndexes")) if args.get(
            "LocalSecondaryIndexes") else [{
            "LocalSecondaryIndex": {
                "IndexName": args.get("local_secondary_index_index_name", None),
                "KeySchema": safe_load_json(args.get("KeySchema")) if args.get("KeySchema") else [{
                    "KeySchemaElement": {
                        "AttributeName": args.get("key_schema_element_attribute_name", None),
                        "KeyType": args.get("key_schema_element_key_type", None)
                    },

                }],
                "Projection": {
                    "ProjectionType": args.get("projection_projection_type", None),
                    "NonKeyAttributes": safe_load_json(args.get("NonKeyAttributes")) if args.get(
                        "NonKeyAttributes") else [{
                        "NonKeyAttributeName": args.get("non_key_attributes_non_key_attribute_name",
                                                        None),

                    }],

                }

            },

        }],
        "GlobalSecondaryIndexes": safe_load_json(args.get("GlobalSecondaryIndexes")) if args.get(
            "GlobalSecondaryIndexes") else [{
            "GlobalSecondaryIndex": {
                "IndexName": args.get("global_secondary_index_index_name", None),
                "KeySchema": safe_load_json(args.get("KeySchema")) if args.get("KeySchema") else [{
                    "KeySchemaElement": {
                        "AttributeName": args.get("key_schema_element_attribute_name", None),
                        "KeyType": args.get("key_schema_element_key_type", None)
                    },

                }],
                "Projection": {
                    "ProjectionType": args.get("projection_projection_type", None),
                    "NonKeyAttributes": safe_load_json(args.get("NonKeyAttributes")) if args.get(
                        "NonKeyAttributes") else [{
                        "NonKeyAttributeName": args.get("non_key_attributes_non_key_attribute_name",
                                                        None),

                    }],

                },
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": args.get("provisioned_throughput_read_capacity_units",
                                                  None),
                    "WriteCapacityUnits": args.get("provisioned_throughput_write_capacity_units",
                                                   None),

                }

            },

        }],
        "BillingMode": args.get("billing_mode", None),
        "ProvisionedThroughput": {
            "ReadCapacityUnits": args.get("provisioned_throughput_read_capacity_units", None),
            "WriteCapacityUnits": args.get("provisioned_throughput_write_capacity_units", None),

        },
        "StreamSpecification": {
            "StreamEnabled": True if args.get("stream_specification_stream_enabled",
                                              "") == "true" else None,
            "StreamViewType": args.get("stream_specification_stream_view_type", None),

        },
        "SSESpecification": {
            "Enabled": True if args.get("sse_specification_enabled", "") == "true" else None,
            "SSEType": args.get("sse_specification_sse_type", None),
            "KMSMasterKeyId": args.get("sse_specification_kms_master_key_id", None),

        },
        "Tags": parse_tag_field(args.get("tags")),

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.create_table(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.TableDescription(val.TableArn && val.TableArn == obj.TableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB CreateTable',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB CreateTable', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB CreateTable', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB CreateTable', response)
    return human_readable, outputs


def delete_backup_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "BackupArn": args.get("backup_arn", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.delete_backup(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.BackupDescriptionBackupDetails(val.BackupArn && val.BackupArn == '
        'obj.BackupArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DeleteBackup',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DeleteBackup', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DeleteBackup', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DeleteBackup', response)
    return human_readable, outputs


def delete_item_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "Key": json.loads(args.get("key", "{}")),
        "Expected": json.loads(args.get("expected", "{}")),
        "ConditionalOperator": args.get("conditional_operator", None),
        "ReturnValues": args.get("return_values", None),
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None),
        "ReturnItemCollectionMetrics": args.get("return_item_collection_metrics", None),
        "ConditionExpression": args.get("condition_expression", None),
        "ExpressionAttributeNames": json.loads(args.get("expression_attribute_names", "{}")),
        "ExpressionAttributeValues": json.loads(args.get("expression_attribute_values", "{}"))
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.delete_item(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DeleteItem',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DeleteItem', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DeleteItem', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DeleteItem', response)
    return human_readable, outputs


def delete_table_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.delete_table(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.TableDescription(val.TableArn && val.TableArn == obj.TableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DeleteTable',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DeleteTable', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DeleteTable', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DeleteTable', response)
    return human_readable, outputs


def describe_backup_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "BackupArn": args.get("backup_arn", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.describe_backup(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.BackupDescriptionBackupDetails(val.BackupArn && val.BackupArn == '
        'obj.BackupArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DescribeBackup',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DescribeBackup', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DescribeBackup', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DescribeBackup', response)
    return human_readable, outputs


def describe_continuous_backups_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.describe_continuous_backups(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DescribeContinuousBackups',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DescribeContinuousBackups', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DescribeContinuousBackups', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DescribeContinuousBackups', response)
    return human_readable, outputs


def describe_endpoints_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.describe_endpoints(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DescribeEndpoints',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DescribeEndpoints', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DescribeEndpoints', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DescribeEndpoints', response)
    return human_readable, outputs


def describe_global_table_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "GlobalTableName": args.get("global_table_name", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.describe_global_table(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.GlobalTableDescription(val.GlobalTableArn && val.GlobalTableArn == '
        'obj.GlobalTableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DescribeGlobalTable',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DescribeGlobalTable', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DescribeGlobalTable', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DescribeGlobalTable', response)
    return human_readable, outputs


def describe_global_table_settings_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "GlobalTableName": args.get("global_table_name", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.describe_global_table_settings(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB'
        '.ReplicaSettingsReplicaSettingsDescriptionReplicaProvisionedReadCapacityAutoScalingSettings(val.AutoScalingRoleArn && val.AutoScalingRoleArn == obj.AutoScalingRoleArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DescribeGlobalTableSettings',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DescribeGlobalTableSettings',
                                                 response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DescribeGlobalTableSettings', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DescribeGlobalTableSettings', response)
    return human_readable, outputs


def describe_limits_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.describe_limits(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DescribeLimits',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DescribeLimits', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DescribeLimits', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DescribeLimits', response)
    return human_readable, outputs


def describe_table_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.describe_table(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB.Table(val.TableArn && val.TableArn == obj.TableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DescribeTable',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DescribeTable', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DescribeTable', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DescribeTable', response)
    return human_readable, outputs


def describe_time_to_live_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.describe_time_to_live(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB DescribeTimeToLive',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB DescribeTimeToLive', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB DescribeTimeToLive', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB DescribeTimeToLive', response)
    return human_readable, outputs


def get_item_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "Key": json.loads(args.get("key", "{}")),
        "AttributesToGet": safe_load_json(args.get("AttributesToGet")) if args.get(
            "AttributesToGet") else [{
            "AttributeName": args.get("attributes_to_get_attribute_name", None),

        }],
        "ConsistentRead": True if args.get("consistent_read", "") == "true" else None,
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None),
        "ProjectionExpression": args.get("projection_expression", None),
        "ExpressionAttributeNames": json.loads(args.get("expression_attribute_names", "{}"))
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.get_item(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB GetItem',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB GetItem', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB GetItem', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB GetItem', response)
    return human_readable, outputs


def list_backups_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "ExclusiveStartBackupArn": args.get("exclusive_start_backup_arn", None),
        "BackupType": args.get("backup_type", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.list_backups(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.BackupSummariesBackupSummary(val.TableArn && val.TableArn == '
        'obj.TableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB ListBackups',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB ListBackups', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB ListBackups', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB ListBackups', response)
    return human_readable, outputs


def list_global_tables_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "ExclusiveStartGlobalTableName": args.get("exclusive_start_global_table_name", None),
        "RegionName": args.get("region_name", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.list_global_tables(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB ListGlobalTables',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB ListGlobalTables', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB ListGlobalTables', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB ListGlobalTables', response)
    return human_readable, outputs


def list_tables_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "ExclusiveStartTableName": args.get("exclusive_start_table_name", None),

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.list_tables(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB ListTables',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB ListTables', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB ListTables', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB ListTables', response)
    return human_readable, outputs


def list_tags_of_resource_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "ResourceArn": args.get("resource_arn", None),
        "NextToken": args.get("next_token", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.list_tags_of_resource(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB ListTagsOfResource',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB ListTagsOfResource', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB ListTagsOfResource', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB ListTagsOfResource', response)
    return human_readable, outputs


def put_item_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "Item": json.loads(args.get("item", "{}")),
        "Expected": json.loads(args.get("expected", "{}")),
        "ReturnValues": args.get("return_values", None),
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None),
        "ReturnItemCollectionMetrics": args.get("return_item_collection_metrics", None),
        "ConditionalOperator": args.get("conditional_operator", None),
        "ConditionExpression": args.get("condition_expression", None),
        "ExpressionAttributeNames": json.loads(args.get("expression_attribute_names", "{}")),
        "ExpressionAttributeValues": json.loads(args.get("expression_attribute_values", "{}"))
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.put_item(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB PutItem',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB PutItem', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB PutItem', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB PutItem', response)
    return human_readable, outputs


def query_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "IndexName": args.get("index_name", None),
        "Select": args.get("select", None),
        "AttributesToGet": safe_load_json(args.get("AttributesToGet")) if args.get(
            "AttributesToGet") else [{
            "AttributeName": args.get("attributes_to_get_attribute_name", None),

        }],
        "ConsistentRead": True if args.get("consistent_read", "") == "true" else None,
        "KeyConditions": json.loads(args.get("key_conditions", "{}")),
        "QueryFilter": json.loads(args.get("query_filter", "{}")),
        "ConditionalOperator": args.get("conditional_operator", None),
        "ScanIndexForward": True if args.get("scan_index_forward", "") == "true" else None,
        "ExclusiveStartKey": json.loads(args.get("exclusive_start_key", "{}")),
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None),
        "ProjectionExpression": args.get("projection_expression", None),
        "FilterExpression": args.get("filter_expression", None),
        "KeyConditionExpression": args.get("key_condition_expression", None),
        "ExpressionAttributeNames": json.loads(args.get("expression_attribute_names", "{}")),
        "ExpressionAttributeValues": json.loads(args.get("expression_attribute_values", "{}"))
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.query(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB Query',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB Query', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB Query', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB Query', response)
    return human_readable, outputs


def restore_table_from_backup_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TargetTableName": args.get("target_table_name", None),
        "BackupArn": args.get("backup_arn", None),
        "BillingModeOverride": args.get("billing_mode_override", None),
        "GlobalSecondaryIndexOverride": safe_load_json(
            args.get("GlobalSecondaryIndexOverride")) if args.get(
            "GlobalSecondaryIndexOverride") else [{
            "GlobalSecondaryIndex": {
                "IndexName": args.get("global_secondary_index_index_name", None),
                "KeySchema": safe_load_json(args.get("KeySchema")) if args.get("KeySchema") else [{
                    "KeySchemaElement": {
                        "AttributeName": args.get("key_schema_element_attribute_name", None),
                        "KeyType": args.get("key_schema_element_key_type", None)
                    },

                }],
                "Projection": {
                    "ProjectionType": args.get("projection_projection_type", None),
                    "NonKeyAttributes": safe_load_json(args.get("NonKeyAttributes")) if args.get(
                        "NonKeyAttributes") else [{
                        "NonKeyAttributeName": args.get("non_key_attributes_non_key_attribute_name",
                                                        None),

                    }],

                },
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": args.get("provisioned_throughput_read_capacity_units",
                                                  None),
                    "WriteCapacityUnits": args.get("provisioned_throughput_write_capacity_units",
                                                   None),

                }

            },

        }],
        "LocalSecondaryIndexOverride": safe_load_json(
            args.get("LocalSecondaryIndexOverride")) if args.get(
            "LocalSecondaryIndexOverride") else [{
            "LocalSecondaryIndex": {
                "IndexName": args.get("local_secondary_index_index_name", None),
                "KeySchema": safe_load_json(args.get("KeySchema")) if args.get("KeySchema") else [{
                    "KeySchemaElement": {
                        "AttributeName": args.get("key_schema_element_attribute_name", None),
                        "KeyType": args.get("key_schema_element_key_type", None)
                    },

                }],
                "Projection": {
                    "ProjectionType": args.get("projection_projection_type", None),
                    "NonKeyAttributes": safe_load_json(args.get("NonKeyAttributes")) if args.get(
                        "NonKeyAttributes") else [{
                        "NonKeyAttributeName": args.get("non_key_attributes_non_key_attribute_name",
                                                        None),

                    }],

                }

            },

        }],
        "ProvisionedThroughputOverride": {
            "ReadCapacityUnits": args.get("provisioned_throughput_override_read_capacity_units",
                                          None),
            "WriteCapacityUnits": args.get("provisioned_throughput_override_write_capacity_units",
                                           None),

        }

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.restore_table_from_backup(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.TableDescription(val.TableArn && val.TableArn == obj.TableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB RestoreTableFromBackup',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB RestoreTableFromBackup', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB RestoreTableFromBackup', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB RestoreTableFromBackup', response)
    return human_readable, outputs


def restore_table_to_point_in_time_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "SourceTableName": args.get("source_table_name", None),
        "TargetTableName": args.get("target_table_name", None),
        "UseLatestRestorableTime": True if args.get("use_latest_restorable_time",
                                                    "") == "true" else None,
        "BillingModeOverride": args.get("billing_mode_override", None),
        "GlobalSecondaryIndexOverride": safe_load_json(
            args.get("GlobalSecondaryIndexOverride")) if args.get(
            "GlobalSecondaryIndexOverride") else [{
            "GlobalSecondaryIndex": {
                "IndexName": args.get("global_secondary_index_index_name", None),
                "KeySchema": safe_load_json(args.get("KeySchema")) if args.get("KeySchema") else [{
                    "KeySchemaElement": {
                        "AttributeName": args.get("key_schema_element_attribute_name", None),
                        "KeyType": args.get("key_schema_element_key_type", None)
                    },

                }],
                "Projection": {
                    "ProjectionType": args.get("projection_projection_type", None),
                    "NonKeyAttributes": safe_load_json(args.get("NonKeyAttributes")) if args.get(
                        "NonKeyAttributes") else [{
                        "NonKeyAttributeName": args.get("non_key_attributes_non_key_attribute_name",
                                                        None),

                    }],

                },
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": args.get("provisioned_throughput_read_capacity_units",
                                                  None),
                    "WriteCapacityUnits": args.get("provisioned_throughput_write_capacity_units",
                                                   None),

                }

            },

        }],
        "LocalSecondaryIndexOverride": safe_load_json(
            args.get("LocalSecondaryIndexOverride")) if args.get(
            "LocalSecondaryIndexOverride") else [{
            "LocalSecondaryIndex": {
                "IndexName": args.get("local_secondary_index_index_name", None),
                "KeySchema": safe_load_json(args.get("KeySchema")) if args.get("KeySchema") else [{
                    "KeySchemaElement": {
                        "AttributeName": args.get("key_schema_element_attribute_name", None),
                        "KeyType": args.get("key_schema_element_key_type", None)
                    },

                }],
                "Projection": {
                    "ProjectionType": args.get("projection_projection_type", None),
                    "NonKeyAttributes": safe_load_json(args.get("NonKeyAttributes")) if args.get(
                        "NonKeyAttributes") else [{
                        "NonKeyAttributeName": args.get("non_key_attributes_non_key_attribute_name",
                                                        None),

                    }],

                }

            },

        }],
        "ProvisionedThroughputOverride": {
            "ReadCapacityUnits": args.get("provisioned_throughput_override_read_capacity_units",
                                          None),
            "WriteCapacityUnits": args.get("provisioned_throughput_override_write_capacity_units",
                                           None),

        }

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.restore_table_to_point_in_time(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.TableDescription(val.TableArn && val.TableArn == obj.TableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB RestoreTableToPointInTime',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB RestoreTableToPointInTime', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB RestoreTableToPointInTime', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB RestoreTableToPointInTime', response)
    return human_readable, outputs


def scan_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "IndexName": args.get("index_name", None),
        "AttributesToGet": safe_load_json(args.get("AttributesToGet")) if args.get(
            "AttributesToGet") else [{
            "AttributeName": args.get("attributes_to_get_attribute_name", None),

        }],
        "Select": args.get("select", None),
        "ScanFilter": json.loads(args.get("scan_filter", "{}")),
        "ConditionalOperator": args.get("conditional_operator", None),
        "ExclusiveStartKey": json.loads(args.get("exclusive_start_key", "{}")),
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None),
        "ProjectionExpression": args.get("projection_expression", None),
        "FilterExpression": args.get("filter_expression", None),
        "ExpressionAttributeNames": json.loads(args.get("expression_attribute_names", "{}")),
        "ExpressionAttributeValues": json.loads(args.get("expression_attribute_values", "{}")),
        "ConsistentRead": True if args.get("consistent_read", "") == "true" else None
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.scan(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB Scan',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB Scan', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB Scan', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB Scan', response)
    return human_readable, outputs


def tag_resource_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "ResourceArn": args.get("resource_arn", None),
        "Tags": parse_tag_field(args.get("tags")),

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.tag_resource(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB TagResource',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB TagResource', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB TagResource', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB TagResource', response)
    return human_readable, outputs


def transact_get_items_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TransactItems": safe_load_json(args.get("TransactItems")) if args.get(
            "TransactItems") else [{
            "TransactGetItem": {
                "Get": {
                    "Key": json.loads(args.get("get_key", "{}")),
                    "TableName": args.get("get_table_name", None),
                    "ProjectionExpression": args.get("get_projection_expression", None),
                    "ExpressionAttributeNames": json.loads(
                        args.get("get_expression_attribute_names", "{}")),

                }

            },

        }],
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.transact_get_items(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB TransactGetItems',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB TransactGetItems', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB TransactGetItems', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB TransactGetItems', response)
    return human_readable, outputs


def transact_write_items_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TransactItems": safe_load_json(args.get("TransactItems")) if args.get(
            "TransactItems") else [{
            "TransactWriteItem": {
                "ConditionCheck": {
                    "Key": json.loads(args.get("condition_check_key", "{}")),
                    "TableName": args.get("condition_check_table_name", None),
                    "ConditionExpression": args.get("condition_check_condition_expression", None),
                    "ExpressionAttributeNames": json.loads(
                        args.get("condition_check_expression_attribute_names", "{}")),
                    "ExpressionAttributeValues": json.loads(
                        args.get("condition_check_expression_attribute_values", "{}")),
                    "ReturnValuesOnConditionCheckFailure": args.get(
                        "condition_check_return_values_on_condition_check_failure", None),

                },
                "Put": {
                    "Item": json.loads(args.get("put_item", "{}")),
                    "TableName": args.get("put_table_name", None),
                    "ConditionExpression": args.get("put_condition_expression", None),
                    "ExpressionAttributeNames": json.loads(
                        args.get("put_expression_attribute_names", "{}")),
                    "ExpressionAttributeValues": json.loads(
                        args.get("put_expression_attribute_values", "{}")),
                    "ReturnValuesOnConditionCheckFailure": args.get(
                        "put_return_values_on_condition_check_failure", None),

                },
                "Delete": {
                    "Key": json.loads(args.get("delete_key", "{}")),
                    "TableName": args.get("delete_table_name", None),
                    "ConditionExpression": args.get("delete_condition_expression", None),
                    "ExpressionAttributeNames": json.loads(
                        args.get("delete_expression_attribute_names", "{}")),
                    "ExpressionAttributeValues": json.loads(
                        args.get("delete_expression_attribute_values", "{}")),
                    "ReturnValuesOnConditionCheckFailure": args.get(
                        "delete_return_values_on_condition_check_failure", None),

                },
                "Update": {
                    "Key": json.loads(args.get("update_key", "{}")),
                    "UpdateExpression": args.get("update_update_expression", None),
                    "TableName": args.get("update_table_name", None),
                    "ConditionExpression": args.get("update_condition_expression", None),
                    "ExpressionAttributeNames": json.loads(
                        args.get("update_expression_attribute_names", "{}")),
                    "ExpressionAttributeValues": json.loads(
                        args.get("update_expression_attribute_values", "{}")),
                    "ReturnValuesOnConditionCheckFailure": args.get(
                        "update_return_values_on_condition_check_failure", None),

                }

            },

        }],
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None),
        "ReturnItemCollectionMetrics": args.get("return_item_collection_metrics", None),
        "ClientRequestToken": args.get("client_request_token", None)
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.transact_write_items(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB TransactWriteItems',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB TransactWriteItems', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB TransactWriteItems', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB TransactWriteItems', response)
    return human_readable, outputs


def untag_resource_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "ResourceArn": args.get("resource_arn", None),
        "TagKeys": safe_load_json(args.get("TagKeys")) if args.get("TagKeys") else [{
            "TagKeyString": args.get("tag_keys_tag_key_string", None),

        }],

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.untag_resource(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB UntagResource',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB UntagResource', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB UntagResource', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB UntagResource', response)
    return human_readable, outputs


def update_continuous_backups_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "PointInTimeRecoverySpecification": {
            "PointInTimeRecoveryEnabled": True if args.get(
                "point_in_time_recovery_specification_point_in_time_recovery_enabled",
                "") == "true" else None,

        }

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.update_continuous_backups(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB UpdateContinuousBackups',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB UpdateContinuousBackups', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB UpdateContinuousBackups', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB UpdateContinuousBackups', response)
    return human_readable, outputs


def update_global_table_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "GlobalTableName": args.get("global_table_name", None),
        "ReplicaUpdates": safe_load_json(args.get("ReplicaUpdates")) if args.get(
            "ReplicaUpdates") else [{
            "ReplicaUpdate": {
                "Create": {
                    "RegionName": args.get("create_region_name", None),

                },
                "Delete": {
                    "RegionName": args.get("delete_region_name", None),

                }

            },

        }],

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.update_global_table(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.GlobalTableDescription(val.GlobalTableArn && val.GlobalTableArn == '
        'obj.GlobalTableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB UpdateGlobalTable',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB UpdateGlobalTable', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB UpdateGlobalTable', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB UpdateGlobalTable', response)
    return human_readable, outputs


def update_global_table_settings_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "GlobalTableName": args.get("global_table_name", None),
        "GlobalTableBillingMode": args.get("global_table_billing_mode", None),
        "GlobalTableProvisionedWriteCapacityUnits": args.get(
            "global_table_provisioned_write_capacity_units", None),
        "GlobalTableProvisionedWriteCapacityAutoScalingSettingsUpdate": {
            "MinimumUnits": args.get(
                "global_table_provisioned_write_capacity_auto_scaling_settings_update_minimum_units",
                None),
            "MaximumUnits": args.get(
                "global_table_provisioned_write_capacity_auto_scaling_settings_update_maximum_units",
                None),
            "AutoScalingDisabled": True if args.get(
                "global_table_provisioned_write_capacity_auto_scaling_settings_update_auto_scaling_disabled",
                "") == "true" else None,
            "AutoScalingRoleArn": args.get(
                "global_table_provisioned_write_capacity_auto_scaling_settings_update_auto_scaling_role_arn",
                None),
            "ScalingPolicyUpdate": {
                "PolicyName": args.get("scaling_policy_update_policy_name", None),
                "TargetTrackingScalingPolicyConfiguration": {
                    "DisableScaleIn": True if args.get(
                        "target_tracking_scaling_policy_configuration_disable_scale_in",
                        "") == "true" else None,

                },

            },

        },
        "GlobalTableGlobalSecondaryIndexSettingsUpdate": safe_load_json(
            args.get("GlobalTableGlobalSecondaryIndexSettingsUpdate")) if args.get(
            "GlobalTableGlobalSecondaryIndexSettingsUpdate") else [{
            "GlobalTableGlobalSecondaryIndexSettingsUpdate": {
                "IndexName": args.get(
                    "global_table_global_secondary_index_settings_update_index_name", None),
                "ProvisionedWriteCapacityUnits": args.get(
                    "global_table_global_secondary_index_settings_update_provisioned_write_capacity_units",
                    None),
                "ProvisionedWriteCapacityAutoScalingSettingsUpdate": {
                    "MinimumUnits": args.get(
                        "provisioned_write_capacity_auto_scaling_settings_update_minimum_units",
                        None),
                    "MaximumUnits": args.get(
                        "provisioned_write_capacity_auto_scaling_settings_update_maximum_units",
                        None),
                    "AutoScalingDisabled": True if args.get(
                        "provisioned_write_capacity_auto_scaling_settings_update_auto_scaling_disabled",
                        "") == "true" else None,
                    "AutoScalingRoleArn": args.get(
                        "provisioned_write_capacity_auto_scaling_settings_update_auto_scaling_role_arn",
                        None),
                    "ScalingPolicyUpdate": {
                        "PolicyName": args.get("scaling_policy_update_policy_name", None),
                        "TargetTrackingScalingPolicyConfiguration": {
                            "DisableScaleIn": True if args.get(
                                "target_tracking_scaling_policy_configuration_disable_scale_in",
                                "") == "true" else None,

                        },

                    },

                }

            },

        }],
        "ReplicaSettingsUpdate": safe_load_json(args.get("ReplicaSettingsUpdate")) if args.get(
            "ReplicaSettingsUpdate") else [{
            "ReplicaSettingsUpdate": {
                "RegionName": args.get("replica_settings_update_region_name", None),
                "ReplicaProvisionedReadCapacityUnits": args.get(
                    "replica_settings_update_replica_provisioned_read_capacity_units", None),
                "ReplicaProvisionedReadCapacityAutoScalingSettingsUpdate": {
                    "MinimumUnits": args.get(
                        "replica_provisioned_read_capacity_auto_scaling_settings_update_minimum_units",
                        None),
                    "MaximumUnits": args.get(
                        "replica_provisioned_read_capacity_auto_scaling_settings_update_maximum_units",
                        None),
                    "AutoScalingDisabled": True if args.get(
                        "replica_provisioned_read_capacity_auto_scaling_settings_update_auto_scaling_disabled",
                        "") == "true" else None,
                    "AutoScalingRoleArn": args.get(
                        "replica_provisioned_read_capacity_auto_scaling_settings_update_auto_scaling_role_arn",
                        None),
                    "ScalingPolicyUpdate": {
                        "PolicyName": args.get("scaling_policy_update_policy_name", None),
                        "TargetTrackingScalingPolicyConfiguration": {
                            "DisableScaleIn": True if args.get(
                                "target_tracking_scaling_policy_configuration_disable_scale_in",
                                "") == "true" else None,

                        },

                    },

                },
                "ReplicaGlobalSecondaryIndexSettingsUpdate": safe_load_json(
                    args.get("ReplicaGlobalSecondaryIndexSettingsUpdate")) if args.get(
                    "ReplicaGlobalSecondaryIndexSettingsUpdate") else [{
                    "ReplicaGlobalSecondaryIndexSettingsUpdate": {
                        "IndexName": args.get(
                            "replica_global_secondary_index_settings_update_index_name", None),
                        "ProvisionedReadCapacityUnits": args.get(
                            "replica_global_secondary_index_settings_update_provisioned_read_capacity_units",
                            None),
                        "ProvisionedReadCapacityAutoScalingSettingsUpdate": {
                            "MinimumUnits": args.get(
                                "provisioned_read_capacity_auto_scaling_settings_update_minimum_units",
                                None),
                            "MaximumUnits": args.get(
                                "provisioned_read_capacity_auto_scaling_settings_update_maximum_units",
                                None),
                            "AutoScalingDisabled": True if args.get(
                                "provisioned_read_capacity_auto_scaling_settings_update_auto_scaling_disabled",
                                "") == "true" else None,
                            "AutoScalingRoleArn": args.get(
                                "provisioned_read_capacity_auto_scaling_settings_update_auto_scaling_role_arn",
                                None),
                            "ScalingPolicyUpdate": {
                                "PolicyName": args.get("scaling_policy_update_policy_name", None),
                                "TargetTrackingScalingPolicyConfiguration": {
                                    "DisableScaleIn": True if args.get(
                                        "target_tracking_scaling_policy_configuration_disable_scale_in",
                                        "") == "true" else None,

                                },

                            },

                        }

                    },

                }],

            },

        }],

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.update_global_table_settings(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB'
        '.ReplicaSettingsReplicaSettingsDescriptionReplicaProvisionedReadCapacityAutoScalingSettings(val.AutoScalingRoleArn && val.AutoScalingRoleArn == obj.AutoScalingRoleArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB UpdateGlobalTableSettings',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB UpdateGlobalTableSettings', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB UpdateGlobalTableSettings', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB UpdateGlobalTableSettings', response)
    return human_readable, outputs


def update_item_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "Key": json.loads(args.get("key", "{}")),
        "AttributeUpdates": json.loads(args.get("attribute_updates", "{}")),
        "Expected": json.loads(args.get("expected", "{}")),
        "ConditionalOperator": args.get("conditional_operator", None),
        "ReturnValues": args.get("return_values", None),
        "ReturnConsumedCapacity": args.get("return_consumed_capacity", None),
        "ReturnItemCollectionMetrics": args.get("return_item_collection_metrics", None),
        "UpdateExpression": args.get("update_expression", None),
        "ConditionExpression": args.get("condition_expression", None),
        "ExpressionAttributeNames": json.loads(args.get("expression_attribute_names", "{}")),
        "ExpressionAttributeValues": json.loads(args.get("expression_attribute_values", "{}"))
    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.update_item(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB UpdateItem',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB UpdateItem', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB UpdateItem', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB UpdateItem', response)
    return human_readable, outputs


def update_table_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "AttributeDefinitions": safe_load_json(args.get("AttributeDefinitions")) if args.get(
            "AttributeDefinitions") else [{
            "AttributeDefinition": {
                "AttributeName": args.get("attribute_definition_attribute_name", None),
                "AttributeType": args.get("attribute_definition_attribute_type", None)
            },

        }],
        "TableName": args.get("table_name", None),
        "BillingMode": args.get("billing_mode", None),
        "ProvisionedThroughput": {
            "ReadCapacityUnits": args.get("provisioned_throughput_read_capacity_units", None),
            "WriteCapacityUnits": args.get("provisioned_throughput_write_capacity_units", None),

        },
        "GlobalSecondaryIndexUpdates": safe_load_json(
            args.get("GlobalSecondaryIndexUpdates")) if args.get(
            "GlobalSecondaryIndexUpdates") else [{
            "GlobalSecondaryIndexUpdate": {
                "Update": {
                    "IndexName": args.get("update_index_name", None),
                    "ProvisionedThroughput": {
                        "ReadCapacityUnits": args.get("provisioned_throughput_read_capacity_units",
                                                      None),
                        "WriteCapacityUnits": args.get(
                            "provisioned_throughput_write_capacity_units", None),

                    },

                },
                "Create": {
                    "IndexName": args.get("create_index_name", None),
                    "KeySchema": safe_load_json(args.get("KeySchema")) if args.get(
                        "KeySchema") else [{
                        "KeySchemaElement": {
                            "AttributeName": args.get("key_schema_element_attribute_name", None),
                            "KeyType": args.get("key_schema_element_key_type", None)
                        },

                    }],
                    "Projection": {
                        "ProjectionType": args.get("projection_projection_type", None),
                        "NonKeyAttributes": safe_load_json(
                            args.get("NonKeyAttributes")) if args.get("NonKeyAttributes") else [{
                            "NonKeyAttributeName": args.get(
                                "non_key_attributes_non_key_attribute_name", None),

                        }],

                    },
                    "ProvisionedThroughput": {
                        "ReadCapacityUnits": args.get("provisioned_throughput_read_capacity_units",
                                                      None),
                        "WriteCapacityUnits": args.get(
                            "provisioned_throughput_write_capacity_units", None),

                    },

                },
                "Delete": {
                    "IndexName": args.get("delete_index_name", None),

                }

            },

        }],
        "StreamSpecification": {
            "StreamEnabled": True if args.get("stream_specification_stream_enabled",
                                              "") == "true" else None,
            "StreamViewType": args.get("stream_specification_stream_view_type", None),

        },
        "SSESpecification": {
            "Enabled": True if args.get("sse_specification_enabled", "") == "true" else None,
            "SSEType": args.get("sse_specification_sse_type", None),
            "KMSMasterKeyId": args.get("sse_specification_kms_master_key_id", None),

        }

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.update_table(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {
        'AWS-DynamoDB.TableDescription(val.TableArn && val.TableArn == obj.TableArn)': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB UpdateTable',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB UpdateTable', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB UpdateTable', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB UpdateTable', response)
    return human_readable, outputs


def update_time_to_live_command(args):
    client = aws_session(
        region=args.get('region'),
        roleArn=args.get('roleArn'),
        roleSessionName=args.get('roleSessionName'),
        roleSessionDuration=args.get('roleSessionDuration'),
    )
    kwargs = {
        "TableName": args.get("table_name", None),
        "TimeToLiveSpecification": {
            "Enabled": True if args.get("time_to_live_specification_enabled",
                                        "") == "true" else None,
            "AttributeName": args.get("time_to_live_specification_attribute_name", None),

        }

    }
    kwargs = remove_empty_elements(kwargs)
    if args.get('raw_json') is not None:
        del kwargs
        kwargs = safe_load_json(args.get('raw_json'))
    response = client.update_time_to_live(**kwargs)
    response = json.dumps(response, default=myconverter)
    response = json.loads(response)
    outputs = {'AWS-DynamoDB': response}
    del response['ResponseMetadata']
    if isinstance(response, dict):
        if len(response) == 1:
            if isinstance(list(response.keys())[0], dict):
                human_readable = tableToMarkdown('AWS DynamoDB UpdateTimeToLive',
                                                 response[list(response.keys())[0]])
            else:
                human_readable = tableToMarkdown('AWS DynamoDB UpdateTimeToLive', response)
        else:
            human_readable = tableToMarkdown('AWS DynamoDB UpdateTimeToLive', response)
    else:
        human_readable = tableToMarkdown('AWS DynamoDB UpdateTimeToLive', response)
    return human_readable, outputs


''' COMMANDS MANAGER / SWITCH PANEL '''


def main():  # pragma: no cover
    args = demisto.args()
    human_readable = None
    outputs = None
    try:
        LOG('Command being called is {command}'.format(command=demisto.command()))
        if demisto.command() == 'test-module':
            # This is the call made when pressing the integration test button.
            client = aws_session()
            response = client.REPLACE_WITH_TEST_FUNCTION()
            if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                demisto.results('ok')

        elif demisto.command() == 'aws-dynamodb-batch-get-item':
            human_readable, outputs = batch_get_item_command(args)
        elif demisto.command() == 'aws-dynamodb-batch-write-item':
            human_readable, outputs = batch_write_item_command(args)
        elif demisto.command() == 'aws-dynamodb-create-backup':
            human_readable, outputs = create_backup_command(args)
        elif demisto.command() == 'aws-dynamodb-create-global-table':
            human_readable, outputs = create_global_table_command(args)
        elif demisto.command() == 'aws-dynamodb-create-table':
            human_readable, outputs = create_table_command(args)
        elif demisto.command() == 'aws-dynamodb-delete-backup':
            human_readable, outputs = delete_backup_command(args)
        elif demisto.command() == 'aws-dynamodb-delete-item':
            human_readable, outputs = delete_item_command(args)
        elif demisto.command() == 'aws-dynamodb-delete-table':
            human_readable, outputs = delete_table_command(args)
        elif demisto.command() == 'aws-dynamodb-describe-backup':
            human_readable, outputs = describe_backup_command(args)
        elif demisto.command() == 'aws-dynamodb-describe-continuous-backups':
            human_readable, outputs = describe_continuous_backups_command(args)
        elif demisto.command() == 'aws-dynamodb-describe-endpoints':
            human_readable, outputs = describe_endpoints_command(args)
        elif demisto.command() == 'aws-dynamodb-describe-global-table':
            human_readable, outputs = describe_global_table_command(args)
        elif demisto.command() == 'aws-dynamodb-describe-global-table-settings':
            human_readable, outputs = describe_global_table_settings_command(args)
        elif demisto.command() == 'aws-dynamodb-describe-limits':
            human_readable, outputs = describe_limits_command(args)
        elif demisto.command() == 'aws-dynamodb-describe-table':
            human_readable, outputs = describe_table_command(args)
        elif demisto.command() == 'aws-dynamodb-describe-time-to-live':
            human_readable, outputs = describe_time_to_live_command(args)
        elif demisto.command() == 'aws-dynamodb-get-item':
            human_readable, outputs = get_item_command(args)
        elif demisto.command() == 'aws-dynamodb-list-backups':
            human_readable, outputs = list_backups_command(args)
        elif demisto.command() == 'aws-dynamodb-list-global-tables':
            human_readable, outputs = list_global_tables_command(args)
        elif demisto.command() == 'aws-dynamodb-list-tables':
            human_readable, outputs = list_tables_command(args)
        elif demisto.command() == 'aws-dynamodb-list-tags-of-resource':
            human_readable, outputs = list_tags_of_resource_command(args)
        elif demisto.command() == 'aws-dynamodb-put-item':
            human_readable, outputs = put_item_command(args)
        elif demisto.command() == 'aws-dynamodb-query':
            human_readable, outputs = query_command(args)
        elif demisto.command() == 'aws-dynamodb-restore-table-from-backup':
            human_readable, outputs = restore_table_from_backup_command(args)
        elif demisto.command() == 'aws-dynamodb-restore-table-to-point-in-time':
            human_readable, outputs = restore_table_to_point_in_time_command(args)
        elif demisto.command() == 'aws-dynamodb-scan':
            human_readable, outputs = scan_command(args)
        elif demisto.command() == 'aws-dynamodb-tag-resource':
            human_readable, outputs = tag_resource_command(args)
        elif demisto.command() == 'aws-dynamodb-transact-get-items':
            human_readable, outputs = transact_get_items_command(args)
        elif demisto.command() == 'aws-dynamodb-transact-write-items':
            human_readable, outputs = transact_write_items_command(args)
        elif demisto.command() == 'aws-dynamodb-untag-resource':
            human_readable, outputs = untag_resource_command(args)
        elif demisto.command() == 'aws-dynamodb-update-continuous-backups':
            human_readable, outputs = update_continuous_backups_command(args)
        elif demisto.command() == 'aws-dynamodb-update-global-table':
            human_readable, outputs = update_global_table_command(args)
        elif demisto.command() == 'aws-dynamodb-update-global-table-settings':
            human_readable, outputs = update_global_table_settings_command(args)
        elif demisto.command() == 'aws-dynamodb-update-item':
            human_readable, outputs = update_item_command(args)
        elif demisto.command() == 'aws-dynamodb-update-table':
            human_readable, outputs = update_table_command(args)
        elif demisto.command() == 'aws-dynamodb-update-time-to-live':
            human_readable, outputs = update_time_to_live_command(args)
        return_outputs(human_readable, outputs)

    except ResponseParserError as e:
        return_error(
            'Could not connect to the AWS endpoint. Please check that the region is valid. {error}'.format(
                error=type(e)))
        LOG(e)
    except Exception as e:
        LOG(e)
        return_error('Error has occurred in the AWS dynamodb Integration: {code} {message}'.format(
            code=type(e), message=e))


if __name__ in ["__builtin__", "builtins", '__main__']:  # pragma: no cover
    main()