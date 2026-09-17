"""WSGI development entry point; production uses gunicorn amnezia_panel:create_app()."""
from . import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
