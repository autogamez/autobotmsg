from aiohttp import web
import threading

def keep_alive():
    def run():
        app = web.Application()
        app.router.add_get("/", lambda r: web.Response(text="OK"))
        web.run_app(
            app,
            host="0.0.0.0",
            port=10000,
            handle_signals=False  # ⭐ ตัวนี้แหละสำคัญ
        )

    t = threading.Thread(target=run, daemon=True)
    t.start()

