#!/usr/bin/env bash
#
# profile.sh — resolve the project profile (L2) for the repo we are standing in.
#
# Sourced by `codex-audit`. Never executed directly. Defines only functions and
# readonly defaults, so sourcing it has no side effects.
#
# Resolution order (docs/design/2026-09-cross-review-loop.md §2.1, as decided in §13):
#   1. <worktree root>/docs/ai-profile.md      — the branch's own copy, if it has one
#   2. <main checkout root>/docs/ai-profile.md — for worktrees branched before it existed
#   3. ~/.config/ai-workflow/projects/<key>.md — repos where workflow files can't be committed
#   4. none → documented defaults below, and the caller offers once to create one
#
# <key> is the basename of the MAIN checkout, resolved through `git-common-dir`. It is
# deliberately not the worktree path: a repository's directory name and the name its worktrees
# are filed under can differ (a product renamed, a repo cloned under another name), and every
# checkout of one repository must resolve to one profile.
#
# This file is L1. It must never name a project, path, command, language or domain.

# --- defaults, all overridable by the profile ------------------------------
readonly PROFILE_DEFAULT_ARTIFACTS="docs/specs"
readonly PROFILE_DEFAULT_GATES="1b,2b"

# Sending an artifact to Codex sends it to a different provider. There is no safe default
# for that: a repo with no profile is exactly the case where nobody has decided whether this
# code may leave, and it is the likely shape of a client or employer repo you just cloned.
# So the default is neither yes nor no but `unset`, which the wrapper treats as "not yet
# authorized" — it records a skip and asks once, rather than reviewing first and asking later.
# Before the wrapper was allowlisted, the per-call Bash prompt was the thing standing here;
# allowlisting it removed that beat, so the default has to hold the line instead.
readonly PROFILE_DEFAULT_CODEX_REVIEWER="unset"
readonly PROFILE_DEFAULT_COMMANDS_REF="AGENTS.md"
readonly PROFILE_DEFAULT_LANGUAGE="en"

# Where out-of-repo profiles live. Deliberately NOT readonly: the tests relocate it, and so
# can anyone who keeps their config elsewhere. Honours XDG_CONFIG_HOME.
: "${PROFILE_CONFIG_HOME:=${XDG_CONFIG_HOME:-$HOME/.config}/ai-workflow/projects}"

readonly PROFILE_DEFAULT_CALIBRATION="No project profile was found, so this review runs on defaults.

Calibrate conservatively: assume a small team, a codebase in active development, and no
information about scale, deployment risk or which areas are genuinely high-stakes. Because
none of that is known, prefer reporting a concrete failure path you can evidence over
inferring severity from assumptions about the project."

# --- repository geometry ---------------------------------------------------

# The root of the working tree we are standing in (a worktree, or the main checkout).
profile_worktree_root() {
  git rev-parse --show-toplevel 2>/dev/null
}

# The root of the MAIN checkout, even when called from inside a worktree.
profile_main_root() {
  local common
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  [[ -n "$common" ]] || return 1
  dirname "$common"
}

# The profile key: the main checkout's directory name.
profile_key() {
  local main
  main="$(profile_main_root)" || return 1
  basename "$main"
}

# --- profile file ----------------------------------------------------------

# Print the path of the profile in effect, or nothing if there is none.
profile_path() {
  local worktree main key
  worktree="$(profile_worktree_root || true)"
  main="$(profile_main_root || true)"
  key="$(profile_key || true)"

  if [[ -n "$worktree" && -f "$worktree/docs/ai-profile.md" ]]; then
    echo "$worktree/docs/ai-profile.md"; return 0
  fi
  if [[ -n "$main" && -f "$main/docs/ai-profile.md" ]]; then
    echo "$main/docs/ai-profile.md"; return 0
  fi
  if [[ -n "$key" && -f "$PROFILE_CONFIG_HOME/$key.md" ]]; then
    echo "$PROFILE_CONFIG_HOME/$key.md"; return 0
  fi
  return 1
}

