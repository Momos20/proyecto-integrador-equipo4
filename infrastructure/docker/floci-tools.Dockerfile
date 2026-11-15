FROM python:3.12-slim
RUN pip install --no-cache-dir "boto3>=1.35,<2"
COPY scripts/local_aws/manage.py /opt/cinegraph/manage.py
WORKDIR /opt/cinegraph
ENTRYPOINT ["python", "/opt/cinegraph/manage.py"]
CMD ["status"]
