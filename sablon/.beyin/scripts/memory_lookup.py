#!/usr/bin/env python3
"""Local vault source lookup; --engine pilot keeps the original policy-only interface."""
import argparse
import json
from pathlib import Path
import authority
import memory_search

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--historical', action='store_true')
    parser.add_argument('--engine', choices=('sources', 'pilot'), default='sources')
    args = parser.parse_args()
    try:
        lookup = authority.lookup if args.engine == 'pilot' else memory_search.lookup
        print(json.dumps(lookup(args.root, args.query, args.historical), ensure_ascii=False))
    except (OSError, ValueError) as error:
        print(json.dumps({'error': type(error).__name__}))
        raise SystemExit(1)
