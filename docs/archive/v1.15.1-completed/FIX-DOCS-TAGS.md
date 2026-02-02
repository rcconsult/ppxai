# Fix Documentation Tag Reversal

## Problem

The documentation site has reversed content:
- `1.15.0` version shows dev content
- `dev` version shows 1.15.0 content

## Root Cause

**Incorrect deployments:**
- `1.15.0` deployed from commit `919e924` (BEFORE the v1.15.0 tag)
- `dev` deployed from commit `e362546` (AFTER the v1.15.0 tag)
- Actual v1.15.0 tag points to `a607df8`

**Timeline:**
```
919e924 - docs: mark release plans complete ← 1.15.0 deployed (WRONG)
   ↓
a607df8 - fix(pyinstaller): hidden imports ← v1.15.0 TAG (CORRECT)
   ↓
e362546 - fix: remove dev badge         ← dev deployed (WRONG)
```

## Solution Options

### Option 1: Run Script Locally

```bash
chmod +x fix-docs-tags.sh
./fix-docs-tags.sh
```

This will:
1. Checkout v1.15.0 tag
2. Deploy 1.15.0 docs from the correct commit
3. Checkout master
4. Deploy dev docs from current master

### Option 2: Manual GitHub Actions Workflow Dispatch

1. Go to: https://github.com/rcconsult/ppxai/actions/workflows/docs.yml
2. Click "Run workflow"
3. Deploy 1.15.0:
   - Branch: `refs/tags/v1.15.0`
   - Version: `1.15.0`
4. Wait for completion
5. Deploy dev:
   - Branch: `master`
   - Version: (leave empty, will default to dev)

### Option 3: Manual Commands

```bash
# Install dependencies
pip install mkdocs-material mike

# Fix 1.15.0
git checkout v1.15.0
mike deploy --push --update-aliases 1.15.0 latest
mike set-default --push latest

# Fix dev
git checkout master
git pull origin master
mike deploy --push dev

# Return to feature branch
git checkout feature/1-15-1
```

## Verification

After deploying, verify at:
- https://rcconsult.github.io/ppxai/1.15.0/ (should show v1.15.0 content)
- https://rcconsult.github.io/ppxai/dev/ (should show latest master content)

Wait 2-3 minutes for GitHub Pages to update after deployment.

## Prevention

To prevent this in the future:

1. **Always tag from master branch**
   ```bash
   git checkout master
   git tag v1.x.x
   git push origin v1.x.x
   ```

2. **Deploy tags via GitHub Actions**
   - Pushing a tag automatically triggers `.github/workflows/docs.yml`
   - Don't manually deploy tagged versions

3. **Verify deployment**
   - Check `versions.json` in gh-pages branch
   - Verify site content matches tag commit

## Current Deployment Log (gh-pages)

```
fe5120f - Deployed e362546 to dev (WRONG - should be from master HEAD)
5170e1d - Deployed 919e924 to 1.15.0 (WRONG - should be from a607df8)
e844f53 - Deployed 919e924 to dev
```

After fix should show:
```
XXXXXXX - Deployed <master-head> to dev (NEW)
XXXXXXX - Deployed a607df8 to 1.15.0 (NEW)
```
