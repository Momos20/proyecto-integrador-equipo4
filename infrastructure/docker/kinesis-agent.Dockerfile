FROM amazonlinux:2

RUN yum install -y aws-kinesis-agent which findutils sed && \
    yum clean all

COPY infrastructure/kinesis/agent.json.template /opt/cinegraph/agent.json.template
COPY infrastructure/kinesis/entrypoint.sh /opt/cinegraph/entrypoint.sh

RUN chmod +x /opt/cinegraph/entrypoint.sh

ENTRYPOINT ["/opt/cinegraph/entrypoint.sh"]
