"""Start the HR system:  python run.py   (or: flask run)"""
import os
import socket
import sys

from app import create_app

app = create_app()


def free_port(port):
    """Use the next free port if the requested one is taken."""
    for p in range(port, port + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                if p != port:
                    print(f" * Port {port} is in use, so using port {p} instead")
                return p
    sys.exit(f"No free port found near {port}. Start with PORT=8000 python run.py")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":   # not inside the reloader's child process
        port = free_port(port)
        os.environ["PORT"] = str(port)
    app.run(debug=app.config.get("DEBUG", False), port=port,
            use_reloader=os.environ.get("FLASK_RELOAD", "1") == "1")
