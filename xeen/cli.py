"""CLI entry point for xeen."""

import argparse
import os
import sys
import webbrowser
import threading
import time


def main():
    parser = argparse.ArgumentParser(
        prog="xeen",
        description="📹 xeen — Screenshot capture → edit → crop → publish",
    )
    sub = parser.add_subparsers(dest="command", help="Dostępne komendy")

    # xeen capture
    cap = sub.add_parser("capture", aliases=["c"], help="Rozpocznij nagrywanie ekranu")
    cap.add_argument("-d", "--duration", type=float, default=10.0,
                     help="Maks. czas nagrywania w sekundach (domyślnie: 10)")
    cap.add_argument("-i", "--interval", type=float, default=1.0,
                     help="Interwał między klatkami w sekundach (domyślnie: 1.0)")
    cap.add_argument("--min-interval", type=float, default=0.5,
                     help="Min. interwał nawet przy zmianach (domyślnie: 0.5)")
    cap.add_argument("--threshold", type=float, default=5.0,
                     help="Próg zmiany ekranu w %% (domyślnie: 5.0)")
    cap.add_argument("-n", "--name", type=str, default=None,
                     help="Nazwa sesji (domyślnie: timestamp)")
    cap.add_argument("--monitor", type=int, default=0,
                     help="Numer monitora (0=wszystkie, 1=pierwszy, ...)")

    # xeen server / xeen (domyślnie)
    srv = sub.add_parser("server", aliases=["s"], help="Uruchom serwer edycji")
    srv.add_argument("-p", "--port", type=int, default=7600, help="Port (domyślnie: 7600)")
    srv.add_argument("--host", type=str, default="127.0.0.1", help="Host (domyślnie: 127.0.0.1)")
    srv.add_argument("--no-browser", action="store_true", help="Nie otwieraj przeglądarki")
    srv.add_argument("--data-dir", type=str, default=None,
                     help="Katalog danych (domyślnie: ~/.xeen)")

    # xeen list
    sub.add_parser("list", aliases=["l"], help="Lista sesji nagrywania")

    args = parser.parse_args()

    # Domyślnie uruchom capture
    if args.command is None:
        args.command = "capture"
        args.duration = 10.0
        args.interval = 1.0
        args.min_interval = 0.5
        args.threshold = 5.0
        args.name = None
        args.monitor = 0

    if args.command in ("capture", "c"):
        run_capture(args)
    elif args.command in ("server", "s"):
        run_server(args)
    elif args.command in ("list", "l"):
        run_list(args)
    else:
        parser.print_help()


def run_capture(args):
    """Uruchom sesję nagrywania."""
    from xeen.capture import CaptureSession

    session = CaptureSession(
        duration=args.duration,
        interval=args.interval,
        min_interval=args.min_interval,
        change_threshold=args.threshold,
        name=args.name,
        monitor=args.monitor,
    )

    print(f"📹 xeen capture")
    print(f"   Czas: {args.duration}s | Interwał: {args.interval}s | Monitor: {args.monitor}")
    print(f"   Naciśnij Ctrl+C aby zakończyć wcześniej\n")

    try:
        session.run()
    except KeyboardInterrupt:
        print("\n⏹  Przerwano")
        session.stop()

    summary = session.summary()
    print(f"\n✅ Sesja: {summary['name']}")
    print(f"   📸 {summary['frame_count']} klatek | {summary['duration']:.1f}s")
    print(f"   📁 {summary['path']}")
    print(f"\n   Uruchom 'xeen' aby edytować w przeglądarce")


def run_server(args):
    """Uruchom serwer WWW."""
    import uvicorn
    from xeen.config import get_data_dir

    data_dir = args.data_dir or get_data_dir()
    os.environ["XEEN_DATA_DIR"] = str(data_dir)

    url = f"http://{args.host}:{args.port}"

    if not args.no_browser:
        def open_browser():
            time.sleep(1.0)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()

    print(f"📹 xeen server → {url}")
    print(f"   Dane: {data_dir}\n")

    uvicorn.run(
        "xeen.server:app",
        host=args.host,
        port=args.port,
        log_level="warning",
    )


def run_list(args):
    """Pokaż listę sesji."""
    from xeen.config import get_data_dir
    from pathlib import Path
    import json

    data_dir = get_data_dir() / "sessions"
    if not data_dir.exists():
        print("Brak sesji. Uruchom 'xeen capture' aby rozpocząć nagrywanie.")
        return

    sessions = sorted(data_dir.iterdir(), reverse=True)
    if not sessions:
        print("Brak sesji.")
        return

    print(f"📋 Sesje ({len(sessions)}):\n")
    for s in sessions[:20]:
        meta_file = s / "session.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
            frames = meta.get("frame_count", "?")
            dur = meta.get("duration", 0)
            print(f"  {s.name:30s}  {frames:>3} klatek  {dur:.1f}s")
        else:
            print(f"  {s.name}")


if __name__ == "__main__":
    main()
