#!/bin/bash
# Fix documentation tag reversal
#
# Problem: 1.15.0 docs show dev content and dev docs show 1.15.0 content
# Solution: Redeploy from correct commits

set -e

echo "Fixing documentation tag reversal..."
echo ""

# Configure git
git config user.name "github-actions[bot]" || git config user.name "$(git config user.name)"
git config user.email "github-actions[bot]@users.noreply.github.com" || git config user.email "$(git config user.email)"

# Install dependencies if needed
if ! command -v mike &> /dev/null; then
    echo "Installing mike..."
    pip install mkdocs-material mike
fi

# Fetch latest gh-pages
echo "Fetching gh-pages branch..."
git fetch origin gh-pages:gh-pages 2>/dev/null || true

# Step 1: Redeploy 1.15.0 from the actual v1.15.0 tag
echo ""
echo "Step 1: Redeploying 1.15.0 from correct tag (a607df8)..."
git checkout v1.15.0
mike deploy --push --update-aliases 1.15.0 latest
mike set-default --push latest

# Step 2: Redeploy dev from current master
echo ""
echo "Step 2: Redeploying dev from current master..."
git checkout master
git pull origin master
mike deploy --push dev

echo ""
echo "✅ Documentation tags fixed!"
echo ""
echo "Verify at:"
echo "  - https://rcconsult.github.io/ppxai/1.15.0/"
echo "  - https://rcconsult.github.io/ppxai/dev/"
echo ""
echo "Wait 2-3 minutes for GitHub Pages to update."

# Return to original branch
git checkout -
