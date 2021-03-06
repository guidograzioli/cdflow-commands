import unittest
import datetime
from contextlib import ExitStack
from copy import deepcopy
from io import BufferedRandom
from os.path import join
from re import match
from string import ascii_lowercase, digits
from textwrap import dedent

import boto3
from boto3.session import Session
from botocore.exceptions import ClientError
from cdflow_commands.account import AccountScheme
from cdflow_commands.state import (
    TFSTATE_TAG_NAME, TAG_VALUE, IncorrectSchemaError, LockTableFactory,
    S3BucketFactory, terraform_state, remove_file, migrate_state,
)
from hypothesis import given
from hypothesis.strategies import fixed_dictionaries, text
from mock import MagicMock, Mock, patch, ANY
from moto import mock_s3, mock_sts
from freezegun import freeze_time


NEW_BUCKET_PATTERN = r'^cdflow-tfstate-[a-z0-9]+$'


class TestS3BucketFactory(unittest.TestCase):

    @given(text())
    def test_get_existing_bucket(self, bucket_name):
        # Given
        session = Mock()
        session.region_name = 'dummy-region'
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': [
                {'Name': bucket_name}
            ]
        }
        s3_client.get_bucket_tagging.return_value = {
            'TagSet': [
                {
                    'Key': TFSTATE_TAG_NAME,
                    'Value': TAG_VALUE,
                }
            ]
        }
        s3_client.get_bucket_location.return_value = {
            'LocationConstraint': session.region_name
        }

        s3_bucket_factory = S3BucketFactory(session)

        # When
        retrieved_bucket_name = s3_bucket_factory.get_bucket_name()

        # Then
        session.client.called_once_with('s3')
        s3_client.list_buckets.assert_called_once_with()
        s3_client.get_bucket_tagging.assert_called_once_with(
            Bucket=bucket_name
        )
        s3_client.get_bucket_location.assert_called_once_with(
            Bucket=bucket_name
        )
        assert retrieved_bucket_name == bucket_name

    def test_assertion_error_on_multiple_buckets(self):

        # Given
        session = Mock()
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': [
                {'Name': 'state-bucket'},
                {'Name': 'another-state-bucket'}
            ]
        }

        s3_client.get_bucket_tagging.return_value = {
            'TagSet': [
                {
                    'Key': TFSTATE_TAG_NAME,
                    'Value': TAG_VALUE,
                }
            ]
        }

        s3_client.get_bucket_location.return_value = {
            'LocationConstraint': session.region_name
        }

        s3_bucket_factory = S3BucketFactory(session)

        # When & Then
        self.assertRaises(AssertionError, s3_bucket_factory.get_bucket_name)

    def test_handle_untagged_buckets(self):
        # Given
        session = Mock()
        session.region_name = 'dummy-region-name'
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': [
                {'Name': 'another-bucket'},
                {'Name': 'state-bucket'}
            ]
        }

        def get_bucket_tagging(Bucket):
            if Bucket == 'state-bucket':
                return {
                    'TagSet': [
                        {
                            'Key': TFSTATE_TAG_NAME,
                            'Value': TAG_VALUE,
                        }
                    ]
                }
            else:
                raise ClientError({
                    'Error': {
                        'Code': 'NoSuchTagSet',
                        'Message': 'The TagSet does not exist'
                    }
                }, 'GetBucketTagging')
        s3_client.get_bucket_tagging = get_bucket_tagging

        s3_client.get_bucket_location.return_value = {
            'LocationConstraint': session.region_name
        }

        s3_bucket_factory = S3BucketFactory(session)

        # When
        bucket = s3_bucket_factory.get_bucket_name()

        # Then
        assert bucket == 'state-bucket'

    def test_handle_missing_buckets(self):
        # Given
        session = Mock()
        session.region_name = 'dummy-region-name'
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': [
                {'Name': 'another-bucket'},
                {'Name': 'state-bucket'}
            ]
        }

        def get_bucket_tagging(Bucket):
            if Bucket == 'state-bucket':
                return {
                    'TagSet': [
                        {
                            'Key': TFSTATE_TAG_NAME,
                            'Value': TAG_VALUE,
                        }
                    ]
                }
            else:
                raise ClientError({
                    'Error': {
                        'Code': 'NoSuchBucket',
                        'Message': 'The bucket does not exist'
                    }
                }, 'GetBucketTagging')
        s3_client.get_bucket_tagging = get_bucket_tagging

        s3_client.get_bucket_location.return_value = {
            'LocationConstraint': session.region_name
        }

        s3_bucket_factory = S3BucketFactory(session)

        # When
        bucket = s3_bucket_factory.get_bucket_name()

        # Then
        assert bucket == 'state-bucket'

    def test_bucket_created_and_tagged_in_us_standard_region(self):

        # Given
        session = Mock()
        session.region_name = 'us-east-1'
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': [
            ]
        }

        s3_bucket_factory = S3BucketFactory(session)
        # When
        bucket_name = s3_bucket_factory.get_bucket_name()

        # Then
        s3_client.create_bucket.assert_called_once_with(
            Bucket=bucket_name
        )

        s3_client.put_bucket_tagging.assert_called_once_with(
            Bucket=bucket_name,
            Tagging={
                'TagSet': [
                    {
                        'Key': TFSTATE_TAG_NAME,
                        'Value': TAG_VALUE,
                    }
                ]
            }
        )

    def test_bucket_created_and_tagged(self):

        # Given
        session = Mock()
        session.region_name = 'dummy-region-name'
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': [
            ]
        }

        s3_bucket_factory = S3BucketFactory(session)
        # When
        bucket_name = s3_bucket_factory.get_bucket_name()

        # Then
        s3_client.create_bucket.assert_called_once_with(
            Bucket=bucket_name,
            CreateBucketConfiguration={
                'LocationConstraint': 'dummy-region-name'
            }
        )

        s3_client.put_bucket_tagging.assert_called_once_with(
            Bucket=bucket_name,
            Tagging={
                'TagSet': [
                    {
                        'Key': TFSTATE_TAG_NAME,
                        'Value': TAG_VALUE,
                    }
                ]
            }
        )

    def test_existing_bucket_name_returned_when_in_us_standard_region(self):

        # Given
        session = Mock()
        session.region_name = 'us-east-1'
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': [
                {'Name': 'dummy-bucket-name'}
            ]
        }
        s3_client.get_bucket_tagging.return_value = {
            'TagSet': [
                {
                    'Key': TFSTATE_TAG_NAME,
                    'Value': TAG_VALUE,
                }
            ]
        }
        s3_client.get_bucket_location.return_value = {
            'LocationConstraint': None
        }

        s3_bucket_factory = S3BucketFactory(session)
        # When
        bucket_name = s3_bucket_factory.get_bucket_name()

        # Then
        assert bucket_name == 'dummy-bucket-name'

    def test_bucket_created_and_tagged_when_one_exists_in_another_region(self):

        # Given
        session = Mock()
        session.region_name = 'dummy-region-name'
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': [
                {'Name': 'dummy-bucket-name'}
            ]
        }
        s3_client.get_bucket_tagging.return_value = {
            'TagSet': [
                {
                    'Key': TFSTATE_TAG_NAME,
                    'Value': TAG_VALUE,
                }
            ]
        }
        s3_client.get_bucket_location.return_value = {
            'LocationConstraint': 'other-region'
        }

        s3_bucket_factory = S3BucketFactory(session)
        # When
        bucket_name = s3_bucket_factory.get_bucket_name()

        # Then
        s3_client.create_bucket.assert_called_once_with(
            Bucket=bucket_name,
            CreateBucketConfiguration={
                'LocationConstraint': 'dummy-region-name'
            }
        )

        s3_client.put_bucket_tagging.assert_called_once_with(
            Bucket=bucket_name,
            Tagging={
                'TagSet': [
                    {
                        'Key': TFSTATE_TAG_NAME,
                        'Value': TAG_VALUE,
                    }
                ]
            }
        )

    def test_bucket_name_generally_unique_based_on_region(self):

        # Given
        session = Mock()
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': []
        }

        # When
        session.region_name = 'region-1'
        bucket = S3BucketFactory(session).get_bucket_name()
        duplicate_bucket = S3BucketFactory(session).get_bucket_name()
        session.region_name = 'region-2'
        bucket_different_region = S3BucketFactory(session).get_bucket_name()

        # Then
        assert match(NEW_BUCKET_PATTERN, bucket)
        assert match(NEW_BUCKET_PATTERN, duplicate_bucket)
        assert match(NEW_BUCKET_PATTERN, bucket_different_region)
        assert bucket == duplicate_bucket
        assert bucket != bucket_different_region

    def test_bucket_name_when_bucket_not_available(self):
        # Given
        session = Mock()
        session.region_name = 'dummy-region'
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': []
        }
        s3_client.create_bucket.side_effect = [
            ClientError({
                'Error': {
                    'Code': 'BucketAlreadyExists',
                    'Message': 'The requested bucket name is not available'
                }
            }, 'CreateBucket'),
            {}
        ]

        s3_bucket_factory = S3BucketFactory(session)

        # When
        bucket_name = s3_bucket_factory.get_bucket_name()

        # Then
        first_call, second_call = s3_client.create_bucket.mock_calls
        first_bucket_param = first_call[2]['Bucket']
        second_bucket_param = second_call[2]['Bucket']
        assert match(NEW_BUCKET_PATTERN, first_bucket_param)
        assert match(NEW_BUCKET_PATTERN, second_bucket_param)
        assert first_bucket_param != bucket_name
        assert second_bucket_param == bucket_name

    def test_bucket_name_when_bucket_owned_in_other_region(self):
        # Given
        session = Mock()
        session.region_name = 'dummy-region'
        s3_client = Mock()
        session.client.return_value = s3_client

        s3_client.list_buckets.return_value = {
            'Buckets': []
        }
        s3_client.create_bucket.side_effect = [
            ClientError({
                'Error': {
                    'Code': 'BucketAlreadyOwnedByYou',
                    'Message': 'Your previous request to create the named ' +
                               'bucket succeeded and you already own it.'
                }
            }, 'CreateBucket'),
            {}
        ]

        s3_bucket_factory = S3BucketFactory(session)

        # When
        bucket_name = s3_bucket_factory.get_bucket_name()

        # Then
        first_call, second_call = s3_client.create_bucket.mock_calls
        first_bucket_param = first_call[2]['Bucket']
        second_bucket_param = second_call[2]['Bucket']
        assert match(NEW_BUCKET_PATTERN, first_bucket_param)
        assert match(NEW_BUCKET_PATTERN, second_bucket_param)
        assert first_bucket_param != bucket_name
        assert second_bucket_param == bucket_name


