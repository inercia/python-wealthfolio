# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "python-wealthfolio @ git+https://github.com/inercia/python-wealthfolio.git@6fcc2a2e94297fdb77b1f97829c675680499af39",
# ]
# ///
"""Run the pinned standalone CLI with uv-managed dependencies."""

from os import environ

from wealthfolio.cli import build_parser


def main():
    """Dispatch library commands without the console entry point's .env loading."""
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(1)
    missing = [
        name for name in ("WEALTHFOLIO_REST_URL", "WEALTHFOLIO_PASSWORD")
        if not environ.get(name, "").strip()
    ]
    if missing:
        parser.error("Set required environment variables: " + ", ".join(missing))
    args.func(args)


if __name__ == "__main__":
    main()
