#!/usr/bin/env bash
# Grep-based check for secrets and account-specific values. Release-blocking: run it
# before every push (the repo will be public).
#
#   scripts/check_secrets.sh             # files in the work tree (tracked + untracked, not ignored)
#   scripts/check_secrets.sh --history   # also every commit diff, message, and author email
#
# Exit code 0 = clean, 1 = findings. Findings print as file:line:text.
# Placeholders such as <account region> or <path/to/private_key.p8> do not match.

set -u
cd "$(git rev-parse --show-toplevel)" || exit 2
GREP=/usr/bin/grep

PATTERNS=(
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'                    # private key material
  '[A-Za-z0-9-]+\.snowflakecomputing\.com'                # account host names
  '\b[A-Z]{2}[0-9]{5}\b'                                  # account locators (two letters + five digits)
  '\b[a-z]{2}-(central|east|west|north|south|northeast|northwest|southeast|southwest)-[0-9]\b'  # cloud region ids
  '\b(AWS|AZURE|GCP)_[A-Z]+_[A-Z]+(_[A-Z]+)?_[0-9]\b'     # Snowflake region names
  '/(Users|home)/[A-Za-z0-9._-]+'                         # local home paths
  '~/\.snowflake'                                         # local key folder
  '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}'  # email addresses
  '(SNOWFLAKE_ACCOUNT|SNOWFLAKE_PRIVATE_KEY_PASSWORD|SNOWFLAKE_JWT|SNOWFLAKE_PAT)=[^[:space:]<#]+'  # filled credentials
)
ALLOW='noreply@anthropic\.com|users\.noreply\.github\.com|@example\.(com|org)'
SELF='scripts/check_secrets.sh'

ARGS=()
for p in "${PATTERNS[@]}"; do ARGS+=(-e "$p"); done
status=0

report() {  # $1 = heading; stdin = findings
  local found
  found=$($GREP -vE "$ALLOW" || true)
  if [ -n "$found" ]; then
    echo "== $1"
    echo "$found"
    status=1
  fi
}

# 1. Files that must never be in the repo.
report "forbidden files present (tracked or not ignored)" < <(
  git ls-files -co --exclude-standard \
    | $GREP -E '(^|/)\.env$|^outputs/|^materials/|^\.venv/|\.(p8|pem|pub)$|(^|/)rsa_key')

# 2. Content of every file in the work tree that git would see.
report "secrets or account-specific values in files" < <(
  git ls-files -co --exclude-standard -z \
    | $GREP -zv "^$SELF\$" \
    | xargs -0 $GREP -nIE "${ARGS[@]}" 2>/dev/null)

# 3. History: added lines and messages of every commit, plus author/committer emails.
if [ "${1:-}" = "--history" ] && git rev-parse --verify -q HEAD >/dev/null; then
  # Keep commit headers, message lines, and added lines; skip removed and context lines.
  report "secrets or account-specific values in history" < <(
    git log -p --all --format='commit %H%n%B' -- . ":(exclude)$SELF" \
      | $GREP -vE '^(-| |@@|diff --git|index )' \
      | sed 's/^+//' \
      | $GREP -nIE "${ARGS[@]}")
  # Allowed: noreply addresses and the repo owner's own git email (public by choice,
  # 2026-11-04). Read from git config so the address is not written into the repo.
  OWNER=$(git config user.email | sed 's/[.[\*^$+?(){}|]/\\&/g')
  COMMIT_ALLOW="$ALLOW${OWNER:+|^$OWNER\$}"
  report "commit emails that are not allowed (public on push)" < <(
    git log --all --format='%ae%n%ce' | sort -u | $GREP -vE "$COMMIT_ALLOW")
fi

if [ $status -eq 0 ]; then echo "check_secrets: clean"; fi
exit $status
