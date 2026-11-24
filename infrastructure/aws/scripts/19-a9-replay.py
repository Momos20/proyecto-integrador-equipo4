#!/usr/bin/env python3
"""Reproduce the validated historical A9 ranking using the existing AWS worker."""
import hashlib,json,os,pathlib,subprocess,sys
from datetime import datetime,timezone
import boto3
B="cinegraph-e4-datalake-023914826547-us-east-1"
H="8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358"
R="67920bb4da2cb8c28a785feb79452852ffbebf7c03e2e1c23bd3b1bf4a6397fc"
D="2023-06-15"
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""): h.update(b)
    return h.hexdigest()
def run(*a):
    subprocess.run([sys.executable,*map(str,a)],cwd=a9,check=True)
root=pathlib.Path("/opt/cinegraph-a9/ec2-20261124031146/work")
a9=root/"ml/a9_daily"
ratings=a9/"data/processed/ratings.parquet"
assert sha(root/"ml/models/A9_sin_id/modelo.pt")==H
assert sha(ratings)==R
s3=boto3.client("s3",region_name="us-east-1")
key="datasets/movielens32m/ratings_"+R[:16]+".parquet"
assert s3.head_object(Bucket=B,Key=key)["Metadata"]["sha256"]==R
prefix=os.environ["PREDICTION_PREFIX"]
assert prefix.startswith("predictions/a9/2023-06-15/orchestrated-")
out=pathlib.Path("/opt/cinegraph-a9/replays")/prefix.split("/")[-1]
out.mkdir(parents=True,exist_ok=False)
run("-m","tests.test_evaluacion")
run("-m","tests.test_diario")
prediction=out/"top10.json"
run("-m","src.recomendar","--fecha",D,"--usuarios","123","414","456","--k","10","--salida",prediction)
groups=json.loads(prediction.read_text())["recomendaciones"]
assert {g["userId"] for g in groups}=={123,414,456} and all(len(g["recomendaciones"])==10 for g in groups)
manifest={"entorno":"AWS EC2 t3.large","modelo":"GraphSAGE A9 original de Miguel; sin reentrenamiento","checkpoint_sha256":H,"ratings_parquet_s3":"s3://"+B+"/"+key,"ratings_sha256":R,"predicciones_sha256":sha(prediction),"fecha_utc":D,"usuarios":[123,414,456],"k":10,"protocolo":"replay historico UTC sin feedback 2026","pruebas_originales_ejecutadas":True,"grupos_usuario_generados":3,"creado_utc":datetime.now(timezone.utc).isoformat(),"salida_s3":"s3://"+B+"/"+prefix+"/top10.json"}
m=out/"top10.manifest.json"
m.write_text(json.dumps(manifest,indent=2))
s3.upload_file(str(prediction),B,prefix+"/top10.json")
s3.upload_file(str(m),B,prefix+"/top10.manifest.json")
print("A9_ORCHESTRATED_INFERENCE_OK",flush=True)
