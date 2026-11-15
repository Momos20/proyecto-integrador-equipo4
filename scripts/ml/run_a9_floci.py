#!/usr/bin/env python3
"""CineGraph: carga MovieLens y ejecuta A9 de Miguel contra S3 emulado por Floci.

SOLO LOCAL: rechaza cualquier endpoint distinto de http://localhost:4566,
http://127.0.0.1:4566 o http://floci:4566. No reentrena ni modifica A9.
La ejecucion siempre es manual. No usa credenciales AWS reales.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
A9_ROOT = ROOT / "ml" / "a9_daily"
PREPARE = ROOT / "scripts" / "data" / "prepare_miguel_a9.py"
MODEL = ROOT / "ml" / "models" / "A9_sin_id" / "modelo.pt"
MODEL_SHA256 = "8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358"
BUCKET = "cinegraph-local-datalake"
REGION = "us-east-1"
LOCAL_ENDPOINT = "http://127.0.0.1:4566"
DATA_PREFIX = "datasets/movielens32m/"
PREDICTION_PREFIX = "predictions/a9/"


def validate_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "floci"}
        or parsed.port != 4566
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("SEGURIDAD: solo se permite Floci local en http://127.0.0.1:4566 (o floci:4566 en Docker)")
    return endpoint.rstrip("/")


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print("Ejecutando:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def object_head(s3, key: str):
    from botocore.exceptions import ClientError
    try:
        return s3.head_object(Bucket=BUCKET, Key=key)
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404 or exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise


def upload_ratings(s3, local_file: Path, digest: str) -> str:
    key = DATA_PREFIX + f"ratings_clean_{digest[:16]}.parquet"
    head = object_head(s3, key)
    if head is not None:
        metadata_sha = (head.get("Metadata") or {}).get("sha256")
        if head.get("ContentLength") != local_file.stat().st_size or metadata_sha != digest:
            raise RuntimeError(f"Objeto previo con datos incompatibles: s3://{BUCKET}/{key}")
        print("Parquet ya almacenado y verificado en Floci: s3://" + BUCKET + "/" + key)
    else:
        print("Subiendo Parquet al S3 LOCAL emulado por Floci...", flush=True)
        s3.upload_file(str(local_file), BUCKET, key, ExtraArgs={"Metadata": {"sha256": digest}})
        confirmed = object_head(s3, key)
        if not confirmed or confirmed.get("ContentLength") != local_file.stat().st_size or (confirmed.get("Metadata") or {}).get("sha256") != digest:
            raise RuntimeError("La subida a Floci no pudo verificarse mediante HeadObject")
        print("Subido y verificado: s3://" + BUCKET + "/" + key)
    return key


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ratings-local", type=Path, required=True, help="Ruta a ratings_clean.parquet en tu Mac")
    parser.add_argument("--endpoint-url", default=LOCAL_ENDPOINT, help="Floci: http://127.0.0.1:4566 (o http://floci:4566 en Docker)")
    parser.add_argument("--solo-subir", action="store_true", help="Solo enviar y comprobar el Parquet en S3 local; no ejecuta ML")
    parser.add_argument("--fecha", default="2023-06-15", help="Fecha de prediccion UTC AAAA-MM-DD")
    parser.add_argument("--usuarios", nargs="+", type=int, default=[123, 456])
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--omitir-pruebas", action="store_true", help="Solo depuracion; no declarar el resultado validado")
    args = parser.parse_args(argv)
    try:
        args.endpoint_url = validate_endpoint(args.endpoint_url)
    except ValueError as exc:
        parser.error(str(exc))
    if not args.ratings_local.name.lower().endswith(".parquet"):
        parser.error("--ratings-local debe ser un archivo Parquet")
    if args.k < 1 or not args.usuarios or any(uid < 1 for uid in args.usuarios):
        parser.error("k debe ser positivo y los IDs de usuario deben ser positivos")
    try:
        if datetime.strptime(args.fecha, "%Y-%m-%d").strftime("%Y-%m-%d") != args.fecha:
            raise ValueError("fecha no canonica")
    except ValueError:
        parser.error("Fecha invalida. Usa AAAA-MM-DD")
    return args


def main(argv=None) -> None:
    args = parse_args(argv)
    input_path = args.ratings_local.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"No existe el Parquet en tu Mac: {input_path}")
    if input_path.stat().st_size == 0:
        raise ValueError("El Parquet está vacío")
    if not MODEL.is_file() or sha256_file(MODEL) != MODEL_SHA256:
        raise RuntimeError("Falta el checkpoint de Miguel o su SHA-256 no coincide. No se ejecuta A9.")

    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, EndpointConnectionError

    # Nunca usar credenciales/cuenta AWS: cliente apuntado al emulador local.
    s3 = boto3.client(
        "s3", endpoint_url=args.endpoint_url, region_name=REGION,
        aws_access_key_id="localtest", aws_secret_access_key="localtest",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
    )
    try:
        s3.head_bucket(Bucket=BUCKET)
    except (ClientError, EndpointConnectionError) as exc:
        raise RuntimeError(
            "No se puede leer el bucket Floci local. Inicia Floci y ejecuta 'floci-tools bootstrap' (docs/floci-local.md)."
        ) from exc

    digest = sha256_file(input_path)
    uploaded_key = upload_ratings(s3, input_path, digest)
    if args.solo_subir:
        print("LISTO: los datos están en S3 emulado. No se ejecutaron pruebas ni inferencia.")
        return

    with tempfile.TemporaryDirectory(prefix="cinegraph-a9-floci-") as temp_name:
        working = Path(temp_name)
        downloaded = working / "ratings_clean.parquet"
        output = working / "top10_a9.json"
        # El archivo consumido por A9 se descarga del bucket local, no se elude Floci.
        s3.download_file(BUCKET, uploaded_key, str(downloaded))
        if sha256_file(downloaded) != digest:
            raise RuntimeError("El Parquet descargado de Floci difiere del archivo de origen")
        run([sys.executable, str(PREPARE), "--ratings-parquet", str(downloaded)])
        if not args.omitir_pruebas:
            run([sys.executable, "-m", "tests.test_evaluacion"], cwd=A9_ROOT)
            run([sys.executable, "-m", "tests.test_diario"], cwd=A9_ROOT)
        run([sys.executable, "-m", "src.recomendar", "--fecha", args.fecha,
             "--usuarios", *map(str, args.usuarios), "--k", str(args.k),
             "--salida", str(output)], cwd=A9_ROOT)
        generated = json.loads(output.read_text(encoding="utf-8"))
        groups = generated.get("recomendaciones", [])
        if not groups or not any(item.get("recomendaciones") for item in groups):
            raise RuntimeError("A9 no generó recomendaciones Top-K; revisar IDs/fecha/historial")

        # Se conserva cada ejecución con sello UTC, sin sobrescribir predicciones anteriores.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target_key = f"{PREDICTION_PREFIX}{args.fecha}/top10_{stamp}.json"
        manifest_key = target_key.removesuffix(".json") + ".manifest.json"
        if object_head(s3, target_key) or object_head(s3, manifest_key):
            raise FileExistsError("El destino local ya existe; no se sobreescribirá")
        manifest = {
            "entorno": "Floci local (AWS emulado; sin servicios AWS reales)",
            "endpoint": args.endpoint_url,
            "modelo": "GraphSAGE A9 original de Miguel; sin reentrenamiento",
            "checkpoint_sha256": MODEL_SHA256,
            "ratings_parquet_s3_local": f"s3://{BUCKET}/{uploaded_key}",
            "ratings_sha256": digest,
            "predicciones_sha256": sha256_file(output),
            "fecha_utc": args.fecha,
            "usuarios": args.usuarios,
            "k": args.k,
            "protocolo": "diario de Miguel; ratings anteriores a la fecha UTC; NO horizonte 7 dias",
            "pruebas_originales_ejecutadas": not args.omitir_pruebas,
            "grupos_usuario_generados": len(groups),
            "creado_utc": datetime.now(timezone.utc).isoformat(),
            "salida_s3_local": f"s3://{BUCKET}/{target_key}",
        }
        s3.upload_file(str(output), BUCKET, target_key, ExtraArgs={"ContentType": "application/json"})
        s3.put_object(Bucket=BUCKET, Key=manifest_key,
                      Body=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                      ContentType="application/json")
        print("EXITO: A9 original produjo recomendaciones. Resultado Floci:")
        print("s3://" + BUCKET + "/" + target_key)
        print("Manifiesto: s3://" + BUCKET + "/" + manifest_key)
        print("Usuarios con recomendaciones:", len(groups))
        print("No se publicaron rankings en PostgreSQL ni se utilizó AWS real")


if __name__ == "__main__":
    main()