class TestLockTableFactory(unittest.TestCase):

    def test_existing_table(self):
        boto_session = MagicMock(spec=Session)
        mock_dynamodb_client = Mock()
        mock_dynamodb_client.describe_table.return_value = {
            'Table': {
                'AttributeDefinitions': [
                    {'AttributeName': 'LockID', 'AttributeType': 'S'}
                ],
                'TableName': 'terraform_locks',
                'TableArn': (
                    'arn:aws:dynamodb:eu-west-12:123456789:'
                    'table/terraform_locks'
                ),
            }
        }
        mock_dynamodb_client.list_tags_of_resource.return_value = {
            'Tags': [
                {'Key': 'cdflow_terraform_locks', 'Value': 'true'}
            ]
        }
        boto_session.client.return_value = mock_dynamodb_client
        table_factory = LockTableFactory(boto_session)

        table_name = table_factory.get_table_name()

        assert table_name == 'terraform_locks'

    def test_table_must_have_correct_schema(self):
        boto_session = MagicMock(spec=Session)
        mock_dynamodb_client = Mock()
        mock_dynamodb_client.describe_table.return_value = {
            'Table': {
                'AttributeDefinitions': [
                    {'AttributeName': 'IncorrectColumn', 'AttributeType': 'S'}
                ],
                'TableName': 'terraform_locks',
                'TableArn': (
                    'arn:aws:dynamodb:eu-west-12:123456789:'
                    'table/terraform_locks'
                ),
            }
        }
        mock_dynamodb_client.list_tags_of_resource.return_value = {
            'Tags': [
                {'Key': 'cdflow_terraform_locks', 'Value': 'true'}
            ]
        }
        boto_session.client.return_value = mock_dynamodb_client
        table_factory = LockTableFactory(boto_session)

        self.assertRaises(IncorrectSchemaError, table_factory.get_table_name)

    def test_creates_table_when_missing(self):
        boto_session = MagicMock(spec=Session)
        mock_dynamodb_client = Mock()
        mock_dynamodb_client.describe_table.side_effect = ClientError(
            {
                'Error': {
                    'Message': 'Requested resource not found:',
                    'Code': 'ResourceNotFoundException'
                }
            },
            None
        )
        mock_dynamodb_client.create_table.return_value = {
            'TableDescription': {'TableArn': ''}
        }
        boto_session.client.return_value = mock_dynamodb_client

        table_factory = LockTableFactory(boto_session)

        table_name = table_factory.get_table_name()

        assert table_name == 'terraform_locks'

        mock_dynamodb_client.create_table.assert_called_once_with(
            AttributeDefinitions=[
                {'AttributeName': 'LockID', 'AttributeType': 'S'}
            ],
            TableName='terraform_locks',
            KeySchema=[{'AttributeName': 'LockID', 'KeyType': 'HASH'}],
            ProvisionedThroughput={
                'ReadCapacityUnits': 1,
                'WriteCapacityUnits': 1
            }
        )

    def test_waits_for_newly_created_table(self):
        boto_session = MagicMock(spec=Session)
        mock_dynamodb_client = Mock()
        mock_dynamodb_client.describe_table.side_effect = ClientError(
            {
                'Error': {
                    'Message': 'Requested resource not found:',
                    'Code': 'ResourceNotFoundException'
                }
            },
            None
        )
        mock_dynamodb_client.create_table.return_value = {
            'TableDescription': {'TableArn': ''}
        }
        boto_session.client.return_value = mock_dynamodb_client

        mock_waiter = Mock()
        mock_dynamodb_client.get_waiter.return_value = mock_waiter

        table_factory = LockTableFactory(boto_session)

        table_factory.get_table_name()

        mock_dynamodb_client.get_waiter.assert_called_once_with('table_exists')

        mock_waiter.wait.assert_called_once_with(TableName='terraform_locks')

    def test_other_client_errors_are_reraised(self):
        boto_session = MagicMock(spec=Session)
        mock_dynamodb_client = Mock()
        mock_dynamodb_client.describe_table.side_effect = ClientError(
            {
                'Error': {
                    'Message': 'You made a mistake',
                    'Code': 'TerribleError'
                }
            },
            None
        )

        boto_session.client.return_value = mock_dynamodb_client

        table_factory = LockTableFactory(boto_session)

        self.assertRaises(ClientError, table_factory.get_table_name)


