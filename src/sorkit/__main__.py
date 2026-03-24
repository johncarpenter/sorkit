"""Entry point for `python -m sorkit` and `sorkit` CLI command."""

from sorkit.server import mcp


def main():
    mcp.run()


if __name__ == "__main__":
    main()
