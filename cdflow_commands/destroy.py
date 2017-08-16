import os
from subprocess import check_call
from time import time

from cdflow_commands.config import env_with_aws_credetials
from cdflow_commands.constants import (
    TERRAFORM_BINARY, TERRAFORM_DESTROY_DEFINITION
)


class Destroy:

    def __init__(self, boto_session):
        self._boto_session = boto_session

    def run(self, plan_only=False):
        self._plan()
        if not plan_only:
            self._destroy()

    def _plan(self):
        check_call(
            [
                TERRAFORM_BINARY, 'plan', '-destroy',
                '-var', 'aws_region={}'.format(self._boto_session.region_name),
                '-out', self.plan_path,
                TERRAFORM_DESTROY_DEFINITION,
            ],
            env=env_with_aws_credetials(
                os.environ, self._boto_session
            ),
            cwd='/cdflow',
        )

    def _destroy(self):
        check_call(
            [TERRAFORM_BINARY, 'apply', self.plan_path],
            env=env_with_aws_credetials(
                os.environ, self._boto_session
            ),
            cwd='/cdflow',
        )

    @property
    def plan_path(self):
        if not hasattr(self, '_plan_path'):
            self._plan_path = 'plan-{}'.format(time())
        return self._plan_path