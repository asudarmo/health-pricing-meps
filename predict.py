"""Price a profile from the command line with the published tables (ML Zoomcamp entry point).

Examples:
    uv run python predict.py --age 40 --region 3 --CANCERDX 1
    uv run python predict.py --profile profile.json

Conditions not given are taken as 0. The tables are read from `outputs/<model-version>/`.
"""

from __future__ import annotations

import argparse
import json
import sys

from health_pricing.rating import ProfileError, load_tariff, rate

CONDITIONS = ["HIBPDX", "CHDDX", "OHRTDX", "CHOLDX", "CANCERDX", "ARTHDX", "ASTHDX"]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Price a customer profile.")
    p.add_argument("--profile", help="JSON file with the profile")
    p.add_argument("--age", type=int)
    p.add_argument("--region", help="1 to 4")
    for condition in CONDITIONS:
        p.add_argument(f"--{condition}", help="0 or 1")
    p.add_argument("--exposure", type=float, default=1.0, help="years of cover")
    p.add_argument("--model-version", default="v1")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.profile:
        with open(args.profile, encoding="utf-8") as handle:
            profile = json.load(handle)
    else:
        profile = {"age": args.age, "region": args.region}
        profile.update({c: getattr(args, c) or "0" for c in CONDITIONS})
        profile = {k: v for k, v in profile.items() if v is not None}
    try:
        result = rate(
            profile,
            args.model_version,
            tariff=load_tariff(args.model_version),
            exposure=args.exposure,
        )
    except (ProfileError, FileNotFoundError) as error:
        print(f"Cannot price this profile: {error}", file=sys.stderr)
        return 2
    if args.json:
        out = {k: v for k, v in result.items() if k != "breakdown"}
        out["breakdown"] = result["breakdown"].to_dict("records")
        print(json.dumps(out, indent=2))
        return 0
    print(f"Model version {result['model_version']}, exposure {result['exposure']} years")
    print(result["breakdown"].to_string(index=False))
    print(f"Premium (dollars): {result['premium']:.2f}")
    if "premium_illustrative_gbp" in result:
        print(f"{result['illustrative_label']}: {result['premium_illustrative_gbp']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