SIMPLE_ALPHABET = ascii_lowercase + digits + '-'

terraform_backend_input = fixed_dictionaries({
    'base_directory': text(min_size=1).filter(
        lambda t: '/' not in t and '.' not in t
    ),
    'sub_directory': text(min_size=1).filter(
        lambda t: '/' not in t and '.' not in t
    ),
    'aws_region': text(min_size=1),
    'bucket_name': text(
        alphabet=SIMPLE_ALPHABET+'_.', min_size=3, max_size=63
    ),
    'lock_table_name': text(
        alphabet=SIMPLE_ALPHABET, min_size=3, max_size=63
    ),
    'environment_name': text(alphabet=SIMPLE_ALPHABET, min_size=1),
    'component_name': text(alphabet=SIMPLE_ALPHABET, min_size=1),
    'tfstate_filename': text(alphabet=SIMPLE_ALPHABET, min_size=1),
    'team_name': text(alphabet=SIMPLE_ALPHABET, min_size=1),
})


class TestTerraformBackendConfigClassic(unittest.TestCase):

    @given(terraform_backend_input)
    def test_backend_config_written_into_infra_code(
        self, terraform_backend_input
    ):
        base_directory = terraform_backend_input['base_directory']
        sub_directory = terraform_backend_input['sub_directory']
        bucket_name = terraform_backend_input['bucket_name']
        lock_table_name = terraform_backend_input['lock_table_name']
        environment_name = terraform_backend_input['environment_name']
        component_name = terraform_backend_input['component_name']
        tfstate_filename = terraform_backend_input['tfstate_filename']
        team_name = terraform_backend_input['team_name']
        boto_session = MagicMock(spec=Session)
        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.classic_metadata_handling = True

        with ExitStack() as stack:
            stack.enter_context(patch('cdflow_commands.state.check_call'))
            stack.enter_context(patch('cdflow_commands.state.atexit'))
            NamedTemporaryFile = stack.enter_context(
                patch('cdflow_commands.state.NamedTemporaryFile')
            )

            mock_file = MagicMock(spec=BufferedRandom)
            NamedTemporaryFile.return_value.__enter__.return_value = mock_file
            LockTableFactory = stack.enter_context(
                patch('cdflow_commands.state.LockTableFactory')
            )
            LockTableFactory.return_value.get_table_name.return_value = \
                lock_table_name
            S3BucketFactory = stack.enter_context(
                patch('cdflow_commands.state.S3BucketFactory')
            )
            S3BucketFactory.return_value.get_bucket_name.return_value = \
                bucket_name

            state = terraform_state(
                base_directory, sub_directory, boto_session,
                environment_name, component_name, tfstate_filename,
                account_scheme, team_name,
            )
            state.init()

        NamedTemporaryFile.assert_called_once_with(
            prefix='cdflow_backend_', suffix='.tf',
            dir=join(base_directory, sub_directory), delete=False, mode='w+'
        )

        mock_file.write.assert_called_once_with(dedent('''
            terraform {
                backend "s3" {
                }
            }
        ''').strip())

    @given(terraform_backend_input)
    def test_backend_is_initialised(self, terraform_backend_input):
        base_directory = terraform_backend_input['base_directory']
        sub_directory = terraform_backend_input['sub_directory']
        bucket_name = terraform_backend_input['bucket_name']
        lock_table_name = terraform_backend_input['lock_table_name']
        environment_name = terraform_backend_input['environment_name']
        component_name = terraform_backend_input['component_name']
        tfstate_filename = terraform_backend_input['tfstate_filename']
        team_name = terraform_backend_input['team_name']
        boto_session = MagicMock(spec=Session)
        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.classic_metadata_handling = True

        state_file_key = (
            f'{environment_name}/{component_name}/{tfstate_filename}'
        )

        with ExitStack() as stack:
            stack.enter_context(
                patch('cdflow_commands.state.NamedTemporaryFile')
            )
            stack.enter_context(patch('cdflow_commands.state.atexit'))
            check_call = stack.enter_context(
                patch('cdflow_commands.state.check_call')
            )
            LockTableFactory = stack.enter_context(
                patch('cdflow_commands.state.LockTableFactory')
            )
            LockTableFactory.return_value.get_table_name.return_value = \
                lock_table_name
            S3BucketFactory = stack.enter_context(
                patch('cdflow_commands.state.S3BucketFactory')
            )
            S3BucketFactory.return_value.get_bucket_name.return_value = \
                bucket_name

            state = terraform_state(
                base_directory, sub_directory, boto_session,
                environment_name, component_name, tfstate_filename,
                account_scheme, team_name,
            )
            state.init()

        check_call.assert_called_once_with(
            [
                'terraform', 'init',
                '-get=false',
                '-get-plugins=false',
                f'-backend-config=bucket={bucket_name}',
                f'-backend-config=region={boto_session.region_name}',
                f'-backend-config=key={state_file_key}',
                f'-backend-config=dynamodb_table={lock_table_name}',
                ANY,
                ANY,
                ANY,
                join(base_directory, sub_directory),
            ],
            cwd=base_directory,
        )

    @given(terraform_backend_input)
    def test_modules_and_plugins_can_be_fetched(self, terraform_backend_input):
        base_directory = terraform_backend_input['base_directory']
        sub_directory = terraform_backend_input['sub_directory']
        bucket_name = terraform_backend_input['bucket_name']
        lock_table_name = terraform_backend_input['lock_table_name']
        environment_name = terraform_backend_input['environment_name']
        component_name = terraform_backend_input['component_name']
        tfstate_filename = terraform_backend_input['tfstate_filename']
        team_name = terraform_backend_input['team_name']
        boto_session = MagicMock(spec=Session)
        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.classic_metadata_handling = True

        state_file_key = (
            f'{environment_name}/{component_name}/{tfstate_filename}'
        )

        with ExitStack() as stack:
            stack.enter_context(
                patch('cdflow_commands.state.NamedTemporaryFile')
            )
            stack.enter_context(patch('cdflow_commands.state.atexit'))
            check_call = stack.enter_context(
                patch('cdflow_commands.state.check_call')
            )
            LockTableFactory = stack.enter_context(
                patch('cdflow_commands.state.LockTableFactory')
            )
            LockTableFactory.return_value.get_table_name.return_value = \
                lock_table_name
            S3BucketFactory = stack.enter_context(
                patch('cdflow_commands.state.S3BucketFactory')
            )
            S3BucketFactory.return_value.get_bucket_name.return_value = \
                bucket_name

            state = terraform_state(
                base_directory, sub_directory, boto_session,
                environment_name, component_name, tfstate_filename,
                account_scheme, team_name,
            )
            state.init(get_terraform_modules=True)

        check_call.assert_called_once_with(
            [
                'terraform', 'init',
                '-get=true',
                '-get-plugins=true',
                f'-backend-config=bucket={bucket_name}',
                f'-backend-config=region={boto_session.region_name}',
                f'-backend-config=key={state_file_key}',
                f'-backend-config=dynamodb_table={lock_table_name}',
                ANY,
                ANY,
                ANY,
                join(base_directory, sub_directory),
            ],
            cwd=base_directory,
        )

    @given(fixed_dictionaries({
        'terraform_backend_input': terraform_backend_input,
        'temp_file_name': text(
            min_size=3, max_size=10, alphabet=ascii_lowercase+digits
        )
    }))
    def test_config_file_is_removed_at_exit(self, test_fixtures):
        terraform_backend_input = test_fixtures['terraform_backend_input']
        base_directory = terraform_backend_input['base_directory']
        sub_directory = terraform_backend_input['sub_directory']
        bucket_name = test_fixtures['terraform_backend_input']['bucket_name']
        boto_session = MagicMock(spec=Session)
        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.classic_metadata_handling = True

        lock_table_name = (
            test_fixtures['terraform_backend_input']['lock_table_name']
        )
        environment_name = (
            test_fixtures['terraform_backend_input']['environment_name']
        )
        component_name = (
            test_fixtures['terraform_backend_input']['component_name']
        )
        tfstate_filename = (
            test_fixtures['terraform_backend_input']['tfstate_filename']
        )

        backend_config_file_name = (
            f'cdflow_backend_{test_fixtures["temp_file_name"]}.tf'
        )

        with ExitStack() as stack:
            stack.enter_context(patch('cdflow_commands.state.check_call'))
            NamedTemporaryFile = stack.enter_context(
                patch('cdflow_commands.state.NamedTemporaryFile')
            )
            atexit = stack.enter_context(patch('cdflow_commands.state.atexit'))

            NamedTemporaryFile.return_value.__enter__.return_value.name = \
                backend_config_file_name
            LockTableFactory = stack.enter_context(
                patch('cdflow_commands.state.LockTableFactory')
            )
            LockTableFactory.return_value.get_table_name.return_value = \
                lock_table_name
            S3BucketFactory = stack.enter_context(
                patch('cdflow_commands.state.S3BucketFactory')
            )
            S3BucketFactory.return_value.get_bucket_name.return_value = \
                bucket_name

            state = terraform_state(
                base_directory, sub_directory, boto_session,
                environment_name, component_name, tfstate_filename,
                account_scheme, 'team-name',
            )
            state.init()

        atexit.register.assert_called_once_with(
            remove_file, backend_config_file_name
        )

    @given(text())
    def test_remove_file_function(self, filepath):
        with patch('cdflow_commands.state.unlink') as unlink:
            remove_file(filepath)

        unlink.assert_called_once_with(filepath)

    @given(text())
    def test_remove_file_function_handles_missing_file(self, filepath):
        with patch('cdflow_commands.state.unlink') as unlink:
            unlink.side_effect = OSError('File not found')

            try:
                remove_file(filepath)
            except OSError as e:
                self.fail(f'An error was thrown: {e}')

        unlink.assert_called_once_with(filepath)


