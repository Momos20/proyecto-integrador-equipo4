FROM python:3.12-slim

# Solo transforma JSONL real de CineGraph (Floci local); sin motor ML ni AWS real.
RUN pip install --no-cache-dir "boto3>=1.35,<2"
COPY scripts/data/transform_behavioral_floci.py /opt/cinegraph/transform_behavioral_floci.py
WORKDIR /opt/cinegraph
ENTRYPOINT ["python", "/opt/cinegraph/transform_behavioral_floci.py"]
CMD ["run"]