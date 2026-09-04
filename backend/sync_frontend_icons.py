"""Populate Vite's generated public icon directory from packaged templates."""

from fetch_templates import sync_frontend_icons


if __name__ == "__main__":
    copied = sync_frontend_icons()
    print(f"Synced {copied} frontend game icons")
