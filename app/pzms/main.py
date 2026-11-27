"""Ponto de entrada: sobe o servidor local e abre a janela do J' PZ MAP STUDIO.
Uso: python -m pzms.main [--browser] [--port N]"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pzms import APP_NAME, __version__  # noqa: E402
from pzms import server  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jpzmapstudio")
    ap.add_argument("--browser", action="store_true", help="abrir no navegador em vez da janela nativa")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PZMS_PORT", "0")))
    ap.add_argument("--no-open", action="store_true", help="so o servidor (testes)")
    ap.add_argument("--resume", action="store_true", help="reabrir o ultimo projeto (usado pelo instalador)")
    a = ap.parse_args(argv)
    app, srv, url = server.serve(a.port)
    from pzms import routes_session
    routes_session.take_resume(app, recent_fallback=a.resume)
    app.handlers["running_clear"] = routes_session.mark_running(srv.server_address[1])
    print(f"{APP_NAME} {__version__} em {url}", flush=True)
    if a.no_open:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    if not a.browser:
        try:
            import webview
            win = webview.create_window(APP_NAME, url, width=1480, height=920, min_size=(980, 640),
                                        background_color="#15171a")
            app.handlers["window"] = win

            def on_closing():
                try:
                    if app.project and app.project.dirty():
                        app.project.save()
                except Exception:              # noqa: BLE001
                    pass
            win.events.closing += on_closing
            webview.start(debug=bool(os.environ.get("PZMS_DEBUG")))
            return 0
        except Exception as e:                 # noqa: BLE001 - sem webview: usa o navegador
            print(f"janela nativa indisponivel ({e}); abrindo no navegador", flush=True)
    import webbrowser
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        if app.project and app.project.dirty():
            app.project.save()
    return 0


if __name__ == "__main__":
    # nao renomear a thread principal: o pywebview exige o nome 'MainThread' (senao cai no navegador)
    sys.exit(main())
