"""La ventana de ordena: lo mismo que la línea de órdenes, con botones.

Tkinter viene con Python, así que no hace falta instalar nada más. Lo lento (leer las
fechas de las fotos, calcular los SHA-256 de los duplicados, mover) va en un hilo aparte
para que la ventana no se quede congelada; Tkinter no se puede tocar desde otro hilo, así
que el hilo deja el resultado en una cola y la ventana la mira cada 100 ms.
"""

from __future__ import annotations

import queue
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from . import __version__, demo
from .folders import downloads_folder, open_in_file_manager, refuse_reason
from .organizer import DUPLICATES, Plan, apply_plan, build_plan, last_run, undo_last
from .report import human_size, plural, run_date, summary_key

ICON = Path(__file__).with_name("icon.png")
EXPAND_UP_TO = 80  # con más archivos, las carpetas del plan salen cerradas


class App:
    def __init__(self, root: tk.Tk, folder: Path | None):
        self.root = root
        self.folder: Path | None = None
        self.plan: Plan | None = None
        self.jobs: queue.Queue = queue.Queue()
        self.busy = False
        self.notice = ""  # lo que se ha hecho la última vez, para enseñarlo abajo
        self.last_result: tuple[int, list[str]] = (0, [])
        self.by_date = tk.BooleanVar(value=True)
        self.duplicates = tk.BooleanVar(value=True)

        root.title("ordena")
        root.geometry("860x600")
        root.minsize(620, 420)
        if ICON.exists():
            root.iconphoto(True, tk.PhotoImage(file=str(ICON)))
        self.build()
        root.after(100, self.poll)
        if folder:
            self.open(folder)
        else:
            self.summary.config(text="Elige qué carpeta ordenar con «Cambiar…».")

    # La ventana

    def build(self) -> None:
        root = self.root
        style = ttk.Style(root)
        # En Windows y macOS el tema por defecto ya es el del sistema. En Linux es uno de los
        # noventa; "clam" queda mucho mejor.
        if style.theme_use() == "default" and "clam" in style.theme_names():
            style.theme_use("clam")
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        style.configure("Treeview", rowheight=line + 8)
        menu = tk.Menu(root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Elegir carpeta…", command=self.choose, accelerator="Ctrl+O")
        file_menu.add_command(label="Probar con una carpeta de ejemplo", command=self.open_demo)
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=root.destroy)
        menu.add_cascade(label="Archivo", menu=file_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Acerca de ordena", command=self.about)
        menu.add_cascade(label="Ayuda", menu=help_menu)
        root.config(menu=menu)
        root.bind_all("<Control-o>", lambda _: self.choose())

        top = ttk.Frame(root, padding=(14, 12, 14, 6))
        top.pack(fill="x")
        ttk.Label(top, text="Carpeta:").pack(side="left")
        self.folder_label = ttk.Label(top, text="(ninguna)", font=bold)
        self.folder_label.pack(side="left", padx=(6, 10), fill="x", expand=True)
        ttk.Button(top, text="Cambiar…", command=self.choose).pack(side="right")

        options = ttk.Frame(root, padding=(14, 0, 14, 6))
        options.pack(fill="x")
        ttk.Checkbutton(options, text="Fotos y vídeos por fecha", variable=self.by_date, command=self.refresh).pack(
            side="left"
        )
        ttk.Checkbutton(options, text="Apartar los duplicados", variable=self.duplicates, command=self.refresh).pack(
            side="left", padx=(16, 0)
        )

        self.summary = ttk.Label(root, padding=(14, 4), wraplength=820, justify="left")
        self.summary.pack(fill="x")
        root.bind("<Configure>", lambda e: e.widget is root and self.summary.config(wraplength=max(300, e.width - 40)))

        table = ttk.Frame(root, padding=(14, 0))
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("note",), selectmode="browse")
        self.tree.heading("#0", text="Adónde va cada archivo", anchor="w")
        self.tree.heading("note", text="", anchor="w")
        self.tree.column("#0", width=520, stretch=True)
        self.tree.column("note", width=260, stretch=True)
        self.tree.tag_configure("group", font=bold)
        self.tree.tag_configure("muted", foreground="#6b7280")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        bottom = ttk.Frame(root, padding=(14, 10, 14, 12))
        bottom.pack(fill="x")
        self.undo_button = ttk.Button(bottom, text="Deshacer la última vez", command=self.undo)
        self.undo_button.pack(side="left")
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=100)
        self.status_label = ttk.Label(bottom, foreground="#4b5563")
        self.status_label.pack(side="left", padx=12)
        self.order_button = ttk.Button(bottom, text="Ordenar", command=self.apply, style="Accent.TButton")
        self.order_button.pack(side="right")
        self.open_button = ttk.Button(bottom, text="Abrir la carpeta", command=self.show_folder)
        self.open_button.pack(side="right", padx=(0, 8))
        style.configure("Accent.TButton", font=bold)
        self.update_buttons()

    def update_buttons(self) -> None:
        ready = not self.busy and self.folder is not None
        can_order = ready and self.plan is not None and bool(self.plan.moves)
        self.order_button.state(["!disabled"] if can_order else ["disabled"])
        self.open_button.state(["!disabled"] if ready else ["disabled"])
        run = last_run(self.folder) if ready else None
        if run:
            self.undo_button.config(text=f"Deshacer lo del {run_date(run):%d/%m a las %H:%M}")
            self.undo_button.state(["!disabled"])
        else:
            self.undo_button.config(text="Deshacer la última vez")
            self.undo_button.state(["disabled"])

    def show_plan(self, plan: Plan) -> None:
        self.plan = plan
        self.tree.delete(*self.tree.get_children())
        self.status_label.config(text=self.notice)
        self.notice = ""
        if not plan.moves:
            self.summary.config(text="No hay nada que ordenar.")
        else:
            total = human_size(sum(m.size for m in plan.moves))
            text = f"{plural(len(plan.moves), 'archivo', 'archivos')} para ordenar ({total})."
            if plan.duplicates:
                freed = human_size(sum(m.size for m in plan.duplicates))
                repeated = plural(len(plan.duplicates), "está repetido", "están repetidos")
                text += f" {repeated}: si los borras, liberas {freed}."
            self.summary.config(text=text + " Todavía no se ha movido nada.")

        by_folder: dict[str, list] = {}
        for move in plan.moves:
            by_folder.setdefault(move.folder, []).append(move)
        expand = len(plan.moves) <= EXPAND_UP_TO
        for folder in sorted(by_folder, key=lambda f: (summary_key(f), f)):
            moves = by_folder[folder]
            note = "no se borran: los decides tú" if folder == DUPLICATES else ""
            label = f"{folder}/  ({len(moves)})"
            group = self.tree.insert("", "end", text=label, values=(note,), open=expand, tags=("group",))
            for move in moves:
                name = move.source
                new_name = move.target.rsplit("/", 1)[1]
                if new_name != move.source:
                    name += f"  →  {new_name}"
                self.tree.insert(group, "end", text=name, values=(move.note,))
        if plan.skipped:
            group = self.tree.insert(
                "", "end", text=f"Se quedan donde están  ({len(plan.skipped)})", open=expand, tags=("group", "muted")
            )
            for name, reason in plan.skipped:
                self.tree.insert(group, "end", text=name, values=(reason,), tags=("muted",))
        self.update_buttons()

    # Lo que hacen los botones

    def choose(self) -> None:
        if self.busy:
            return
        start = self.folder or downloads_folder()
        initial = start if start.is_dir() else Path.home()
        chosen = filedialog.askdirectory(parent=self.root, title="¿Qué carpeta ordeno?", initialdir=str(initial))
        if chosen:
            self.open(Path(chosen))

    def open(self, folder: Path) -> None:
        folder = folder.expanduser().resolve()
        if not folder.is_dir():
            messagebox.showerror("ordena", f"No existe la carpeta {folder}.", parent=self.root)
            return
        reason = refuse_reason(folder)
        if reason:
            messagebox.showwarning("ordena", f"No ordeno {folder}: {reason}.", parent=self.root)
            return
        self.folder = folder
        self.folder_label.config(text=str(folder))
        self.refresh()

    def open_demo(self) -> None:
        if self.busy:
            return
        folder = demo.create()
        messagebox.showinfo(
            "Carpeta de ejemplo",
            f"He creado una carpeta de prueba con {len(demo.FILES)} archivos, como unas Descargas cualquiera:\n\n"
            f"{folder}\n\nOrdénala, mira cómo queda y deshazlo: no pasa nada.",
            parent=self.root,
        )
        self.open(folder)

    def refresh(self) -> None:
        if self.folder is None or self.busy:
            return
        folder, by_date, duplicates = self.folder, self.by_date.get(), self.duplicates.get()

        def work():
            return build_plan(folder, by_date=by_date, duplicates=duplicates)

        self.in_background(work, self.show_plan, "Mirando la carpeta…")

    def apply(self, confirm: bool = True) -> None:
        if not self.plan or not self.plan.moves or self.busy:
            return
        question = (
            f"Se van a mover {plural(len(self.plan.moves), 'archivo', 'archivos')} a sus carpetas.\n\n"
            "No se borra nada y se puede deshacer."
        )
        if confirm and not messagebox.askokcancel("Ordenar", question, parent=self.root):
            return
        plan = self.plan
        self.in_background(lambda: apply_plan(plan), lambda result: self.finished(result, "movido"), "Ordenando…")

    def undo(self, confirm: bool = True) -> None:
        if self.folder is None or self.busy:
            return
        run = last_run(self.folder)
        if not run:
            return
        question = f"¿Dejar la carpeta como estaba antes de ordenarla el {run_date(run):%d/%m/%Y a las %H:%M}?"
        if confirm and not messagebox.askokcancel("Deshacer", question, parent=self.root):
            return
        folder = self.folder
        self.in_background(lambda: undo_last(folder), lambda result: self.finished(result, "devuelto"), "Deshaciendo…")

    def finished(self, result: tuple[int, list[str]], verb: str) -> None:
        done, problems = result
        self.last_result = result
        message = f"{plural(done, 'archivo ' + verb, 'archivos ' + verb + 's')}."
        if problems:
            listed = "\n".join(problems[:12]) + ("\n…" if len(problems) > 12 else "")
            warning = f"{message}\n\nNo se ha podido con {len(problems)}:\n{listed}"
            messagebox.showwarning("ordena", warning, parent=self.root)
        self.notice = message
        self.refresh()

    def show_folder(self) -> None:
        if self.folder:
            open_in_file_manager(self.folder)

    def about(self) -> None:
        messagebox.showinfo(
            "Acerca de ordena",
            f"ordena {__version__}\n\nOrdena una carpeta por tipos, las fotos por fecha y los duplicados aparte. "
            "No borra nada y se puede deshacer.\n\nhttps://github.com/espi0207/ordena",
            parent=self.root,
        )

    # Trabajo en segundo plano

    def in_background(self, work, done, message: str) -> None:
        self.busy = True
        self.status_label.config(text=message)
        self.progress.pack(side="left", before=self.status_label)
        self.progress.start(12)
        self.update_buttons()

        def worker():
            try:
                self.jobs.put((done, work(), None))
            except Exception as exc:  # que un error no deje la ventana esperando para siempre
                self.jobs.put((done, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self) -> None:
        try:
            while True:
                done, result, error = self.jobs.get_nowait()
                self.busy = False
                self.progress.stop()
                self.progress.pack_forget()
                if error:
                    self.status_label.config(text="")
                    messagebox.showerror("ordena", f"Algo ha fallado: {error}", parent=self.root)
                    self.update_buttons()
                else:
                    done(result)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def self_check() -> int:
    """Para la CI: abre la ventana con una carpeta de ejemplo, la ordena, lo deshace y
    comprueba que todo vuelve a estar igual, sin que nadie toque nada. Así se sabe que el
    programa instalado funciona de verdad (con Tkinter y todo), no solo que se ha creado."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = demo.create(Path(tmp))
        before = sorted(p.name for p in folder.iterdir())
        root = tk.Tk()
        app = App(root, folder)
        steps = iter(["apply", "undo", "check"])
        outcome = {"code": 1}

        def next_step():
            if app.busy:
                root.after(100, next_step)
                return
            step = next(steps)
            if step == "apply":
                app.apply(confirm=False)
            elif step == "undo":
                app.undo(confirm=False)
            else:
                after = sorted(p.name for p in folder.iterdir())
                outcome["code"] = 0 if after == before and app.last_result[0] == 22 else 1
                root.destroy()
                return
            root.after(300, next_step)

        root.after(500, next_step)
        root.after(60_000, root.destroy)  # por si algo se queda colgado
        root.mainloop()
        return outcome["code"]


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if sys.platform == "win32":
        try:  # sin esto, en pantallas con zoom Windows estira la ventana y se ve borrosa
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    if "--comprobar" in args:
        sys.exit(self_check())
    # Una carpeta como argumento: la que llega desde "Ordenar con ordena" en el menú del Explorador.
    folder = Path(args[0]) if args else downloads_folder()
    root = tk.Tk()
    App(root, folder if folder.is_dir() else None)
    root.mainloop()


if __name__ == "__main__":
    main()
