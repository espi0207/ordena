"""Uso desde la terminal. Sin opciones solo enseña el plan; --aplicar lo hace."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from collections import Counter
from pathlib import Path

from . import __version__, demo
from .ansi import clean, paint
from .folders import downloads_folder, refuse_reason
from .organizer import DUPLICATES, JOURNAL, Plan, apply_plan, build_plan, last_run, undo_last
from .report import human_size, plural, run_date, summary_key


def command(folder: str | None, *flags: str) -> str:
    """La orden para copiar y pegar, con la carpeta entre comillas si hace falta."""
    words = ["ordena"]
    if folder is not None:
        if os.name == "nt":
            words.append(f'"{folder}"' if " " in folder else folder)
        else:
            words.append(shlex.quote(folder))
    return clean(" ".join(words + [f for f in flags if f]))


def print_summary(plan: Plan) -> None:
    counts = Counter(summary_key(m.folder) for m in plan.moves)
    width = max(len(key[2]) for key in counts) + 3
    for key in sorted(counts):
        label = key[2]
        line = f"  {label:<{width}}{counts[key]:>4}"
        if label == DUPLICATES:
            freed = human_size(sum(m.size for m in plan.duplicates))
            line = paint(line, "yellow") + paint(f"   si los borras, liberas {freed}", "gray")
        print(line)


def print_detail(plan: Plan) -> None:
    by_folder: dict[str, list] = {}
    for move in plan.moves:
        by_folder.setdefault(move.folder, []).append(move)
    width = max(len(clean(m.source)) for m in plan.moves) + 3
    for folder in sorted(by_folder, key=lambda f: (summary_key(f), f)):
        print(paint(f"  {folder}/", "bold"))
        for move in by_folder[folder]:
            name = clean(move.source)
            new_name = move.target.rsplit("/", 1)[1]
            if new_name != move.source:
                name += f"  →  {clean(new_name)}"
            if move.note:
                name = f"{name:<{width}}" + paint(clean(move.note), "gray")
            print(f"    {name}")


def show_skipped(plan: Plan, detail: bool) -> None:
    if not plan.skipped:
        return
    reasons = Counter(reason for _, reason in plan.skipped)
    print(f"Se quedan donde están ({len(plan.skipped)}): " + ", ".join(f"{n} {r}" for r, n in reasons.items()))
    if detail:
        for name, reason in plan.skipped:
            print(paint(f"    {clean(name)}  ({reason})", "gray"))


def show_plan(plan: Plan, detail: bool) -> None:
    total = human_size(sum(m.size for m in plan.moves))
    print(f"{plural(len(plan.moves), 'archivo', 'archivos')} para ordenar ({total}):\n")
    if detail:
        print_detail(plan)
    else:
        print_summary(plan)
    if plan.skipped:
        print()
        show_skipped(plan, detail)


def run_undo(folder: Path) -> int:
    run = last_run(folder)
    if not run:
        print(f"No hay nada que deshacer en {clean(str(folder))}.", file=sys.stderr)
        return 1
    done, problems = undo_last(folder)
    when = run_date(run)
    print(f"Deshecho lo que se ordenó el {when:%d/%m/%Y} a las {when:%H:%M}: ", end="")
    print(paint(f"{plural(done, 'archivo ha', 'archivos han')} vuelto a su sitio.", "green"))
    if problems:
        print(paint(f"\nNo se ha podido con {len(problems)}:", "red"))
        for problem in problems:
            print(f"  {clean(problem)}")
    previous = last_run(folder)
    if previous and previous != run:
        before = run_date(previous)
        print(f"\nAntes se había ordenado otra vez (el {before:%d/%m/%Y}). Otro --deshacer lo deshace también.")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # que un nombre raro no tire el programa en Windows
    parser = argparse.ArgumentParser(
        prog="ordena",
        description="Ordena los archivos sueltos de una carpeta (por defecto, Descargas) en subcarpetas por "
        "tipo, las fotos por la fecha en que se hicieron y los duplicados aparte. Sin --aplicar "
        "solo enseña lo que haría.",
    )
    parser.add_argument("carpeta", nargs="?", help="la carpeta a ordenar (si no se pone, Descargas)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--aplicar", action="store_true", help="ordenarla de verdad")
    action.add_argument("--deshacer", action="store_true", help="dejarla como estaba antes de la última vez")
    action.add_argument("--demo", action="store_true", help="crear una carpeta de ejemplo para probar")
    parser.add_argument("--detalle", action="store_true", help="enseñar adónde va cada archivo")
    parser.add_argument("--sin-fechas", action="store_true", help="no separar las fotos y vídeos por fecha")
    parser.add_argument("--sin-duplicados", action="store_true", help="no buscar archivos repetidos")
    parser.add_argument("--version", action="version", version=f"ordena {__version__}")
    args = parser.parse_args(argv)
    if args.demo and args.carpeta:
        parser.error("--demo crea su propia carpeta, no hace falta decirle ninguna")

    try:
        if args.demo:
            return run_demo()
        folder = Path(args.carpeta).expanduser() if args.carpeta else downloads_folder()
        if not folder.is_dir():
            print(f"No existe la carpeta {clean(str(folder))}.", file=sys.stderr)
            return 2
        folder = folder.resolve()
        reason = refuse_reason(folder)
        if reason:
            print(f"No ordeno {clean(str(folder))}: {reason}.", file=sys.stderr)
            return 2
        return run_undo(folder) if args.deshacer else run_order(folder, args)
    except BrokenPipeError:
        # `ordena | head`: el otro lado ya no quiere leer más, no es un error. Se manda el resto
        # a la nada para que Python no vuelva a quejarse al cerrar.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except OSError as exc:
        # Sin permiso para leer la carpeta o para escribir el historial, un disco que se desconecta...
        where = f" ({clean(str(exc.filename))})" if exc.filename else ""
        print(f"No se puede seguir: {exc.strerror or exc}{where}.", file=sys.stderr)
        return 1


def run_demo() -> int:
    folder = demo.create()
    print(f"He creado una carpeta de prueba con {len(demo.FILES)} archivos, como unas Descargas cualquiera:")
    print(f"  {clean(str(folder))}\n")
    show_plan(build_plan(folder), detail=True)
    print("\nPruébalo con ella, no pasa nada:")
    print(f"  {command(str(folder), '--aplicar')}")
    print(f"  {command(str(folder), '--deshacer')}")
    return 0


def run_order(folder: Path, args: argparse.Namespace) -> int:
    print(paint(f"Carpeta: {clean(str(folder))}", "bold"))
    plan = build_plan(folder, by_date=not args.sin_fechas, duplicates=not args.sin_duplicados)
    if not plan.moves:
        print("No hay nada que ordenar.")
        show_skipped(plan, args.detalle)
        return 0
    show_plan(plan, args.detalle)

    options = ["--sin-fechas" if args.sin_fechas else "", "--sin-duplicados" if args.sin_duplicados else ""]
    if not args.aplicar:
        print("\nEsto es solo el plan: no se ha movido nada.")
        if not args.detalle:
            print(f"Para ver adónde va cada archivo:  {command(args.carpeta, '--detalle', *options)}")
        print(f"Para ordenarla de verdad:         {command(args.carpeta, '--aplicar', *options)}")
        return 0

    done, problems = apply_plan(plan)
    print(paint(f"\nHecho: {plural(done, 'archivo movido', 'archivos movidos')}.", "green"), end=" ")
    print(f"Queda apuntado en {JOURNAL}; si no te gusta cómo ha quedado:")
    print(f"  {command(args.carpeta, '--deshacer')}")
    if problems:
        print(paint(f"\nNo se ha podido mover {len(problems)}:", "red"))
        for problem in problems:
            print(f"  {clean(problem)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
