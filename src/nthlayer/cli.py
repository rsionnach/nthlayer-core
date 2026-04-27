"""NthLayer core CLI."""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="NthLayer core")
    parser.add_argument("-V", "--version", action="version", version="%(prog)s 1.5.0a1")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Start the core HTTP server")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    if args.command == "serve":
        from nthlayer.server import run_server

        run_server(host=args.host, port=args.port)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
