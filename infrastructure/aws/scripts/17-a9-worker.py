#!/usr/bin/env python3
"""EC2 CPU job, historical A9 inference. No live behavioral mixing."""
import hashlib,json,os,pathlib,subprocess,sys,tarfile,urllib.request,zipfile
from datetime import datetime,timezone
import boto3

def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for block in iter(lambda:f.read(1048576),b""): h.update(block)
    return h.hexdigest()
def run(*args,cwd=None):
    subprocess.run([str(x) for x in args],cwd=cwd,check=True)
base=pathlib.Path("/opt/cinegraph-a9") / os.environ["PREDICTION_PREFIX"].split("/")[-1]
base.mkdir(parents=True,exist_ok=False)
work=base/"work"
work.mkdir(exist_ok=True)
out=base/"output"
out.mkdir(exist_ok=True)
bucket="cinegraph-e4-datalake-023914826547-us-east-1"
modelhash="8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358"
s3=boto3.client("s3",region_name="us-east-1")
s3.download_file(bucket,"models/a9/a9-source.tar.gz",str(base/"a9-source.tar.gz"))
with tarfile.open(base/"a9-source.tar.gz") as t:
    for member in t.getmembers():
        if member.issym() or member.islnk() or not (work/member.name).resolve().is_relative_to(work.resolve()):
            raise RuntimeError("Unsafe archive")
    t.extractall(work)
assert sha(work/"ml/models/A9_sin_id/modelo.pt")==modelhash
run(sys.executable,"-m","pip","install","--no-cache-dir","certifi")
run(sys.executable,"-m","pip","install","--no-cache-dir","--only-binary=:all:","typing-extensions==4.12.2","filelock","networkx","jinja2","fsspec","sympy==1.13.1")
run(sys.executable,"-m","pip","install","--no-cache-dir","--no-deps","torch==2.5.1+cpu","--index-url","https://download.pytorch.org/whl/cpu")
run(sys.executable,"-m","pip","install","--no-cache-dir","numpy==1.26.4","pandas==2.2.3","pyarrow==18.1.0","scipy==1.14.1","torch-geometric==2.6.1","matplotlib==3.9.4")
archive=work/"ml-32m.zip"
import ssl
import certifi
import shutil
url = "https://files.grouplens.org/datasets/movielens/ml-32m.zip"
context = ssl.create_default_context(cafile=certifi.where())
print("Downloading MovieLens 32M with certificate verification", flush=True)
with urllib.request.urlopen(url, context=context, timeout=120) as response, archive.open("wb") as dest:
    shutil.copyfileobj(response, dest, length=1024*1024)
print("MOVIELENS_DOWNLOAD_OK", archive.stat().st_size, flush=True)
with zipfile.ZipFile(archive) as z:
    with z.open("ml-32m/ratings.csv") as src, open(work/"ratings.csv","wb") as dest:
        import shutil
        shutil.copyfileobj(src,dest)
ratings=work/"ratings.csv"
run(sys.executable,work/"scripts/data/prepare_miguel_a9.py","--ratings-csv",ratings)
a9=work/"ml/a9_daily"
parquet=a9/"data/processed/ratings.parquet"
digest=sha(parquet)
s3=boto3.client("s3",region_name="us-east-1")
key="datasets/movielens32m/ratings_"+digest[:16]+".parquet"
s3.upload_file(str(parquet),bucket,key,ExtraArgs={"Metadata":{"sha256":digest}})
run(sys.executable,"-m","tests.test_evaluacion",cwd=a9)
run(sys.executable,"-m","tests.test_diario",cwd=a9)
date="2023-06-15"
prediction=out/"top10.json"
run(sys.executable,"-m","src.recomendar","--fecha",date,"--usuarios","123","414","456","--k","10","--salida",prediction,cwd=a9)
result=json.loads(prediction.read_text())
groups=result["recomendaciones"]
assert {g["userId"] for g in groups}=={123,414,456}
assert all(len(g["recomendaciones"])==10 for g in groups)
prefix=os.environ["PREDICTION_PREFIX"]
manifest={"entorno":"AWS EC2 t3.large","modelo":"GraphSAGE A9 original de Miguel; sin reentrenamiento","checkpoint_sha256":modelhash,"ratings_parquet_s3":"s3://"+bucket+"/"+key,"ratings_sha256":digest,"predicciones_sha256":sha(prediction),"fecha_utc":date,"usuarios":[123,414,456],"k":10,"protocolo":"historico diario UTC, sin feedback 2026","pruebas_originales_ejecutadas":True,"grupos_usuario_generados":len(groups),"creado_utc":datetime.now(timezone.utc).isoformat(),"salida_s3":"s3://"+bucket+"/"+prefix+"/top10.json"}
(out/"top10.manifest.json").write_text(json.dumps(manifest,indent=2))
s3.upload_file(str(prediction),bucket,prefix+"/top10.json")
s3.upload_file(str(out/"top10.manifest.json"),bucket,prefix+"/top10.manifest.json")
print("A9_INFERENCE_OK",flush=True)
