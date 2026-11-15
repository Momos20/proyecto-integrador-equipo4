#!/usr/bin/env python3
"""Publica un Top-K REAL de A9 guardado en S3 local de Floci, nunca el ejemplo CSV/JSON.

Sólo se ejecuta manualmente. Valida manifiesto, checkpoint y scores; no reentrena.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from datetime import date
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from sqlalchemy import text
from app.db import get_engine, _database_url

EXPECTED_SHA = "8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358"
VERSION = "a9-miguel-diario"
BUCKET = "cinegraph-local-datalake"
PREFIX = "predictions/a9/"
ENDPOINT = "http://floci:4566"


def load_latest(s3, target_key=None):
    listing=s3.list_objects_v2(Bucket=BUCKET,Prefix=PREFIX)
    objects=[entry for entry in listing.get("Contents",[]) if entry["Key"].endswith(".json") and not entry["Key"].endswith(".manifest.json")]
    keys=[entry["Key"] for entry in objects]
    if not keys: raise RuntimeError("No hay predicciones A9 reales en Floci. Ejecuta run_a9_floci.py primero.")
    key=target_key or max(objects, key=lambda item:item["LastModified"])["Key"]
    if key not in keys: raise ValueError("La clave solicitada no es una predicción existente de A9")
    manifest_key=key[:-5]+".manifest.json"
    prediction_bytes = s3.get_object(Bucket=BUCKET,Key=key)["Body"].read()
    result=json.loads(prediction_bytes)
    manifest=json.loads(s3.get_object(Bucket=BUCKET,Key=manifest_key)["Body"].read())
    if manifest.get("predicciones_sha256") != hashlib.sha256(prediction_bytes).hexdigest():
        raise RuntimeError("El JSON de recomendaciones no coincide con su manifiesto SHA-256")
    if manifest.get("entorno") != "Floci local (AWS emulado; sin servicios AWS reales)":
        raise RuntimeError("Origen no reconocido: se requiere una inferencia local trazable")
    if manifest.get("checkpoint_sha256") != EXPECTED_SHA or manifest.get("pruebas_originales_ejecutadas") is not True:
        raise RuntimeError("El manifiesto no acredita checkpoint y pruebas originales de Miguel")
    if manifest.get("salida_s3_local") != "s3://"+BUCKET+"/"+key:
        raise RuntimeError("El manifiesto no corresponde al resultado escogido")
    if result.get("modelo") != "GraphSAGE A9 (sin embeddings de ID)" or result.get("pesos") != "ml/models/A9_sin_id/modelo.pt":
        raise RuntimeError("El JSON no fue emitido por el recomendador A9 esperado")
    cutoff=date.fromisoformat(manifest["fecha_utc"])
    groups=result.get("recomendaciones",[])
    if not groups: raise RuntimeError("No hay usuarios con ranking")
    rows=[]; found=set()
    for group in groups:
        user=int(group["userId"])
        if (user, cutoff) in found: raise ValueError("Usuario duplicado")
        found.add((user,cutoff))
        if group.get("fecha")!=str(cutoff): raise ValueError("Fecha inconsistente en ranking")
        items=group.get("recomendaciones",[])
        if not items: continue
        positions=[]; movies=set()
        for rec in items:
            movie=int(rec["movieId"]); position=int(rec["posicion"]); score=float(rec["puntaje"])
            if movie <=0 or position<=0 or movie in movies or not math.isfinite(score):
                raise ValueError("Recomendación corrupta o score no finito")
            movies.add(movie);positions.append(position)
            rows.append((user,movie,position,score))
        if sorted(positions)!=list(range(1,len(positions)+1)): raise ValueError("Ranking no secuencial")
    if not rows: raise ValueError("A9 no devolvió recomendaciones para publicar")
    return key, manifest, cutoff, rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key",help="Objeto bajo predictions/a9/; omitir para utilizar el más reciente")
    args=parser.parse_args()
    parsed=urlsplit(_database_url())
    if os.getenv("CINEGRAPH_LOCAL_SETUP")!="1" or parsed.hostname not in {"db","localhost","127.0.0.1"}:
        raise RuntimeError("SEGURIDAD: publicación sólo contra PostgreSQL local")
    s3=boto3.client("s3",endpoint_url=ENDPOINT,region_name="us-east-1",aws_access_key_id="localtest",aws_secret_access_key="localtest",config=Config(s3={"addressing_style":"path"}))
    key, manifest, cutoff, rows=load_latest(s3,args.key)
    engine=get_engine()
    with engine.begin() as conn:
        missing=conn.execute(text("SELECT count(*) FROM movies WHERE movie_id = ANY(:ids)"),
          {"ids":list({row[1] for row in rows})}).scalar()
        if missing != len({row[1] for row in rows}):
            raise RuntimeError("Faltan películas reales en PostgreSQL: ejecuta local-setup primero")
        prior=conn.execute(text("SELECT 1 FROM scoring_runs WHERE model_version=:v AND cutoff_week=:d"),{"v":VERSION,"d":cutoff}).first()
        if prior: raise RuntimeError("Ya se publicó A9 para esa fecha. No se sobreescribe una ejecución validada")
        # Promoción sólo cuando la validación del manifiesto ha pasado.
        conn.execute(text("UPDATE model_versions SET status='archived' WHERE status='champion' AND model_version<>:v"),{"v":VERSION})
        conn.execute(text("""
          INSERT INTO model_versions(model_version,model_name,status,artifact_uri,cutoff_week)
          VALUES(:v,'GraphSAGE A9 de Miguel','champion','ml/models/A9_sin_id/modelo.pt',:d)
          ON CONFLICT(model_version) DO UPDATE SET status='champion',cutoff_week=EXCLUDED.cutoff_week
        """),{"v":VERSION,"d":cutoff})
        run_id=conn.execute(text("""
          INSERT INTO scoring_runs(model_version,cutoff_week,source_uri,output_uri,status,users_scored,recommendations_written,finished_at)
          VALUES(:v,:d,:source,:dest,'succeeded',:users,:cnt,NOW()) RETURNING scoring_run_id
        """),{"v":VERSION,"d":cutoff,"source":manifest["ratings_parquet_s3_local"],
          "dest":"s3://"+BUCKET+"/"+key,"users":len({r[0] for r in rows}),"cnt":len(rows)}).scalar_one()
        # Inserciones estrictamente del JSON de Miguel; scores y posiciones originales.
        for user,movie,position,score in rows:
            conn.execute(text("""
              INSERT INTO recommendations(user_id,movie_id,rank,score,model_version,cutoff_week,scoring_run_id)
              VALUES(:u,:m,:p,:s,:v,:d,:run)
            """),{"u":user,"m":movie,"p":position,"s":score,"v":VERSION,"d":cutoff,"run":run_id})
    print(f"OK: {len(rows)} recomendaciones A9 reales publicadas para {len(set(r[0] for r in rows))} usuarios, corte {cutoff}.")
    print("Origen:","s3://"+BUCKET+"/"+key)
    print("La API mostrará estos rankings sólo al usuario autenticado correspondiente.")

if __name__=="__main__":main()
