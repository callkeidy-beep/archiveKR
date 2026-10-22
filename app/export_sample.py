"""Export only synthetic bootstrap data, never DB rows or environment secrets."""
import json
import sys
from pathlib import Path
from app.domain import bootstrap


def main():
    target = Path(sys.argv[1] if len(sys.argv)>1 else 'site-dist/sample.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bootstrap([]), ensure_ascii=False, indent=2) + '\n')
    print(f'Synthetic sample exported: {target}')

if __name__ == '__main__': main()