# Read one `key: value` field from the profile's frontmatter.
#   profile_get <key> <default>
# Frontmatter is the block between the first two `---` lines. Values are trimmed and may
# carry a trailing `# comment`. A key that is absent, empty, or in a profile that does not
# exist yields the default.
profile_get() {
  local key="$1" default="$2" file value
  file="$(profile_path)" || { echo "$default"; return 0; }

  value="$(awk -v k="$key" '
    NR == 1 && $0 != "---" { exit }
    NR == 1 { infm = 1; next }
    infm && $0 == "---" { exit }
    infm {
      i = index($0, ":")
      if (i == 0) next
      cur = substr($0, 1, i - 1)
      gsub(/^[ \t]+|[ \t]+$/, "", cur)
      if (cur != k) next
      v = substr($0, i + 1)
      sub(/[ \t]+#.*$/, "", v)
      gsub(/^[ \t]+|[ \t]+$/, "", v)
      print v
      exit
    }
  ' "$file")"

  [[ -n "$value" ]] && echo "$value" || echo "$default"
}

# Print the calibration block: everything under the `## Calibration` heading, up to the next
# `## ` heading or end of file. Falls back to the default calibration text.
profile_calibration() {
  local file body
  file="$(profile_path)" || { echo "$PROFILE_DEFAULT_CALIBRATION"; return 0; }

  # HTML comments are stripped. profile.template.md ships a Calibration section whose entire
  # body is a comment explaining how to write one; a profile copied from it but never filled
  # in would otherwise send those authoring instructions to the reviewer as the project
  # context — "calibrate everything to it: <a note telling you how to write this section>".
  # Silently degrading every review is worse than falling back to the documented default.
  body="$(awk '
    /^## +Calibration[ \t]*$/ { grab = 1; next }
    grab && /^## / { exit }
    !grab { next }
    /<!--/ { inc = 1 }
    !inc { print }
    /-->/ { inc = 0 }
  ' "$file")"

  # Trim leading and trailing blank lines.
  body="$(printf '%s\n' "$body" | sed -e '/./,$!d' | sed -e ':a' -e '/^\n*$/{$d;N;ba' -e '}')"

  [[ -n "$body" ]] && printf '%s\n' "$body" || printf '%s\n' "$PROFILE_DEFAULT_CALIBRATION"
}

# --- derived settings ------------------------------------------------------

# Absolute path of the artifacts directory (specs, plans). Ledgers live in .git/codex-audit/.
# A relative `artifacts` resolves against the WORKTREE root, because artifacts are written on
# the branch. An absolute or ~-prefixed one is used as given — the external case, for repos
# where nothing may be committed.
profile_artifacts_dir() {
  local setting worktree
  setting="$(profile_get artifacts "$PROFILE_DEFAULT_ARTIFACTS")"
  case "$setting" in
    "~"/*) echo "$HOME/${setting#"~/"}" ;;
    /*)    echo "$setting" ;;
    *)
      worktree="$(profile_worktree_root)" || return 1
      echo "$worktree/$setting"
      ;;
  esac
}

profile_is_external() {
  case "$(profile_get artifacts "$PROFILE_DEFAULT_ARTIFACTS")" in
    "~"/*|/*) return 0 ;;
    *)        return 1 ;;
  esac
}

# Has anyone decided whether Codex may review this project? Prints yes | no | unset.
# `unset` is not a synonym for `no`: no is a decision, unset means nobody has made one, and
# the two produce different messages so the caller can offer to create a profile.
profile_codex_consent() {
  case "$(profile_get codex_reviewer "$PROFILE_DEFAULT_CODEX_REVIEWER")" in
    yes) echo yes ;;
    no)  echo no ;;
    *)   echo unset ;;
  esac
}

# Is Codex allowed to review this project at all?
profile_codex_allowed() {
  [[ "$(profile_codex_consent)" == "yes" ]]
}

# Out-of-repo profiles are addressed by the main checkout's basename, which is not unique:
# two unrelated client repositories can easily share a generic directory name, and would share
# one profile — including its `codex_reviewer: yes`. An out-of-repo profile must therefore
# carry a `repo_identity` naming the repository it belongs to, and the wrapper refuses to use
# one that does not match. In-repo profiles need none: they travel with the repository.
#
# Prints the identity of the repo we are standing in: the origin remote if there is one,
# otherwise the absolute path of the main checkout.
profile_repo_identity() {
  local url
  url="$(git remote get-url origin 2>/dev/null || true)"
  if [[ -n "$url" ]]; then
    # Normalise the spellings of the same remote: scheme, userinfo, .git suffix, trailing /.
    url="${url%.git}"; url="${url%/}"
    url="${url#git@}"; url="${url#https://}"; url="${url#http://}"; url="${url#ssh://}"
    url="${url/://}"
    echo "$url"
  else
    profile_canon_path "$(profile_main_root)"
  fi
}

# Resolve a path to its physical form. Without this, the same directory compares unequal to
# itself across the symlinks macOS puts in front of /var and /tmp, so a correct repo_identity
# reads as a mismatch. A path that does not exist is returned unchanged.
profile_canon_path() {
  local p="$1"
  [[ -d "$p" ]] || { echo "$p"; return 0; }
  ( cd "$p" 2>/dev/null && pwd -P ) || echo "$p"
}

# Is the profile in effect an out-of-repo one?
profile_is_out_of_repo() {
  local file; file="$(profile_path)" || return 1
  [[ "$file" == "$PROFILE_CONFIG_HOME/"* ]]
}

# Is <gate> enabled for this project?
profile_gate_enabled() {
  local gate="$1" gates
  gates="$(profile_get gates "$PROFILE_DEFAULT_GATES")"
  [[ "$gates" == "none" ]] && return 1
  [[ ",$gates," == *",$gate,"* ]]
}
