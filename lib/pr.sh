#!/usr/bin/env bash
#
# Pull-request resolution.
#
# A reviewer should only have to name the pull request. Everything the gates
# need — which branch it targets, and which commit it proposes — is looked up
# from the forge, so the reviewer never has to know the base branch or even be
# checked out on the right branch.
#
# Resolution order per provider:
#   1. the provider CLI (gh / az), which knows the true base branch
#   2. a bare 'refs/pull/<id>/head' fetch, with the remote's default branch as
#      the base. This is a fallback, and says so out loud.
#
# Exports: PR_ID, PR_TITLE, PR_URL, PR_BODY, PR_BASE_BRANCH, PR_HEAD_REV,
#          PR_PROVIDER

PR_ID=""
PR_TITLE=""
PR_URL=""
# The description is the author's own statement of what this change delivers.
# The reviewer verifies the branch against it, so an unimplemented promise is
# caught here rather than by whoever trusted the description and merged.
PR_BODY=""
PR_BASE_BRANCH=""
PR_HEAD_REV=""
PR_PROVIDER=""
PR_REMOTE=""
PR_REPO_SLUG=""

# Read one string field out of a JSON document on stdin. Dotted paths only.
pr_json_field() {
  "${PYTHON_CMD[@]}" -c '
import json, sys
document = json.load(sys.stdin)
value = document
for key in sys.argv[1].split("."):
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        value = None
        break
    value = value.get(key)
print(value if isinstance(value, (str, int)) else "")
' "$1" 2>/dev/null
}

pr_pick_remote() {
  local remote
  for remote in upstream origin; do
    git remote get-url "$remote" >/dev/null 2>&1 && { PR_REMOTE="$remote"; return 0; }
  done
  PR_REMOTE="$(git remote 2>/dev/null | head -1)"
  [ -n "$PR_REMOTE" ]
}

# Provider is decided by the remote, or by the host in a pasted pull-request URL.
pr_detect_provider() {
  local url="$1"
  case "$url" in
    *github.com*)                     PR_PROVIDER="github" ;;
    *dev.azure.com*|*visualstudio.com*|*ssh.dev.azure.com*) PR_PROVIDER="azure" ;;
    *) PR_PROVIDER="unknown" ;;
  esac
}

# Accepts a bare number, '#123', or a full pull-request URL from either forge.
pr_parse_reference() {
  local reference="$1"
  case "$reference" in
    '#'*) reference="${reference#\#}" ;;
  esac
  case "$reference" in
    http*|git@*)
      PR_URL="$reference"
      pr_detect_provider "$reference"
      PR_ID="${reference##*/}"
      PR_ID="${PR_ID%%\?*}"
      case "$reference" in
        *github.com/*)
          PR_REPO_SLUG="$(printf '%s' "$reference" |
            sed -n 's#.*github\.com/\([^/]*/[^/]*\)/pull/.*#\1#p')"
          ;;
      esac
      ;;
    *) PR_ID="$reference" ;;
  esac
  case "$PR_ID" in
    ''|*[!0-9]*)
      fail "inhousecode: '--pr $reference' is not a pull-request number or URL."
      return 1
      ;;
  esac
}

pr_fetch_ref() {
  # Fetch a ref into FETCH_HEAD and echo the resolved commit.
  local ref="$1" rev
  git fetch --quiet "$PR_REMOTE" "$ref" 2>/dev/null || return 1
  rev="$(git rev-parse --verify --quiet FETCH_HEAD)" || return 1
  printf '%s\n' "$rev"
}

