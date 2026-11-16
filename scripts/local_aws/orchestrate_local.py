#!/usr/bin/env python3
"""Orquesta el ciclo behavioral de CineGraph en Docker + Floci, SOLO LOCAL.

El comando valida que cada etapa termine con código 0, guarda logs por paso
fuera de Git y no ejecuta entrenamiento, scoring ni comandos AWS reales.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.floci.yml", "--profile", "floci"]
RUN_DIR = ROOT / "artifacts" / "pipeline-runs"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_cutoff(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("--cutoff debe ser AAAA-MM-DD (UTC)") from None
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("--cutoff debe ser AAAA-MM-DD canónico")
    return value


def next_utc_date() -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()


def steps(cutoff: str) -> list[tuple[str, list[str]]]:
    # 'verify' comprueba realmente S3 Raw, no solo el envío a Kinesis.
    return [
        ("01-ship", COMPOSE + ["run", "--rm", "--build", "floci-tools", "ship"]),
        ("02-verify-raw", COMPOSE + ["run", "--rm", "floci-tools", "verify"]),
        ("03-transform", COMPOSE + ["run", "--rm", "--build", "behavioral-transform", "run"]),
        ("04-verify-curated-features", COMPOSE + ["run", "--rm", "behavioral-transform", "verify"]),
        ("05-stage-a9-shadow", COMPOSE + ["run", "--rm", "--build", "a9-feedback-stage", "run", "--cutoff", cutoff]),
        ("06-verify-a9-shadow", COMPOSE + ["run", "--rm", "a9-feedback-stage", "verify", "--cutoff", cutoff]),
    ]


def run_step(name: str, command: list[str], out_dir: Path) -> dict:
    start = time.monotonic()
    begun = utc_now()
    log_path = out_dir / f"{name}.log"
    print(f"\n{'='*12} {name} {'='*12}", flush=True)
    print("Comando:", " ".join(command), flush=True)
    try:
        with log_path.open("w", encoding="utf-8") as log:
            with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  bufsize=1) as process:
                assert process.stdout is not None
                for line in process.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                exit_code = process.wait()
    except (OSError, KeyboardInterrupt) as error:
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 127
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"Error local al ejecutar: {error}\n")
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
    return {
        "step": name, "command": command, "started_utc": begun,
        "finished_utc": utc_now(), "duration_seconds": round(time.monotonic() - start, 3),
        "exit_code": exit_code, "status": "ok" if exit_code == 0 else "failed",
        "log": log_path.name,
    }


def execute(cutoff: str, *, dry_run=False, run_dir: Path = RUN_DIR) -> int:
    planned = steps(cutoff)
    if dry_run:
        print("PLAN LOCAL (no ejecuta nada):")
        for label, cmd in planned:
            print(f"{label}: {' '.join(cmd)}")
        return 0
    # No modificar la base, S3 o el emulador si faltan servicios.
    if not (ROOT / "docker-compose.floci.yml").exists():
        raise RuntimeError("No se encuentra docker-compose.floci.yml en la raíz del proyecto")
    out_dir = run_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    out_dir.mkdir(parents=True, exist_ok=False)
    summary = {
        "pipeline": "cinegraph-floci-orchestrated-v1",
        "environment": "Floci local solamente",
        "cutoff_utc": cutoff, "created_utc": utc_now(),
        "status": "running", "steps": [],
        "note": "ETL y shadow-only; nunca ejecuta inferencia ni altera GraphSAGE A9.",
    }
    def save() -> None:
        (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save()
    for name, cmd in planned:
        result = run_step(name, cmd, out_dir)
        summary["steps"].append(result)
        if result["exit_code"]:
            summary["status"] = "failed"
            summary["failed_at"] = name
            summary["completed_utc"] = utc_now()
            save()
            print(f"\nPIPELINE DETENIDO: {name} falló. No se ejecutan etapas posteriores.", file=sys.stderr)
            print("Diagnóstico:", out_dir / result["log"], file=sys.stderr)
            return 1
        save()
    summary["status"] = "succeeded"
    summary["completed_utc"] = utc_now()
    save()
    print("\nSUCCESS: ship → Raw verificado → Curated/Features verificado → A9 shadow preparado y verificado.")
    print("Resumen y logs:", out_dir / "summary.json")
    print("NO se ejecutó ni publicó inferencia GraphSAGE; la preparación solo admite datos previos al corte UTC.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cutoff", type=validate_cutoff, default=next_utc_date(),
                   help="fecha de futuro scoring UTC YYYY-MM-DD (por defecto mañana UTC)")
    p.add_argument("--dry-run", action="store_true", help="mostrar orden de etapas sin ejecutar Docker")
    args = p.parse_args(argv)
    return execute(args.cutoff, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())