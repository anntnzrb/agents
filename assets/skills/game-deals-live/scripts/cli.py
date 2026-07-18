# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Cross-platform CLI for live game-deal evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "lib"))

from game_deals.env import load_environment  # noqa: E402
from game_deals.errors import GameDealsError  # noqa: E402
from game_deals.schema import OUTPUT_SCHEMA, llm_projection  # noqa: E402
from game_deals.service import GameDealsService, ServiceResult  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Build the public command grammar."""
    parser = argparse.ArgumentParser(
        prog="game-deals-live",
        description="Resolve PC game identities and compare live deal evidence.",
    )
    _add_output_options(parser)
    parser.add_argument(
        "--schema",
        action="store_true",
        help="print the output JSON Schema and exit",
    )
    commands = parser.add_subparsers(dest="command")

    lookup = commands.add_parser("lookup", help="find, normalize, and rank offers")
    lookup.add_argument(
        "query",
        nargs="?",
        help="title, Steam URL, or app/sub/bundle ID",
    )
    explicit_id = lookup.add_mutually_exclusive_group()
    explicit_id.add_argument("--steam-app-id", help="exact Steam app ID")
    explicit_id.add_argument("--steam-sub-id", help="exact Steam package/sub ID")
    explicit_id.add_argument("--steam-bundle-id", help="exact Steam bundle ID")
    lookup.add_argument(
        "--country",
        default="US",
        help="two-letter market code (default: US)",
    )
    lookup.add_argument(
        "--currency",
        default="USD",
        help="three-letter output currency (default: USD)",
    )
    lookup.add_argument(
        "--top",
        type=int,
        default=5,
        help="number of ranked offers (default: 5)",
    )
    lookup.add_argument(
        "--include-itad",
        action="store_true",
        help="query ITAD; requires ITAD_API_KEY",
    )
    _add_output_options(lookup, suppress_defaults=True)

    provider = commands.add_parser("provider", help="call a provider explicitly")
    providers = provider.add_subparsers(dest="provider", required=True)
    gg = providers.add_parser("gg", help="fetch GG Deals prices and bundle history")
    gg.add_argument(
        "--kind",
        "--type",
        choices=("app", "sub", "bundle"),
        default="app",
        dest="steam_type",
        help="Steam identifier kind (default: app; --type is an alias)",
    )
    gg.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="one to 100 Steam IDs; commas accepted",
    )
    gg.add_argument("--region", default="us", help="GG Deals region (default: us)")
    mode = gg.add_mutually_exclusive_group()
    mode.add_argument("--prices-only", action="store_true", help="skip bundle history")
    mode.add_argument("--bundles-only", action="store_true", help="skip prices")
    gg.add_argument("--top", type=int, default=5, help="number of ranked price entries")
    _add_output_options(gg, suppress_defaults=True)

    stores = commands.add_parser("stores", help="list CheapShark stores")
    _add_output_options(stores, suppress_defaults=True)
    return parser


def _add_output_options(
    parser: argparse.ArgumentParser,
    *,
    suppress_defaults: bool = False,
) -> None:
    group = parser.add_mutually_exclusive_group()
    default = argparse.SUPPRESS if suppress_defaults else False
    group.add_argument(
        "--json",
        action="store_true",
        default=default,
        help="print full machine JSON",
    )
    group.add_argument(
        "--llm-json",
        action="store_true",
        default=default,
        help="print compact normalized JSON",
    )


def main(argv: list[str] | None = None) -> int:
    """Execute one command and preserve documented exit codes."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.json and args.llm_json:
        parser.error("--json and --llm-json are mutually exclusive")
    if args.schema:
        print(json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not args.command:
        parser.error("a command is required unless --schema is used")

    env = load_environment(skill_dir=SKILL_DIR)
    service = GameDealsService(env=env)
    try:
        if args.command == "lookup":
            explicit_steam = next(
                (
                    {"type": kind, "id": value}
                    for kind, value in (
                        ("app", args.steam_app_id),
                        ("sub", args.steam_sub_id),
                        ("bundle", args.steam_bundle_id),
                    )
                    if value is not None
                ),
                None,
            )
            result = service.lookup(
                args.query,
                country=args.country,
                currency=args.currency,
                top=args.top,
                include_itad=args.include_itad,
                explicit_steam=explicit_steam,
            )
        elif args.command == "provider" and args.provider == "gg":
            result = service.provider_gg(
                steam_type=args.steam_type,
                ids=args.ids,
                region=args.region,
                prices=not args.bundles_only,
                bundles=not args.prices_only,
                top=args.top,
            )
        elif args.command == "stores":
            result = service.stores()
        else:
            parser.error("unsupported command")
    except GameDealsError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code

    _render(result, json_mode=args.json, llm_mode=args.llm_json)
    return result.exit_code


def _render(result: ServiceResult, *, json_mode: bool, llm_mode: bool) -> None:
    payload = llm_projection(result.payload) if llm_mode else result.payload
    if json_mode or llm_mode:
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=None if llm_mode else 2,
                sort_keys=True,
            ),
        )
        return
    _render_human(payload)


def _render_human(payload: dict[str, Any]) -> None:
    command = payload["command"]
    if command == "stores":
        stores = payload.get("stores", [])
        print(f"Stores: {len(stores)}")
        for store in stores:
            state = "active" if store.get("active") else "inactive"
            print(f"- {store.get('id')}: {store.get('name')} ({state})")
        return

    identity = payload.get("identity")
    if identity:
        print(
            f"Game: {identity.get('canonical_title') or payload.get('query')} [{identity.get('match_status')}]",
        )
    print(
        f"Offers: {len(payload.get('offers', []))}; bundle history: {len(payload.get('bundle_history', []))}",
    )
    rankings = payload.get("rankings", {}).get("overall", [])
    for item in rankings:
        offer = payload["offers"][item["offer_index"]]
        price = offer["price"]
        risks = f" | risks: {', '.join(item['risk_labels'])}" if item.get("risk_labels") else ""
        print(
            f"{item['rank']}. {offer.get('store')} — {price['amount']:.2f} {price['currency']}"
            f" [{offer.get('acquisition_type')}]{risks}",
        )
    for warning in payload.get("warnings", []):
        print(f"warning: {warning['message']}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
