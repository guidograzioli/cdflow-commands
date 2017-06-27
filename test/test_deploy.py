import unittest
from collections import namedtuple
from contextlib import ExitStack
from string import digits

from hypothesis import given
from hypothesis.strategies import fixed_dictionaries, text
from mock import patch, Mock, MagicMock

from cdflow_commands.account import AccountScheme
from cdflow_commands.deploy import Deploy


BotoCredentials = namedtuple(
    'BotoCredentials', ['access_key', 'secret_key', 'token']
)


class TestDeploy(unittest.TestCase):

    @given(fixed_dictionaries({
        'component': text(),
        'version': text(),
        'environment': text(),
        'team': text(),
        'release_path': text(),
        'account': text(),
        'utcnow': text(alphabet=digits),
        'access_key': text(),
        'secret_key': text(),
        'token': text(),
    }))
    def test_deploy_runs_terraform_plan(self, fixtures):
        component = fixtures['component']
        version = fixtures['version']
        environment = fixtures['environment']
        team = fixtures['team']
        release_path = fixtures['release_path']
        account = fixtures['account']
        utcnow = fixtures['utcnow']
        access_key = fixtures['access_key']
        secret_key = fixtures['secret_key']
        token = fixtures['token']

        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.account_for_environment.return_value = account

        boto_session = Mock()
        boto_session.region_name = 'us-north-4'
        credentials = BotoCredentials(access_key, secret_key, token)
        boto_session.get_credentials.return_value = credentials

        deploy = Deploy(
            component, version, environment, team,
            release_path, account_scheme, boto_session,
        )

        with ExitStack() as stack:
            stack.enter_context(patch('cdflow_commands.deploy.path'))
            check_call = stack.enter_context(
                patch('cdflow_commands.deploy.check_call')
            )
            NamedTemporaryFile = stack.enter_context(
                patch('cdflow_commands.deploy.NamedTemporaryFile')
            )
            mock_os = stack.enter_context(patch('cdflow_commands.deploy.os'))
            get_secrets = stack.enter_context(
                patch('cdflow_commands.deploy.get_secrets')
            )
            datetime = stack.enter_context(
                patch('cdflow_commands.deploy.datetime')
            )

            datetime.utcnow.return_value.strftime.return_value = utcnow

            get_secrets.return_value = {}

            secret_file_path = NamedTemporaryFile.return_value.__enter__\
                .return_value

            mock_os.environ = {}

            dummy_plugin = Mock()
            dummy_plugin.parameters.return_value = []

            deploy.run(dummy_plugin)

            check_call.assert_any_call(
                [
                    'terraform', 'plan', 'infra',
                    '-var', 'component={}'.format(component),
                    '-var', 'env={}'.format(environment),
                    '-var', 'aws_region={}'.format(boto_session.region_name),
                    '-var', 'team={}'.format(team),
                    '-var', 'version={}'.format(version),
                    '-var-file', 'platform-config/{}/{}.json'.format(
                        account, boto_session.region_name
                    ),
                    '-var-file', secret_file_path,
                    '-out', 'plan-{}'.format(utcnow),
                    '-var-file', 'config/{}.json'.format(environment),
                ],
                cwd=release_path,
                env={
                    'AWS_ACCESS_KEY_ID': credentials.access_key,
                    'AWS_SECRET_ACCESS_KEY': credentials.secret_key,
                    'AWS_SESSION_TOKEN': credentials.token,
                }
            )

    @given(fixed_dictionaries({
        'component': text(),
        'version': text(),
        'environment': text(),
        'team': text(),
        'release_path': text(),
        'account': text(),
        'utcnow': text(alphabet=digits),
        'access_key': text(),
        'secret_key': text(),
        'token': text(),
    }))
    def test_deploy_runs_terraform_apply(self, fixtures):
        component = fixtures['component']
        version = fixtures['version']
        environment = fixtures['environment']
        team = fixtures['team']
        release_path = fixtures['release_path']
        account = fixtures['account']
        utcnow = fixtures['utcnow']
        access_key = fixtures['access_key']
        secret_key = fixtures['secret_key']
        token = fixtures['token']

        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.account_for_environment.return_value = account

        boto_session = Mock()
        boto_session.region_name = 'us-north-4'
        credentials = BotoCredentials(access_key, secret_key, token)
        boto_session.get_credentials.return_value = credentials

        deploy = Deploy(
            component, version, environment, team,
            release_path, account_scheme, boto_session,
        )

        with ExitStack() as stack:
            stack.enter_context(patch('cdflow_commands.deploy.path'))
            stack.enter_context(
                patch('cdflow_commands.deploy.NamedTemporaryFile')
            )
            check_call = stack.enter_context(
                patch('cdflow_commands.deploy.check_call')
            )
            mock_os = stack.enter_context(patch('cdflow_commands.deploy.os'))
            get_secrets = stack.enter_context(
                patch('cdflow_commands.deploy.get_secrets')
            )
            datetime = stack.enter_context(
                patch('cdflow_commands.deploy.datetime')
            )

            datetime.utcnow.return_value.strftime.return_value = utcnow

            get_secrets.return_value = {}

            mock_os.environ = {}

            dummy_plugin = Mock()
            dummy_plugin.parameters.return_value = []

            deploy.run(dummy_plugin)

            check_call.assert_any_call(
                ['terraform', 'apply', 'plan-{}'.format(utcnow)],
                cwd=release_path,
                env={
                    'AWS_ACCESS_KEY_ID': credentials.access_key,
                    'AWS_SECRET_ACCESS_KEY': credentials.secret_key,
                    'AWS_SESSION_TOKEN': credentials.token,
                }
            )

    @given(fixed_dictionaries({
        'component': text(),
        'version': text(),
        'environment': text(),
        'team': text(),
        'release_path': text(),
        'account': text(),
        'utcnow': text(alphabet=digits),
        'access_key': text(),
        'secret_key': text(),
        'token': text(),
    }))
    def test_plan_only_does_not_apply(self, fixtures):
        component = fixtures['component']
        version = fixtures['version']
        environment = fixtures['environment']
        team = fixtures['team']
        release_path = fixtures['release_path']
        account = fixtures['account']
        utcnow = fixtures['utcnow']
        access_key = fixtures['access_key']
        secret_key = fixtures['secret_key']
        token = fixtures['token']

        account_scheme = MagicMock(spec=AccountScheme)
        account_scheme.account_for_environment.return_value = account

        boto_session = Mock()
        boto_session.region_name = 'us-north-4'
        credentials = BotoCredentials(access_key, secret_key, token)
        boto_session.get_credentials.return_value = credentials

        deploy = Deploy(
            component, version, environment, team,
            release_path, account_scheme, boto_session,
        )

        with ExitStack() as stack:
            stack.enter_context(patch('cdflow_commands.deploy.path'))
            NamedTemporaryFile = stack.enter_context(
                patch('cdflow_commands.deploy.NamedTemporaryFile')
            )
            check_call = stack.enter_context(
                patch('cdflow_commands.deploy.check_call')
            )
            mock_os = stack.enter_context(patch('cdflow_commands.deploy.os'))
            get_secrets = stack.enter_context(
                patch('cdflow_commands.deploy.get_secrets')
            )
            datetime = stack.enter_context(
                patch('cdflow_commands.deploy.datetime')
            )

            datetime.utcnow.return_value.strftime.return_value = utcnow

            get_secrets.return_value = {}

            secret_file_path = NamedTemporaryFile.return_value.__enter__\
                .return_value

            mock_os.environ = {}

            dummy_plugin = Mock()
            dummy_plugin.parameters.return_value = []

            deploy.run(dummy_plugin, plan_only=True)

            check_call.assert_called_once_with(
                [
                    'terraform', 'plan', 'infra',
                    '-var', 'component={}'.format(component),
                    '-var', 'env={}'.format(environment),
                    '-var', 'aws_region={}'.format(boto_session.region_name),
                    '-var', 'team={}'.format(team),
                    '-var', 'version={}'.format(version),
                    '-var-file', 'platform-config/{}/{}.json'.format(
                        account, boto_session.region_name
                    ),
                    '-var-file', secret_file_path,
                    '-out', 'plan-{}'.format(utcnow),
                    '-var-file', 'config/{}.json'.format(environment),
                ],
                cwd=release_path,
                env={
                    'AWS_ACCESS_KEY_ID': credentials.access_key,
                    'AWS_SECRET_ACCESS_KEY': credentials.secret_key,
                    'AWS_SESSION_TOKEN': credentials.token,
                }
            )
