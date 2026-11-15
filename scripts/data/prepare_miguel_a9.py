#!/usr/bin/env python3
"""Prepara los Parquet esperados por el código original de Miguel, sin reentrenar.

No ejecuta GraphSAGE, Glue, SageMaker, GitHub Actions ni ningún pipeline.
"""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "data" / "reference" / "movielens32m"
PARTS = [REFERENCE / "parts" / f"movies.part{n:02d}.csv" for n in (1, 2, 3)]
CHECKSUMS = {
    "movies.csv": "0df90835c19151f9d819d0822e190797",
    "links.csv": "8f033867bcb4e6be8792b21468b4fa6e",
    "tags.csv": "963bf4fa4de6b8901868fddd3eb54567",
    "ratings.csv": "cf12b74f9ad4b94a011f079e26d4270a",
}


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def movie_csv_bytes() -> bytes:
    if not all(path.is_file() for path in PARTS):
        missing = [str(path) for path in PARTS if not path.is_file()]
        raise FileNotFoundError(f"Faltan las partes del catálogo en Git: {missing}")
    data = b"".join(path.read_bytes() for path in PARTS)
    if hashlib.md5(data).hexdigest() != CHECKSUMS["movies.csv"]:
        raise ValueError("El catálogo reconstruido no coincide con el MovieLens original")
    return data


def verify_reference() -> bytes:
    movie_data = movie_csv_bytes()
    links_path = REFERENCE / "links.csv"
    if not links_path.is_file() or md5_file(links_path) != CHECKSUMS["links.csv"]:
        raise ValueError("links.csv ausente o con suma MD5 incorrecta")
    print("OK MovieLens: movies.csv (87.585) y links.csv (87.585) idénticos al original")
    return movie_data


def normalize_ratings(table):
    """Acepta ratings.parquet canónico o el ratings_clean.parquet ya existente.

    Conserva los ratings originales. Solo normaliza nombres/tipos de columnas.
    """
    import pandas as pd

    aliases = {"user_id": "userId", "movie_id": "movieId"}
    table = table.rename(columns={k: v for k, v in aliases.items() if k in table.columns})
    expected = ["userId", "movieId", "rating", "timestamp"]
    if not set(expected).issubset(table.columns):
        raise ValueError(f"Ratings requiere las columnas {expected}; encontradas: {list(table.columns)}")
    table = table[expected].copy()
    table["userId"] = pd.to_numeric(table["userId"], errors="raise").astype("int32")
    table["movieId"] = pd.to_numeric(table["movieId"], errors="raise").astype("int32")
    table["rating"] = pd.to_numeric(table["rating"], errors="raise").astype("float32")
    if pd.api.types.is_datetime64_any_dtype(table["timestamp"]):
        table["timestamp"] = (
            pd.to_datetime(table["timestamp"], utc=True).astype("int64") // 1_000_000_000
        ).astype("int64")
    else:
        table["timestamp"] = pd.to_numeric(table["timestamp"], errors="raise").astype("int64")
    if table["timestamp"].max() > 10_000_000_000:
        raise ValueError("Los timestamps parecen milisegundos; Miguel requiere segundos Unix")
    return table


def run(args: argparse.Namespace) -> None:
    movie_data = verify_reference()
    if args.verify_only:
        if args.tags_csv:
            path = args.tags_csv.expanduser()
            if md5_file(path) != CHECKSUMS["tags.csv"]:
                raise ValueError("tags.csv no coincide con MovieLens 32M")
            print("OK tags.csv: 2.000.072 etiquetas verificadas (no se suben a Git)")
        return

    # Las salidas son exactamente las rutas y nombres que espera src/datos.py de Miguel.
    import pandas as pd

    out = args.output.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    movies = pd.read_csv(io.BytesIO(movie_data), dtype={
        "movieId": "int32", "title": "string", "genres": "string"
    })
    if len(movies) != 87_585:
        raise ValueError(f"Cantidad inesperada de películas: {len(movies)}")
    movies.to_parquet(out / "movies.parquet", index=False)
    links = pd.read_csv(REFERENCE / "links.csv", dtype={
        "movieId": "int32", "imdbId": "string", "tmdbId": "Int64"
    })
    if len(links) != 87_585:
        raise ValueError(f"Cantidad inesperada de links: {len(links)}")
    links.to_parquet(out / "links.parquet", index=False)
    print(f"Catálogo MovieLens disponible: {out}/movies.parquet y links.parquet")

    if args.ratings_parquet and args.ratings_csv:
        raise ValueError("Indica solo un origen de ratings: Parquet limpio o CSV")
    if args.ratings_parquet:
        source = args.ratings_parquet.expanduser().resolve()
        if source == (out / "ratings.parquet").resolve():
            # Ya está exactamente en el lugar de Miguel, no se requiere rescribir.
            print("Ratings ya está en data/processed/ratings.parquet; reutilizando sin cambios")
        else:
            ratings = normalize_ratings(pd.read_parquet(source))
            ratings.to_parquet(out / "ratings.parquet", index=False)
            print(f"Ratings limpios reutilizados: {len(ratings):,} registros")
    elif args.ratings_csv:
        source = args.ratings_csv.expanduser().resolve()
        if md5_file(source) != CHECKSUMS["ratings.csv"]:
            raise ValueError("ratings.csv no coincide con el MovieLens 32M original")
        # Convierte por lotes: no hace falta cargar los 32M ratings simultáneamente.
        import pyarrow as pa
        import pyarrow.parquet as pq

        dest = out / "ratings.parquet"
        writer = None
        total = 0
        try:
            for batch in pd.read_csv(source, dtype={
                "userId": "int32", "movieId": "int32",
                "rating": "float32", "timestamp": "int64",
            }, chunksize=500_000):
                arrow = pa.Table.from_pandas(batch, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(dest, arrow.schema)
                writer.write_table(arrow)
                total += len(batch)
        finally:
            if writer:
                writer.close()
        print(f"Ratings convertidos: {total:,} registros")
    else:
        print("PENDIENTE: falta ratings.parquet. A9 necesita ratings + movies para grafo/inferencia")

    if args.tags_csv:
        source = args.tags_csv.expanduser().resolve()
        if md5_file(source) != CHECKSUMS["tags.csv"]:
            raise ValueError("tags.csv no coincide con MovieLens 32M")
        tags = pd.read_csv(source, dtype={
            "userId": "int32", "movieId": "int32",
            "tag": "string", "timestamp": "int64",
        })
        tags.to_parquet(out / "tags.parquet", index=False)
        print(f"Tags opcionales: {len(tags):,} etiquetas preparadas")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Solo comprobar checksums; no convertir")
    parser.add_argument("--ratings-parquet", type=Path, help="ratings_clean.parquet o ratings.parquet existentes")
    parser.add_argument("--ratings-csv", type=Path, help="ratings.csv original, si no hay Parquet")
    parser.add_argument("--tags-csv", type=Path, help="tags.csv completo (opcional para A9)")
    parser.add_argument("--output", type=Path, default=ROOT / "ml" / "a9_daily" / "data" / "processed")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