# The forge told us which commit the PR proposes. If this clone already has it —
# because the branch is checked out, or was fetched earlier — that object is the
# same object, so there is nothing to download. This keeps a local review fast
# and lets it work with no network at all.
pr_head_from_local() {
  local oid="$1" branch="$2" rev
  [ -n "$oid" ] || return 1
  git cat-file -e "$oid^{commit}" 2>/dev/null || return 1

  local origin="local object"
  rev="$(git rev-parse --verify --quiet HEAD)"
  if [ "$rev" = "$oid" ]; then
    origin="checked-out HEAD"
  elif [ -n "$branch" ] &&
      [ "$(git rev-parse --verify --quiet "refs/heads/$branch")" = "$oid" ]; then
    origin="local branch '$branch'"
  fi
  # This function's stdout is captured by the caller, so the log line must not
  # land there — it would be read back as part of the commit id.
  info "inhousecode: PR head ${oid:0:9} is already here ($origin); not fetching." >&2
  printf '%s\n' "$oid"
}

pr_resolve_github() {
  local document args=()
  command -v gh >/dev/null 2>&1 || return 1
  [ -n "$PR_REPO_SLUG" ] && args=(-R "$PR_REPO_SLUG")
  document="$(gh pr view "$PR_ID" "${args[@]}" \
    --json baseRefName,headRefName,headRefOid,title,url,body 2>/dev/null)" || return 1
  [ -n "$document" ] || return 1

  PR_BASE_BRANCH="$(printf '%s' "$document" | pr_json_field baseRefName)"
  PR_TITLE="$(printf '%s' "$document" | pr_json_field title)"
  PR_URL="$(printf '%s' "$document" | pr_json_field url)"
  PR_BODY="$(printf '%s' "$document" | pr_json_field body)"
  local head_oid head_branch
  head_oid="$(printf '%s' "$document" | pr_json_field headRefOid)"
  head_branch="$(printf '%s' "$document" | pr_json_field headRefName)"
  [ -n "$PR_BASE_BRANCH" ] || return 1

  # The pull ref is authoritative and works for forks, where the head branch
  # does not exist on this remote at all.
  PR_HEAD_REV="$(pr_head_from_local "$head_oid" "$head_branch")" ||
    PR_HEAD_REV="$(pr_fetch_ref "refs/pull/$PR_ID/head")" ||
    PR_HEAD_REV="$(pr_fetch_ref "refs/heads/$head_branch")" || return 1
  if [ -n "$head_oid" ] && [ "$head_oid" != "$PR_HEAD_REV" ]; then
    warn "inhousecode: PR head moved during resolution; reviewing ${PR_HEAD_REV:0:9}."
  fi
  git rev-parse --verify --quiet "$PR_BASE_BRANCH^{commit}" >/dev/null ||
    git rev-parse --verify --quiet "$PR_REMOTE/$PR_BASE_BRANCH^{commit}" >/dev/null ||
    git fetch --quiet "$PR_REMOTE" "refs/heads/$PR_BASE_BRANCH" 2>/dev/null || true
  return 0
}

pr_resolve_azure() {
  local document source_ref target_ref merge_commit
  command -v az >/dev/null 2>&1 || return 1
  document="$(az repos pr show --id "$PR_ID" --output json 2>/dev/null)" || return 1
  [ -n "$document" ] || return 1

  source_ref="$(printf '%s' "$document" | pr_json_field sourceRefName)"
  target_ref="$(printf '%s' "$document" | pr_json_field targetRefName)"
  PR_TITLE="$(printf '%s' "$document" | pr_json_field title)"
  PR_BODY="$(printf '%s' "$document" | pr_json_field description)"
  merge_commit="$(printf '%s' "$document" | pr_json_field lastMergeSourceCommit.commitId)"
  [ -n "$source_ref" ] && [ -n "$target_ref" ] || return 1

  PR_BASE_BRANCH="${target_ref#refs/heads/}"
  local source_branch="${source_ref#refs/heads/}"
  PR_HEAD_REV="$(pr_head_from_local "$merge_commit" "$source_branch")" ||
    PR_HEAD_REV="$(pr_fetch_ref "$source_ref")" ||
    PR_HEAD_REV="$(pr_fetch_ref "refs/heads/$source_branch")" || return 1
  if [ -n "$merge_commit" ] && [ "$merge_commit" != "$PR_HEAD_REV" ]; then
    warn "inhousecode: PR head moved during resolution; reviewing ${PR_HEAD_REV:0:9}."
  fi
  git rev-parse --verify --quiet "$PR_BASE_BRANCH^{commit}" >/dev/null ||
    git rev-parse --verify --quiet "$PR_REMOTE/$PR_BASE_BRANCH^{commit}" >/dev/null ||
    git fetch --quiet "$PR_REMOTE" "$target_ref" 2>/dev/null || true
  return 0
}

