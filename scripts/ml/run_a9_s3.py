#!/usr/bin/env python3
"""Ejecuta una prueba MANUAL del A9 original usando ratings Parquet en S3.

Este orquestador no modifica src/ de Miguel, no entrena el modelo ni crea recursos
AWS. Necesita credenciales IAM del entorno, PyTorch Geometric y acceso S3.
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

REPO_ROOT = Path(__file__).resolve().parents[2]
A9_ROOT = REPO_ROOT / "ml" / "a9_daily"
PREPARE = REPO_ROOT / "scripts" / "data" / "prepare_miguel_a9.py"
CHECKPOINT = REPO_ROOT / "ml" / "models" / "A9_sin_id" / "modelo.pt"
CHECKPOINT_SHA256 = "8c9aa61fb7e8d3ed3a6476fe759f9861283387bc6561ea5aa03595ab516a2358"


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Acepta solo objetos S3 concretos; no nombres de bucket sueltos."""
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Se esperaba s3://bucket/objeto, recibido: {uri!r}")
    if parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port:
        raise ValueError("La URI S3 no debe incluir usuario, puerto, query ni fragmentos")
    return parsed.netloc, parsed.path.lstrip("/")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(command: list[str], cwd: Path = REPO_ROOT) -> None:
    print("Ejecutando:", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ratings-s3", required=True,
                        help="s3://bucket/.../ratings_clean.parquet, fuente MovieLens 32M")
    parser.add_argument("--salida-s3", required=True,
                        help="s3://bucket/.../top10_a9_YYYY-MM-DD.json, destino sin sobrescribir")
    parser.add_argument("--fecha", default="2023-06-15", help="Día UTC AAAA-MM-DD")
    parser.add_argument("--usuarios", type=int, nargs="+", default=[123, 456])
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--omitir-pruebas", action="store_true",
                        help="Sólo para depuración; no declarar el resultado validado")
    args = parser.parse_args()

    try:
        datetime.strptime(args.fecha, "%Y-%m-%d")
    except ValueError as exc:
        parser.error(f"Fecha inválida: {exc}")
    if args.k < 1 or not args.usuarios or any(u < 1 for u in args.usuarios):
        parser.error("Indica k >= 1 y usuarios con identificadores positivos")
    try:
        ratings_bucket, ratings_key = parse_s3_uri(args.ratings_s3)
        output_bucket, output_key = parse_s3_uri(args.salida_s3)
    except ValueError as exc:
        parser.error(str(exc))
    if not ratings_key.lower().endswith(".parquet"):
        parser.error("El origen debe ser un archivo Parquet")
    if not output_key.lower().endswith(".json"):
        parser.error("La salida debe terminar en .json")
    if args.ratings_s3 == args.salida_s3:
        parser.error("El origen y la salida deben ser diferentes")

    # A9 permanece original. Se comprueba el checkpoint antes de acceder a los datos.
    if not CHECKPOINT.is_file():
        raise FileNotFoundError(f"Falta el checkpoint original: {CHECKPOINT}")
    actual_sha = sha256_file(CHECKPOINT)
    if actual_sha != CHECKPOINT_SHA256:
        raise RuntimeError("El checkpoint difiere del SHA-256 de Miguel; se detiene la prueba")

    import boto3  # Sólo necesario al ejecutar en la cuenta AWS.
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3")
    source = s3.head_object(Bucket=ratings_bucket, Key=ratings_key)
    if source.get("ContentLength", 0) == 0:
        raise ValueError("El objeto Parquet de entrada está vacío")
    # No sobrescribir resultados previos para preservar la trazabilidad.
    try:
        s3.head_object(Bucket=output_bucket, Key=output_key)
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
            raise
    else:
        raise FileExistsError(f"La salida ya existe en S3: {args.salida_s3}")

    with tempfile.TemporaryDirectory(prefix="cinegraph-a9-") as temp_name:
        workdir = Path(temp_name)
        ratings = workdir / "ratings_clean.parquet"
        output = workdir / "topk_a9.json"
        print(f"Descargando ratings desde {args.ratings_s3}...", flush=True)
        s3.download_file(ratings_bucket, ratings_key, str(ratings))
        ratings_sha = sha256_file(ratings)
        run([sys.executable, str(PREPARE), "--ratings-parquet", str(ratings)])
        if not args.omitir_pruebas:
            run([sys.executable, "-m", "tests.test_evaluacion"], cwd=A9_ROOT)
            run([sys.executable, "-m", "tests.test_diario"], cwd=A9_ROOT)
        run([sys.executable, "-m", "src.recomendar", "--fecha", args.fecha,
             "--usuarios", *map(str, args.usuarios), "--k", str(args.k),
             "--salida", str(output)], cwd=A9_ROOT)
        generated = json.loads(output.read_text(encoding="utf-8"))
        entries = generated.get("recomendaciones", [])
        if not entries:
            raise RuntimeError("A9 no produjo recomendaciones: revisar fecha/usuarios/historial")
        manifest = {
            "modelo": "GraphSAGE A9 de Miguel, checkpoint original sin reentrenamiento",
            "protocolo": "Diario UTC; sólo historial anterior a la fecha de predicción",
            "checkpoint_sha256": actual_sha,
            "ratings_s3": args.ratings_s3,
            "ratings_sha256": ratings_sha,
            "fecha": args.fecha,
            "usuarios": args.usuarios,
            "k": args.k,
            "pruebas_originales_ejecutadas": not args.omitir_pruebas,
            "grupos_usuario_generados": len(entries),
            "creado_utc": datetime.now(timezone.utc).isoformat(),
            "salida_s3": args.salida_s3,
        }
        # Se sube sólo cuando las pruebas y la inferencia hayan terminado bien.
        s3.upload_file(str(output), output_bucket, output_key,
                       ExtraArgs={"ContentType": "application/json"})
        manifest_key = output_key.removesuffix(".json") + ".manifest.json"
        s3.put_object(Bucket=output_bucket, Key=manifest_key,
                      Body=json.dumps(manifest, indent=2, ensure_ascii=False).encode(),
                      ContentType="application/json")
        print("Prueba terminada. Recomendaciones:", args.salida_s3)
        print("Manifest:", f"s3://{output_bucket}/{manifest_key}")
        print("Grupos con recomendaciones:", len(entries))


if __name__ == "__main__":
    main()