class TestTerraformBackendConfig(unittest.TestCase):

    @given(terraform_backend_input)
    def test_backend_config_written_into_infra_code(
        self, terraform_backend_input
    ):
        base_directory = terraform_backend_input['base_directory']
        sub_directory = terraform_backend_input['sub_directory']
        bucket_name = terraform_backend_input['bucket_name']
        lock_table_name = terraform_backend_input['lock_table_name']
        environment_name = terraform_backend_input['environment_name']
        component_name = terraform_backend_input['component_name']
        tfstate_filename = terraform_backend_input['tfstate_filename']
        team_name = terraform_backend_input['team_name']
        boto_session = MagicMock(spec=Session)
        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.classic_metadata_handling = False
        account_scheme.backend_s3_bucket = bucket_name
        account_scheme.backend_s3_dynamodb_table = lock_table_name

        with ExitStack() as stack:
            stack.enter_context(patch('cdflow_commands.state.check_call'))
            stack.enter_context(patch('cdflow_commands.state.atexit'))
            NamedTemporaryFile = stack.enter_context(
                patch('cdflow_commands.state.NamedTemporaryFile')
            )

            mock_file = MagicMock(spec=BufferedRandom)
            NamedTemporaryFile.return_value.__enter__.return_value = mock_file
            check_output = stack.enter_context(
                patch('cdflow_commands.state.check_output')
            )
            check_output.return_value = '* default'.encode('utf-8')

            state = terraform_state(
                base_directory, sub_directory, boto_session,
                environment_name, component_name, tfstate_filename,
                account_scheme, team_name,
            )
            state.init()

        NamedTemporaryFile.assert_called_once_with(
            prefix='cdflow_backend_', suffix='.tf',
            dir=join(base_directory, sub_directory), delete=False, mode='w+'
        )

        mock_file.write.assert_called_once_with(dedent('''
            terraform {
                backend "s3" {
                }
            }
        ''').strip())

    @given(terraform_backend_input)
    def test_backend_is_initialised(self, terraform_backend_input):
        base_directory = terraform_backend_input['base_directory']
        sub_directory = terraform_backend_input['sub_directory']
        bucket_name = terraform_backend_input['bucket_name']
        lock_table_name = terraform_backend_input['lock_table_name']
        environment_name = terraform_backend_input['environment_name']
        component_name = terraform_backend_input['component_name']
        tfstate_filename = terraform_backend_input['tfstate_filename']
        team_name = terraform_backend_input['team_name']
        boto_session = MagicMock(spec=Session)
        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.classic_metadata_handling = False
        account_scheme.backend_s3_bucket = bucket_name
        account_scheme.backend_s3_dynamodb_table = lock_table_name

        with ExitStack() as stack:
            stack.enter_context(
                patch('cdflow_commands.state.NamedTemporaryFile')
            )
            stack.enter_context(patch('cdflow_commands.state.atexit'))
            check_call = stack.enter_context(
                patch('cdflow_commands.state.check_call')
            )
            check_output = stack.enter_context(
                patch('cdflow_commands.state.check_output')
            )
            check_output.return_value = '* default'.encode('utf-8')

            state = terraform_state(
                base_directory, sub_directory, boto_session,
                environment_name, component_name, tfstate_filename,
                account_scheme, team_name,
            )
            state.init()

        check_call.assert_any_call(
            [
                'terraform', 'init',
                '-get=false',
                '-get-plugins=false',
                f'-backend-config=bucket={bucket_name}',
                f'-backend-config=region={boto_session.region_name}',
                f'-backend-config=key={tfstate_filename}',
                (
                    '-backend-config=workspace_key_prefix'
                    f'={team_name}/{component_name}'
                ),
                f'-backend-config=dynamodb_table={lock_table_name}',
                ANY,
                ANY,
                ANY,
                join(base_directory, sub_directory),
            ],
            cwd=base_directory,
        )

    @given(terraform_backend_input)
    def test_modules_and_plugins_can_be_fetched(self, terraform_backend_input):
        base_directory = terraform_backend_input['base_directory']
        sub_directory = terraform_backend_input['sub_directory']
        bucket_name = terraform_backend_input['bucket_name']
        lock_table_name = terraform_backend_input['lock_table_name']
        environment_name = terraform_backend_input['environment_name']
        component_name = terraform_backend_input['component_name']
        tfstate_filename = terraform_backend_input['tfstate_filename']
        team_name = terraform_backend_input['team_name']
        boto_session = MagicMock(spec=Session)
        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.classic_metadata_handling = False
        account_scheme.backend_s3_bucket = bucket_name
        account_scheme.backend_s3_dynamodb_table = lock_table_name

        with ExitStack() as stack:
            stack.enter_context(
                patch('cdflow_commands.state.NamedTemporaryFile')
            )
            stack.enter_context(patch('cdflow_commands.state.atexit'))
            check_call = stack.enter_context(
                patch('cdflow_commands.state.check_call')
            )
            check_output = stack.enter_context(
                patch('cdflow_commands.state.check_output')
            )
            check_output.return_value = '* default'.encode('utf-8')

            state = terraform_state(
                base_directory, sub_directory, boto_session,
                environment_name, component_name, tfstate_filename,
                account_scheme, team_name,
            )
            state.init(get_terraform_modules=True)

        check_call.assert_any_call(
            [
                'terraform', 'init',
                '-get=true',
                '-get-plugins=true',
                f'-backend-config=bucket={bucket_name}',
                f'-backend-config=region={boto_session.region_name}',
                f'-backend-config=key={tfstate_filename}',
                (
                    '-backend-config=workspace_key_prefix'
                    f'={team_name}/{component_name}'
                ),
                f'-backend-config=dynamodb_table={lock_table_name}',
                ANY,
                ANY,
                ANY,
                join(base_directory, sub_directory),
            ],
            cwd=base_directory,
        )

    @given(terraform_backend_input)
    def test_environment_is_used_for_workspace(self, terraform_backend_input):
        base_directory = terraform_backend_input['base_directory']
        sub_directory = terraform_backend_input['sub_directory']
        bucket_name = terraform_backend_input['bucket_name']
        lock_table_name = terraform_backend_input['lock_table_name']
        environment_name = terraform_backend_input['environment_name']
        component_name = terraform_backend_input['component_name']
        tfstate_filename = terraform_backend_input['tfstate_filename']
        team_name = terraform_backend_input['team_name']
        boto_session = MagicMock(spec=Session)
        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.classic_metadata_handling = False
        account_scheme.backend_s3_bucket = bucket_name
        account_scheme.backend_s3_dynamodb_table = lock_table_name

        with ExitStack() as stack:
            stack.enter_context(
                patch('cdflow_commands.state.NamedTemporaryFile')
            )
            stack.enter_context(patch('cdflow_commands.state.atexit'))
            check_call = stack.enter_context(
                patch('cdflow_commands.state.check_call')
            )
            check_output = stack.enter_context(
                patch('cdflow_commands.state.check_output')
            )
            check_output.return_value = '* default'.encode('utf-8')

            state = terraform_state(
                base_directory, sub_directory, boto_session,
                environment_name, component_name, tfstate_filename,
                account_scheme, team_name,
            )
            state.init()

        check_call.assert_any_call(
            [
                'terraform', 'workspace',
                'new', environment_name,
                join(base_directory, sub_directory),
            ],
            cwd=base_directory,
        )

    @given(terraform_backend_input)
    def test_exiting_workspace_is_selected(self, terraform_backend_input):
        base_directory = terraform_backend_input['base_directory']
        sub_directory = terraform_backend_input['sub_directory']
        bucket_name = terraform_backend_input['bucket_name']
        lock_table_name = terraform_backend_input['lock_table_name']
        environment_name = terraform_backend_input['environment_name']
        component_name = terraform_backend_input['component_name']
        tfstate_filename = terraform_backend_input['tfstate_filename']
        team_name = terraform_backend_input['team_name']
        boto_session = MagicMock(spec=Session)
        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.classic_metadata_handling = False
        account_scheme.backend_s3_bucket = bucket_name
        account_scheme.backend_s3_dynamodb_table = lock_table_name

        with ExitStack() as stack:
            stack.enter_context(
                patch('cdflow_commands.state.NamedTemporaryFile')
            )
            stack.enter_context(patch('cdflow_commands.state.atexit'))
            check_call = stack.enter_context(
                patch('cdflow_commands.state.check_call')
            )
            check_output = stack.enter_context(
                patch('cdflow_commands.state.check_output')
            )

            check_output.return_value = (
                f'* default\n  {environment_name}\n\n'.encode('utf-8')
            )

            state = terraform_state(
                base_directory, sub_directory, boto_session,
                environment_name, component_name, tfstate_filename,
                account_scheme, team_name,
            )
            state.init()

        check_call.assert_any_call(
            [
                'terraform', 'workspace',
                'select', environment_name,
                join(base_directory, sub_directory),
            ],
            cwd=base_directory,
        )


