#!/usr/bin/env bash
#
# Ticket resolution.
#
# The PR description says what the author thinks they built. The ticket says
# what the work was supposed to do in the first place. Feeding both to the
# reviewer lets it verify the change against its ORIGIN, not just the author's
# own summary of it. This is evidence, not a gate: a ticket that cannot be
# fetched (a private tracker, an SSO wall, an unknown host) is dropped with a
# note, exactly as a missing PR description is -- optional inputs never block
# and never bluff (invariant 9).
#
# Depends on pr_json_field from lib/pr.sh for JSON parsing.
#
# Exports: TICKET_ID, TICKET_TITLE, TICKET_URL, TICKET_BODY, TICKET_PROVIDER

TICKET_ID=""
TICKET_TITLE=""
TICKET_URL=""
TICKET_BODY=""
TICKET_PROVIDER=""
TICKET_REPO_SLUG=""

ticket_detect_provider() {
  case "$1" in
    *github.com*)                                         TICKET_PROVIDER="github" ;;
    *dev.azure.com*|*visualstudio.com*)                   TICKET_PROVIDER="azure" ;;
    *atlassian.net*|*/browse/*)                           TICKET_PROVIDER="jira" ;;
    *linear.app*)                                         TICKET_PROVIDER="linear" ;;
    *) TICKET_PROVIDER="unknown" ;;
  esac
}

# Accepts a bare number ('42', '#42') -> GitHub issue on the current repo; a
# GitHub issue URL; or any other tracker URL (routed by host).
ticket_parse_reference() {
  local reference="$1"
  case "$reference" in
    '#'*) reference="${reference#\#}" ;;
  esac
  case "$reference" in
    http*)
      TICKET_URL="$reference"
      ticket_detect_provider "$reference"
      case "$reference" in
        *github.com/*)
          TICKET_ID="${reference##*/}"; TICKET_ID="${TICKET_ID%%\?*}"
          TICKET_REPO_SLUG="$(printf '%s' "$reference" |
            sed -n 's#.*github\.com/\([^/]*/[^/]*\)/issues/.*#\1#p')"
          ;;
        *) TICKET_ID="${reference##*/}"; TICKET_ID="${TICKET_ID%%\?*}" ;;
      esac
      ;;
    *)
      # A bare value: a GitHub issue number, or a tracker key like PROJ-123.
      TICKET_ID="$reference"
      case "$reference" in
        *[!0-9]*) ticket_detect_provider "key:$reference" ;;
        *)        TICKET_PROVIDER="github" ;;
      esac
      ;;
  esac
  [ -n "$TICKET_ID" ]
}

ticket_resolve_github() {
  local document args=()
  command -v gh >/dev/null 2>&1 || return 1
  case "$TICKET_ID" in ''|*[!0-9]*) return 1 ;; esac
  [ -n "$TICKET_REPO_SLUG" ] && args=(-R "$TICKET_REPO_SLUG")
  document="$(gh issue view "$TICKET_ID" "${args[@]}" \
    --json number,title,url,body 2>/dev/null)" || return 1
  [ -n "$document" ] || return 1

  TICKET_TITLE="$(printf '%s' "$document" | pr_json_field title)"
  TICKET_URL="$(printf '%s' "$document" | pr_json_field url)"
  TICKET_BODY="$(printf '%s' "$document" | pr_json_field body)"
  [ -n "$TICKET_BODY" ] || [ -n "$TICKET_TITLE" ]
}

ticket_resolve_azure() {
  local document
  command -v az >/dev/null 2>&1 || return 1
  case "$TICKET_ID" in ''|*[!0-9]*) return 1 ;; esac
  document="$(az boards work-item show --id "$TICKET_ID" --output json 2>/dev/null)" || return 1
  [ -n "$document" ] || return 1
  TICKET_TITLE="$(printf '%s' "$document" | pr_json_field 'fields.System\.Title')"
  TICKET_BODY="$(printf '%s' "$document" | pr_json_field 'fields.System\.Description')"
  [ -n "$TICKET_BODY" ] || [ -n "$TICKET_TITLE" ]
}

# resolve_ticket <reference> -- best-effort. Returns 0 and sets TICKET_BODY on
# success; returns 1 (with a warning, never a failure of the run) when the
# ticket cannot be fetched. The caller treats a 1 as "no ticket supplied".
resolve_ticket() {
  local reference="$1"
  [ -n "$reference" ] || return 1
  resolve_python || return 1

  ticket_parse_reference "$reference" || {
    warn "inhousecode: could not parse --ticket '$reference'; continuing without it."
    return 1
  }

  case "$TICKET_PROVIDER" in
    github) ticket_resolve_github ;;
    azure)  ticket_resolve_azure ;;
    *)      false ;;
  esac || {
    warn "inhousecode: could not fetch ticket '$reference' (${TICKET_PROVIDER:-unknown} tracker). Pass its text with --intent-file to include it."
    TICKET_BODY=""
    return 1
  }
  [ -n "$TICKET_ID" ] || TICKET_ID="$reference"
  return 0
}
