from pathlib import Path
from shutil import copytree, rmtree

from app import app


ROUTES = {
    "/": "index.html",
    "/campaigns": "campaigns/index.html",
    "/campaign/1": "campaign/1/index.html",
    "/campaign/2": "campaign/2/index.html",
    "/campaign/3": "campaign/3/index.html",
    "/login": "login/index.html",
    "/register": "register/index.html",
    "/dashboard": "dashboard/index.html",
}


def build_static_site():
    output_dir = Path("netlify-site")
    if output_dir.exists():
        rmtree(output_dir)

    output_dir.mkdir()
    copytree("static", output_dir / "static")

    with app.test_client() as client:
        for route, target in ROUTES.items():
            response = client.get(route)
            if response.status_code >= 400:
                raise RuntimeError(f"Could not render {route}: {response.status_code}")
            target_path = output_dir / target
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(response.data)

    (output_dir / "_redirects").write_text(
        "/campaigns /campaigns/index.html 200\n"
        "/campaign/1 /campaign/1/index.html 200\n"
        "/campaign/2 /campaign/2/index.html 200\n"
        "/campaign/3 /campaign/3/index.html 200\n"
        "/login /login/index.html 200\n"
        "/register /register/index.html 200\n"
        "/dashboard /dashboard/index.html 200\n",
        encoding="utf-8",
    )

    print(f"Static Netlify site created at: {output_dir.resolve()}")


if __name__ == "__main__":
    build_static_site()
