"""NthLayer core CLI."""
import argparse
import sys

from nthlayer_core import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser. Exposed so tests can introspect the surface
    without running ``main``'s side effects (see test_deploying_doc_parity)."""
    parser = argparse.ArgumentParser(description="NthLayer core")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Start the core HTTP server")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "serve":
        from nthlayer_core.server import run_server

        run_server(host=args.host, port=args.port)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
