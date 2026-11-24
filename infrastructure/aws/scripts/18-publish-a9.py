#!/usr/bin/env python3
"""Publish only the verified AWS historical run; transactional, no credentials in logs."""
import boto3, hashlib, json, math, os, sys
from datetime import date
import psycopg
B="cinegraph-e4-datalake-023914826547-us-east-1"
P="predictions/a9/2023-06-15/ec2-20261124031146/"
V="a9-miguel-diario"
H="8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358"
D=date(2023,6,15)
def check(ok,label):
    if not ok: raise ValueError(label)
def main():
    s=boto3.client("s3",region_name="us-east-1")
    def read(k): return s.get_object(Bucket=B,Key=k)["Body"].read()
    raw=read(P+"top10.json")
    m=json.loads(read(P+"top10.manifest.json"))
    j=json.loads(raw)
    uri="s3://"+B+"/"+P+"top10.json"
    check(m["entorno"]=="AWS EC2 t3.large" and m["checkpoint_sha256"]==H and m["pruebas_originales_ejecutadas"] is True and m["predicciones_sha256"]==hashlib.sha256(raw).hexdigest() and m["salida_s3"]==uri and m["fecha_utc"]==str(D) and m["k"]==10,"MANIFEST")
    check(hashlib.sha256(read("models/a9/modelo.pt")).hexdigest()==H,"CHECKPOINT")
    source=m["ratings_parquet_s3"]
    check(source.startswith("s3://"+B+"/datasets/movielens32m/"),"DATASET_URI")
    head=s.head_object(Bucket=B,Key=source.split("/",3)[3])
    check(head["Metadata"].get("sha256")==m["ratings_sha256"],"DATASET_METADATA")
    check(j["modelo"]=="GraphSAGE A9 (sin embeddings de ID)" and j["pesos"]=="ml/models/A9_sin_id/modelo.pt","MODEL")
    rows=[]; users=set()
    for g in j["recomendaciones"]:
        u=int(g["userId"]); items=g["recomendaciones"]
        check(u not in users and g["fecha"]==str(D) and len(items)==10,"GROUP")
        users.add(u)
        check(sorted(int(i["posicion"]) for i in items)==list(range(1,11)) and len({int(i["movieId"]) for i in items})==10,"RANK")
        for i in items:
            movie=int(i["movieId"]); score=float(i["puntaje"])
            check(movie>0 and math.isfinite(score),"SCORE")
            rows.append((u,movie,int(i["posicion"]),score))
    check(users=={123,414,456} and len(rows)==30,"USERS")
    print("A9_S3_VALIDATED: 30 rows, checkpoint and prediction SHA256 OK",flush=True)
    host=os.environ["RDS_ENDPOINT"]
    check(host.startswith("cinegraph-e4-postgres.") and host.endswith(".us-east-1.rds.amazonaws.com"),"HOST")
    secret=json.loads(boto3.client("secretsmanager",region_name="us-east-1").get_secret_value(SecretId=os.environ["RDS_SECRET_ARN"])["SecretString"])
    check(secret["username"]=="cinegraphadmin","DB_ROLE")
    with psycopg.connect(host=host,port=5432,dbname="cinegraph",user=secret["username"],password=secret["password"],sslmode="verify-full",sslrootcert="/tmp/cinegraph-rds-ca.pem",connect_timeout=10) as db:
        db.execute("SELECT pg_advisory_xact_lock(20261124,18)")
        ids=list({x[1] for x in rows})
        check(db.execute("SELECT count(*) FROM movies WHERE movie_id=ANY(%s)",(ids,)).fetchone()[0]==len(ids),"CATALOG")
        prior=db.execute("SELECT scoring_run_id,output_uri,status FROM scoring_runs WHERE model_version=%s AND cutoff_week=%s",(V,D)).fetchone()
        if prior:
            check(prior[1:]==(uri,"succeeded"),"EXISTING_RUN_CONFLICT")
            run=prior[0]
        else:
            check(not db.execute("SELECT 1 FROM model_versions WHERE status='champion' AND model_version<>%s",(V,)).fetchone(),"OTHER_CHAMPION")
            db.execute("INSERT INTO model_versions(model_version,model_name,status,artifact_uri,cutoff_week,promoted_at) VALUES(%s,'GraphSAGE A9 de Miguel','champion',%s,%s,NOW()) ON CONFLICT(model_version) DO UPDATE SET status='champion',cutoff_week=EXCLUDED.cutoff_week,artifact_uri=EXCLUDED.artifact_uri,promoted_at=NOW()",(V,"s3://"+B+"/models/a9/modelo.pt",D))
            run=db.execute("INSERT INTO scoring_runs(model_version,cutoff_week,source_uri,output_uri,status,users_scored,recommendations_written,finished_at) VALUES(%s,%s,%s,%s,'succeeded',3,30,NOW()) RETURNING scoring_run_id",(V,D,source,uri)).fetchone()[0]
            for u,movie,rank,score in rows:
                db.execute("INSERT INTO recommendations(user_id,movie_id,rank,score,model_version,cutoff_week,scoring_run_id) VALUES(%s,%s,%s,%s,%s,%s,%s)",(u,movie,rank,score,V,D,run))
        actual=db.execute("SELECT user_id,movie_id,rank,score FROM recommendations WHERE scoring_run_id=%s",(run,)).fetchall()
        check(sorted(actual)==sorted(rows),"RDS_ROWS")
    print("A9_RDS_PUBLISHED: 30 recommendations, 3 users, run_id="+str(run),flush=True)
if __name__=="__main__":
    try: main()
    except Exception as e:
        print("A9_PUBLISH_FAILED:",type(e).__name__,str(e) if isinstance(e,ValueError) and str(e).isupper() else "",file=sys.stderr)
        sys.exit(1)
