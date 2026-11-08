#!/usr/bin/env bash
# Render docs/design_card.md to the one-page docs/design_card.pdf (Letter) with pandoc + headless Chrome.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
pandoc docs/design_card.md -s --metadata title="Design card" -c "$PWD/scripts/design_card.css" -o "$tmp/card.html"
sed -i '' 's#<header id="title-block-header">.*</header>##; /<h1 class="title">/d' "$tmp/card.html"
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$PWD/docs/design_card.pdf" "file://$tmp/card.html" 2>/dev/null
pages=$(python3 -c "import re,sys;d=open('docs/design_card.pdf','rb').read();print(len(re.findall(rb'/Type\s*/Page[^s]', d)))")
echo "docs/design_card.pdf: $pages page(s)"; [ "$pages" = "1" ] || { echo "must be one page" >&2; exit 1; }