# No CLI, or the CLI failed. The pull ref alone still identifies the proposed
# commit; the base branch has to be guessed from the remote's default branch,
# which is wrong for any PR that does not target it — hence the warning.
pr_resolve_fallback() {
  local default_branch
  PR_HEAD_REV="$(pr_fetch_ref "refs/pull/$PR_ID/head")" ||
    PR_HEAD_REV="$(pr_fetch_ref "refs/pull/$PR_ID/merge")" || return 1
  default_branch="$(git symbolic-ref --quiet --short "refs/remotes/$PR_REMOTE/HEAD" 2>/dev/null)"
  default_branch="${default_branch#$PR_REMOTE/}"
  [ -n "$default_branch" ] || default_branch="$(git remote show "$PR_REMOTE" 2>/dev/null |
    sed -n 's/.*HEAD branch: //p' | head -1)"
  [ -n "$default_branch" ] || return 1
  PR_BASE_BRANCH="$default_branch"
  warn "inhousecode: could not query the pull request; assuming it targets '$PR_BASE_BRANCH'."
  warn "  If that is wrong, pass the base explicitly: --diff <base-branch>"
  return 0
}

resolve_pull_request() {
  local reference="$1" remote_url
  pr_parse_reference "$reference" || return 1
  pr_pick_remote || {
    fail "inhousecode: this repository has no git remote to resolve PR #$PR_ID from."
    return 1
  }
  remote_url="$(git remote get-url "$PR_REMOTE" 2>/dev/null)"
  [ -n "$PR_PROVIDER" ] || pr_detect_provider "$remote_url"
  [ "$PR_PROVIDER" = "unknown" ] && pr_detect_provider "$remote_url"

  info "inhousecode: resolving PR #$PR_ID from '$PR_REMOTE'..."
  case "$PR_PROVIDER" in
    github) pr_resolve_github || pr_resolve_fallback ;;
    azure)  pr_resolve_azure  || pr_resolve_fallback ;;
    *)      pr_resolve_fallback ;;
  esac || {
    fail "inhousecode: could not resolve PR #$PR_ID."
    case "$PR_PROVIDER" in
      github) fail "  Try: gh auth login   (or pass the base branch with --diff <base>)" ;;
      azure)  fail "  Try: az login && az devops configure --defaults organization=<url> project=<name>" ;;
      *)      fail "  Unrecognized remote host. Use --diff <base-branch> instead." ;;
    esac
    return 1
  }

  # The base branch must be resolvable locally or there is nothing to diff from.
  local base_rev
  base_rev="$(git rev-parse --verify --quiet "$PR_REMOTE/$PR_BASE_BRANCH^{commit}")" ||
    base_rev="$(git rev-parse --verify --quiet "$PR_BASE_BRANCH^{commit}")" || {
      fail "inhousecode: PR #$PR_ID targets '$PR_BASE_BRANCH', which is not in this checkout."
      fail "  Fetch it first: git fetch $PR_REMOTE $PR_BASE_BRANCH"
      return 1
    }
  PR_BASE_REV="$base_rev"
  export PR_ID PR_TITLE PR_URL PR_BODY PR_BASE_BRANCH PR_BASE_REV PR_HEAD_REV
  return 0
}
