FROM python:3.12-slim

# S3 emulado por Floci. Sin PyTorch, sin AWS real, sin entrenamiento.
RUN pip install --no-cache-dir "boto3>=1.35,<2"
COPY scripts/data/transform_behavioral_floci.py /opt/cinegraph/transform_behavioral_floci.py
COPY scripts/ml/stage_a9_feedback_floci.py /opt/cinegraph/stage_a9_feedback_floci.py
WORKDIR /opt/cinegraph
ENTRYPOINT ["python", "/opt/cinegraph/stage_a9_feedback_floci.py"]
CMD ["run"]