class TestMigrateState(unittest.TestCase):

    def setUp(self):
        self.mock_s3 = mock_s3()
        self.mock_sts = mock_sts()
        self.mock_s3.start()
        self.mock_sts.start()

        self.team = 'a-team'
        self.component_name = 'a-service'
        self.raw_scheme = {
            'accounts': {
                'dev': {
                    'id': '123456789',
                    'role': 'admin',
                },
                'prod': {
                    'id': '987654321',
                    'role': 'admin',
                },
                'release': {
                    'id': '98754321',
                    'role': 'admin',
                },
            },
            'release-bucket': 'release-bucket',
            'lambda-bucket': 'lambda-bucket',
            'release-account': 'dev',
            'default-region': 'eu-west-1',
            'environments': {},
            'terraform-backend-s3-bucket': 'backend-s3-bucket',
            'terraform-backend-s3-dynamodb-table': 'backend-s3-dynamodb-table',
        }

        self.old_raw_scheme = {
            'accounts': {
                'dev': {
                    'id': '123456789',
                    'role': 'admin',
                },
                'prod': {
                    'id': '987654321',
                    'role': 'admin',
                },
            },
            'release-bucket': 'release-bucket',
            'lambda-bucket': 'lambda-bucket',
            'release-account': 'dev',
            'default-region': 'eu-west-1',
            'environments': {},
            'classic-metadata-handling': True,
        }

        self.s3_resource = boto3.resource('s3', region_name='eu-west-1')

        self.s3_client = boto3.client('s3', region_name='eu-west-1')

        self.old_state_bucket = 'cdflow-tfstate'
        self.new_state_bucket = 'backend-s3-bucket'

        self.s3_client.create_bucket(
            Bucket=self.old_state_bucket,
            CreateBucketConfiguration={
                'LocationConstraint': 'eu-west-1',
            },
        )
        self.s3_client.put_bucket_tagging(
            Bucket=self.old_state_bucket,
            Tagging={
                'TagSet': [
                    {
                        'Key': TFSTATE_TAG_NAME,
                        'Value': TAG_VALUE,
                    }
                ]
            }
        )

        self.s3_client.create_bucket(
            Bucket=self.new_state_bucket,
            CreateBucketConfiguration={
                'LocationConstraint': 'eu-west-1',
            },
        )

    def tearDown(self):
        self.mock_s3.stop()
        self.mock_sts.stop()

    def test_migrate_with_single_environment(self):
        del self.raw_scheme['accounts']['prod']
        del self.old_raw_scheme['accounts']['prod']

        account_scheme = AccountScheme.create(self.raw_scheme, self.team)
        old_scheme = AccountScheme.create(self.old_raw_scheme, self.team)

        original_state = self.s3_resource.Object(
            self.old_state_bucket,
            f'test/{self.component_name}/terraform.tfstate',
        )
        original_state.put(Body=b'state')

        root_session = Session(region_name='eu-west-1')
        migrate_state(
            root_session, account_scheme, old_scheme,
            self.team, self.component_name,
        )

        new_state = self.s3_resource.Object(
            self.new_state_bucket,
            f'{self.team}/{self.component_name}/test/terraform.tfstate',
        )
        response = new_state.get()
        body = response['Body'].read()

        assert body == b'state'

        migrated_marker = self.s3_resource.Object(
            self.new_state_bucket,
            f'{self.team}/{self.component_name}/test/MIGRATED',
        )
        migrated_response = migrated_marker.get()
        migrated_body = migrated_response['Body'].read()

        assert migrated_body == b'1'

    def test_migrate_with_multiple_environments(self):
        account_scheme = AccountScheme.create(self.raw_scheme, self.team)
        old_scheme = AccountScheme.create(self.old_raw_scheme, self.team)

        environments = ('ci', 'qa', 'aslive', 'live')

        for env in environments:
            self.s3_resource.Object(
                self.old_state_bucket,
                f'{env}/{self.component_name}/terraform.tfstate',
            ).put(Body=f'{env} state'.encode('utf-8'))

        root_session = Session(region_name='eu-west-1')
        migrate_state(
            root_session, account_scheme, old_scheme,
            self.team, self.component_name,
        )

        for env in environments:
            new_state = self.s3_resource.Object(
                self.new_state_bucket,
                f'{self.team}/{self.component_name}/{env}/terraform.tfstate',
            )
            response = new_state.get()
            body = response['Body'].read()

            assert body == f'{env} state'.encode()

            migrated_marker = self.s3_resource.Object(
                self.new_state_bucket,
                f'{self.team}/{self.component_name}/{env}/MIGRATED',
            )
            migrated_response = migrated_marker.get()
            migrated_body = migrated_response['Body'].read()

            assert migrated_body == b'1'

    def test_does_not_migrate_state_if_already_migrated(self):
        with freeze_time("2012-01-14") as frozen_time:
            account_scheme = AccountScheme.create(self.raw_scheme, self.team)
            old_scheme = AccountScheme.create(self.old_raw_scheme, self.team)

            environments = ('ci', 'qa', 'aslive', 'live')

            state_written_time = deepcopy(frozen_time)

            for env in environments:
                self.s3_resource.Object(
                    self.old_state_bucket,
                    f'{env}/{self.component_name}/terraform.tfstate',
                ).put(Body=f'{env} state'.encode('utf-8'))

                self.s3_resource.Object(
                    self.new_state_bucket,
                    (
                        f'{self.team}/{self.component_name}/'
                        f'{env}/terraform.tfstate'
                    ),
                ).put(Body=f'{env} state'.encode('utf-8'))

                self.s3_resource.Object(
                    self.new_state_bucket,
                    f'{self.team}/{self.component_name}/{env}/MIGRATED',
                ).put(Body=b'1')

            frozen_time.tick(datetime.timedelta(days=1))

            root_session = Session(region_name='eu-west-1')
            migrate_state(
                root_session, account_scheme, old_scheme,
                self.team, self.component_name,
            )

            for env in environments:
                new_state = self.s3_resource.Object(
                    self.new_state_bucket,
                    (
                        f'{self.team}/{self.component_name}/'
                        f'{env}/terraform.tfstate'
                    ),
                )

                assert new_state.last_modified.strftime("%Y-%m-%d") == \
                    state_written_time.time_to_freeze.strftime("%Y-%m-%d")

    def test_migrate_component_not_deployed_to_all_environments(self):
        account_scheme = AccountScheme.create(self.raw_scheme, self.team)
        old_scheme = AccountScheme.create(self.old_raw_scheme, self.team)

        environments = ('aslive', 'live')

        for env in environments:
            self.s3_resource.Object(
                self.old_state_bucket,
                f'{env}/{self.component_name}/terraform.tfstate',
            ).put(Body=f'{env} state'.encode('utf-8'))

        for env in ('ci', 'qa', 'acceptance'):
            self.s3_resource.Object(
                self.old_state_bucket,
                f'{env}/other-component/terraform.tfstate',
            ).put(Body=f'{env} state'.encode('utf-8'))

        root_session = Session(region_name='eu-west-1')
        migrate_state(
            root_session, account_scheme, old_scheme,
            self.team, self.component_name,
        )

        for env in environments:
            new_state = self.s3_resource.Object(
                self.new_state_bucket,
                f'{self.team}/{self.component_name}/{env}/terraform.tfstate',
            )
            response = new_state.get()
            body = response['Body'].read()

            assert body == f'{env} state'.encode()

            migrated_marker = self.s3_resource.Object(
                self.new_state_bucket,
                f'{self.team}/{self.component_name}/{env}/MIGRATED',
            )
            migrated_response = migrated_marker.get()
            migrated_body = migrated_response['Body'].read()

            assert migrated_body == b'1'
