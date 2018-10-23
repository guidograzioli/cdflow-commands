FROM python:3.7.0-alpine3.8 AS base

ENV TERRAFORM_VERSION=0.11.7

ENV TERRAFORM_PROVIDER_ACME_VERSION=0.6.0

ENV TERRAFORM_PLUGIN_DIR=/root/.terraform.d/plugins/

ENV K8SVERSION=v1.8.11

RUN echo http://dl-cdn.alpinelinux.org/alpine/latest-stable/main >> /etc/apk/repositories
RUN apk update
RUN apk --no-cache add gcc musl-dev libffi-dev openssl-dev docker curl git zip unzip wget libc6-compat

RUN cd /tmp && \
    curl -o kubectl https://amazon-eks.s3-us-west-2.amazonaws.com/1.10.3/2018-07-26/bin/linux/amd64/kubectl && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl

RUN cd /tmp && \
    curl -o aws-iam-authenticator  https://amazon-eks.s3-us-west-2.amazonaws.com/1.10.3/2018-07-26/bin/linux/amd64/aws-iam-authenticator && \
    chmod +x ./aws-iam-authenticator && \
    mv ./aws-iam-authenticator /usr/local/bin/aws-iam-authenticator

RUN aws-iam-authenticator help

RUN mkdir -p "${TERRAFORM_PLUGIN_DIR}" && cd /tmp && \
    curl -sSLO "https://releases.hashicorp.com/terraform/$TERRAFORM_VERSION/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" && \
        unzip "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -d /usr/bin/ && \
    wget -q "https://github.com/paybyphone/terraform-provider-acme/releases/download/v${TERRAFORM_PROVIDER_ACME_VERSION}/terraform-provider-acme_v${TERRAFORM_PROVIDER_ACME_VERSION}_linux_amd64.zip" && \
        unzip "terraform-provider-acme_v${TERRAFORM_PROVIDER_ACME_VERSION}_linux_amd64.zip" -d "${TERRAFORM_PLUGIN_DIR}" && \
    rm -rf /tmp/* && \
    rm -rf /var/tmp/*

RUN mkdir -p /opt/cdflow-commands/cdflow_commands
WORKDIR /opt/cdflow-commands/

ENV PYTHONPATH=/opt/cdflow-commands

COPY ./requirements.txt ./requirements.txt
RUN pip install -r ./requirements.txt

FROM base AS test

COPY test_requirements.txt .
RUN pip install --no-cache-dir -r test_requirements.txt

COPY ./cdflow_commands /opt/cdflow-commands/cdflow_commands/
COPY ./test /opt/cdflow-commands/test/

FROM base

COPY ./cdflow_commands /opt/cdflow-commands/cdflow_commands/

ENTRYPOINT ["python", "-m", "cdflow_commands"]
