import unittest

from string import printable

from mock import patch, Mock, ANY
from hypothesis import given
from hypothesis.strategies import text, dictionaries, fixed_dictionaries

from boto3 import Session

from cdflow_commands.destroy import Destroy, DestroyConfig


CALL_KWARGS = 2


class TestDestroy(unittest.TestCase):

    def test_external_modules_are_imported(self):
        config = DestroyConfig(
            team='dummy-team',
            platform_config_file='./dummy/file/path.json'
        )
        destroy = Destroy(
            Mock(), 'dummy-component', 'dummy-environment', config
        )

        with patch('cdflow_commands.destroy.check_call') as check_call:
            destroy.run()

            check_call.assert_any_call(['terragrunt', 'get', 'infra'])

    @given(fixed_dictionaries({
        'component_name': text(alphabet=printable, min_size=1),
        'environment_name': text(alphabet=printable, min_size=1),
    }))
    def test_plan_was_called_via_terragrunt(self, test_fixtures):
        component_name = test_fixtures['component_name']
        environment_name = test_fixtures['environment_name']
        config = DestroyConfig(
            team='dummy-team',
            platform_config_file='./dummy/file/path.json'
        )
        boto_session = Session('ANY', 'ANY', 'ANY', 'dummy-region')
        destroy = Destroy(
            boto_session, component_name, environment_name, config
        )

        with patch('cdflow_commands.destroy.check_call') as check_call:
            destroy.run()

            check_call.assert_any_call(
                [
                    'terragrunt', 'plan',
                    '-var', 'component={}'.format(component_name),
                    '-var', 'env={}'.format(environment_name),
                    '-var', 'aws_region=dummy-region',
                    '-var', 'team=dummy-team',
                    '-var', 'image=any',
                    '-var', 'version=all',
                    '-var-file', './dummy/file/path.json',
                    'infra',
                ],
                env=ANY
            )

    @given(fixed_dictionaries({
        'component_name': text(alphabet=printable, min_size=1),
        'environment_name': text(alphabet=printable, min_size=1),
    }))
    def test_destroy_was_called_via_terragrunt(self, test_fixtures):
        component_name = test_fixtures['component_name']
        environment_name = test_fixtures['environment_name']
        config = DestroyConfig(
            team='dummy-team',
            platform_config_file='./dummy/file/path.json'
        )
        boto_session = Session('ANY', 'ANY', 'ANY', 'dummy-region')
        destroy = Destroy(
            boto_session, component_name, environment_name, config
        )

        with patch('cdflow_commands.destroy.check_call') as check_call:
            destroy.run()

            check_call.assert_any_call(
                [
                    'terragrunt', 'destroy',
                    '-force',
                    '-var', 'component={}'.format(component_name),
                    '-var', 'env={}'.format(environment_name),
                    '-var', 'aws_region=dummy-region',
                    '-var', 'team=dummy-team',
                    '-var', 'image=any',
                    '-var', 'version=all',
                    '-var-file', './dummy/file/path.json',
                    'infra',
                ],
                env=ANY
            )

    @given(fixed_dictionaries({
        'access_key': text(alphabet=printable, min_size=1),
        'secret_key': text(alphabet=printable, min_size=1),
        'session_token': text(alphabet=printable, min_size=1),
    }))
    def test_aws_config_was_passed_into_envionrment(self, aws_config):
        config = DestroyConfig(
            team='dummy-team',
            platform_config_file='./dummy/file/path.json'
        )
        boto_session = Session(
            aws_config['access_key'],
            aws_config['secret_key'],
            aws_config['session_token'],
            'dummy-region'
        )
        destroy = Destroy(
            boto_session, 'dummy-component', 'dummy-environment', config
        )

        with patch('cdflow_commands.destroy.check_call') as check_call:
            destroy.run()

            env = check_call.mock_calls[1][CALL_KWARGS]['env']
            assert env['AWS_ACCESS_KEY_ID'] == aws_config['access_key']
            assert env['AWS_SECRET_ACCESS_KEY'] == aws_config['secret_key']
            assert env['AWS_SESSION_TOKEN'] == aws_config['session_token']

            env = check_call.mock_calls[2][CALL_KWARGS]['env']
            assert env['AWS_ACCESS_KEY_ID'] == aws_config['access_key']
            assert env['AWS_SECRET_ACCESS_KEY'] == aws_config['secret_key']
            assert env['AWS_SESSION_TOKEN'] == aws_config['session_token']

    @given(dictionaries(
        keys=text(alphabet=printable, min_size=1),
        values=text(alphabet=printable, min_size=1),
        min_size=1
    ))
    def test_original_environment_was_preserved(self, mock_env):
        config = DestroyConfig(
            team='dummy-team',
            platform_config_file='./dummy/file/path.json'
        )
        boto_session = Session(
            'dummy-access-key',
            'dummy-secret-key',
            'dummy-session-token',
            'dummy-region'
        )
        destroy = Destroy(
            boto_session, 'dummy-component', 'dummy-environment', config
        )

        with patch(
            'cdflow_commands.destroy.check_call'
        ) as check_call, patch(
            'cdflow_commands.destroy.os'
        ) as mock_os:
            mock_os.environ = mock_env.copy()
            destroy.run()

            env = check_call.mock_calls[1][CALL_KWARGS]['env']
            for key, value in mock_env.items():
                assert env[key] == value

            env = check_call.mock_calls[2][CALL_KWARGS]['env']
            for key, value in mock_env.items():
                assert env[key] == value