#!/usr/bin/env bash
#
# install.sh — replicate this Claude Code setup on a Mac by symlinking the
# tracked config in this repo into ~/.claude (the Codex audit profile into
# ~/.codex, the Zed config into ~/.config/zed), and merging the MCP servers
# into ~/.claude.json. Idempotent and safe: existing targets are backed up
# before they are replaced, and re-running makes no further changes.
#
# It never touches your machine-local state (projects/, sessions/, history, etc.)
# or skills installed from other sources — only the paths listed below.

set -euo pipefail

# --- locations -------------------------------------------------------------
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO/claude"
CONFIG_DEST="$HOME/.config/ai-workflow"
DEST="$HOME/.claude"
CLAUDE_JSON="$HOME/.claude.json"
CODEX_SRC="$REPO/codex"
CODEX_DEST="$HOME/.codex"
ZED_SRC="$REPO/zed"
ZED_DEST="$HOME/.config/zed"
SHELL_SRC="$REPO/shell"
SHELL_DEST="$HOME/.config/zsh"
ZSHRC="$HOME/.zshrc"
GIT_IGNORE_DEST="$HOME/.config/git/ignore"
LOCAL_BIN="$HOME/.local/bin"
TS="$(date +%Y%m%d-%H%M%S)"

# Codex: audit.config.toml (the read-only auditor profile used by the feature-workflow skill)
# is linked; config.toml is rendered from config.base.toml (see render_codex_config). Only
# these two files are owned by this repo; the rest of ~/.codex (auth, sessions, caches) is
# machine-local and never touched.
CODEX_FILES=(audit.config.toml)

# codex-audit wrapper linked onto PATH (~/.local/bin). It is the single entry point for the
# feature-workflow Codex gates: codex-audit <1b|2b|6b> [--slug s] [--round 1|2] [--response f].
#
# Only the wrapper is linked. It resolves its own symlink to find the rest of what it needs —
# reviewer-contract.md, prompts/ and lib/profile.sh — inside this repo, so those are edited in
# one place and never copied into ~/.codex.
CODEX_BINS=(codex-audit)

# gate-log, the gate scorecard's recorder, is linked onto PATH like codex-audit. Its source is
# the usage-audit skill's script (analyze.py imports the same module), so it is not in CODEX_BINS,
# whose source directory is fixed to codex/bin.
GATE_LOG_BIN="$SRC/skills/usage-audit/scripts/gate_log.py"

# Zed is the editor I read and review generated code in — it never writes it.
# Only the three config files are owned here; Zed's state, caches, extension
# binaries and conversation history under ~/.config/zed are machine-local and
# never touched. Extensions are not installed by this script: settings.json
# declares them under `auto_install_extensions`, so Zed installs them itself on
# first launch.
ZED_FILES=(settings.json keymap.json tasks.json)

# The test runner behind the three Zed tasks, linked onto PATH like codex-audit.
ZED_BINS=(zed-ruby-test)

# suite-queue serializes the heavy pre-push suites across repos (one Ruby and one
# JS suite at a time); the lefthook configs call it by name, linked onto PATH like
# codex-audit. ship, behind /ship, merges a PR and cleans up its branch and worktree.
# inflight, behind /inflight, lists open PRs and worktrees, stale ones marked.
GIT_BINS=(suite-queue ship inflight)

# Whole paths that are fully owned by this repo: link the entire entry.
#
# `agents` is here for the same reason as `commands`: the directory is owned end to end.
WHOLE=(CLAUDE.md settings.json commands hooks agents)

# Skills are linked individually so skills installed from other sources in
# ~/.claude/skills are left untouched.
#
# Derived from the filesystem so the list cannot drift.
SKILLS=()
for d in "$SRC"/skills/*/; do
  [[ -d "$d" ]] && SKILLS+=("$(basename "$d")")
done



info() { printf '  \033[0;34m•\033[0m %s\n' "$1"; }
ok()   { printf '  \033[0;32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[0;33m!\033[0m %s\n' "$1"; }

# --- prerequisites ---------------------------------------------------------
# Every link below points at $REPO — the checkout this script was run from. Run
# from a worktree (which the worktree rule says all work happens in), the links
# point INTO that worktree and go dangling the moment it is removed after merge.
# Most of that is loud. ~/.config/git/ignore is not: git treats a dangling
# excludes file as no excludes at all, so .zed/ and .ruby-lsp/ would quietly
# become committable in every repo. Warn rather than refuse — installing from a
# worktree is legitimate while testing a branch.
case "$REPO" in
  "$HOME/worktrees"/*)
    printf '  \033[0;33m!\033[0m %s\n' "running from a worktree: ${REPO/#$HOME/~}"
    printf '  \033[0;33m!\033[0m %s\n' "  links will point there and break when it is removed."
    printf '  \033[0;33m!\033[0m %s\n' "  Re-run this from your main checkout after merging."
    echo
    ;;
esac

echo "==> Checking prerequisites"
MISSING=()
check() { if command -v "$1" >/dev/null 2>&1; then ok "$1 ($(command -v "$1"))"; else warn "$1 not found — $2"; MISSING+=("$1"); fi; }
check claude  "install the Claude Code CLI: https://claude.com/claude-code"
check codex   "install the Codex CLI (feature-workflow audit gates): npm i -g @openai/codex"
check zed     "install Zed (code viewer/reviewer): brew install --cask zed"
check node    "install Node (hooks/MCP need it): https://nodejs.org"
check python3 "install Python 3.11+ (the hooks run under it, standard library only)"
# tomllib (codex/render_config.py, scripts/link-baseline.py) needs 3.11; macOS ships 3.9.
if command -v python3 >/dev/null 2>&1 && ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  warn "python3 is older than 3.11 — the Codex config render needs tomllib"
  MISSING+=("python3>=3.11")
fi
check git     "install git"
# A checkout with a root lefthook.yml (the public repo) guards its pushes through lefthook: it
# must be installed and be the repo's pre-push hook, or the pre-push guard silently never runs.
if [[ -f "$REPO/lefthook.yml" ]]; then
  check lefthook "install lefthook (the pre-push guard runs through it): brew install lefthook"
  if command -v lefthook >/dev/null 2>&1; then
    hook="$(git -C "$REPO" rev-parse --git-path hooks/pre-push 2>/dev/null || true)"
    [[ -n "$hook" && "$hook" != /* ]] && hook="$REPO/$hook"
    if [[ -n "$hook" && -f "$hook" ]] && grep -qi lefthook "$hook"; then
      ok "lefthook is installed as the pre-push hook"
    else
      warn "lefthook is not this repo's pre-push hook — run 'lefthook install' in ${REPO/#$HOME/~}"
      MISSING+=("'lefthook install'")
    fi
  fi
fi
# The public pre-push guard and public-text-guard.py fail closed without this pointer, so say so
# here rather than at the first push. Same shape scripts/privacy-check requires: a regular file
# holding one line, the absolute path of an existing file.
pointer="$CONFIG_DEST/extra-scanner"
scanner=""
if [[ -f "$pointer" && ! -L "$pointer" ]]; then
  IFS= read -r scanner < "$pointer" || true
  body="$(cat "$pointer"; printf x)"   # the x keeps trailing newlines: "/a\n\n" is two lines
  [[ "$body" == "${scanner}x" || "$body" == "${scanner}"$'\n'x ]] || scanner=""
fi
if [[ "$scanner" == /* && -f "$scanner" ]]; then
  ok "extra-scanner pointer (~/.config/ai-workflow/extra-scanner)"
else
  warn "extra-scanner not found — ~/.config/ai-workflow/extra-scanner must be a regular file holding one line, the scanner's absolute path"
  MISSING+=("~/.config/ai-workflow/extra-scanner")
fi
HAVE_JQ=1
if command -v jq >/dev/null 2>&1; then ok "jq ($(command -v jq))"; else warn "jq not found — MCP merge will be skipped"; HAVE_JQ=0; fi

# --- symlink helper --------------------------------------------------------
# link_path <source-abs> <target-abs>
link_path() {
  local src="$1" tgt="$2"
  # Never link something that isn't there: `ln -s` to a missing source succeeds and leaves a
  # dangling symlink that fails silently later.
  if [[ ! -e "$src" ]]; then
    warn "skipped ${tgt/#$HOME/~} — no ${src/#$REPO\//} in this repo"
    return
  fi
  if [[ -L "$tgt" && "$(readlink "$tgt")" == "$src" ]]; then
    info "already linked: ${tgt/#$HOME/~}"
    return
  fi
  if [[ -e "$tgt" || -L "$tgt" ]]; then
    local backup="${tgt}.backup.${TS}"
    mv "$tgt" "$backup"
    warn "backed up existing ${tgt/#$HOME/~} -> ${backup/#$HOME/~}"
  fi
  mkdir -p "$(dirname "$tgt")"
  ln -s "$src" "$tgt"
  ok "linked ${tgt/#$HOME/~} -> ${src/#$HOME/~}"
}

echo
echo "==> Linking config into ${DEST/#$HOME/~}"
mkdir -p "$DEST"
for name in "${WHOLE[@]}"; do
  link_path "$SRC/$name" "$DEST/$name"
done

echo
echo "==> Linking skills into ${DEST/#$HOME/~}/skills"
mkdir -p "$DEST/skills"
for s in "${SKILLS[@]}"; do
  link_path "$SRC/skills/$s" "$DEST/skills/$s"
done

# Prune links this repo used to own but no longer does — a skill renamed or deleted here
# leaves a dangling symlink behind, and refusing to create new ones doesn't clear the old.
# Only links pointing INTO this repo's skills dirs are considered; skills installed from
# other sources, and links into any other repo, are never touched.
for l in "$DEST"/skills/*; do
  [[ -L "$l" ]] || continue
  target="$(readlink "$l")"
  case "$target" in
    "$SRC"/skills/*)
      if [[ ! -e "$target" ]]; then
        rm "$l"
        warn "pruned ${l/#$HOME/~} — its source is no longer in this repo"
      fi
      ;;
  esac
done


# ~/.codex/config.toml is rendered, not linked: the base has {HOME} placeholders and the
# optional personal fragment adds trusted projects. A symlink left over from the old layout is
# removed first, so the render is never written through it into a tracked file. The render goes
# to a temp file in the same directory and is renamed into place; an existing regular file is
# backed up only when its content actually changes.
render_codex_config() {
  local tgt="$CODEX_DEST/config.toml" tmp
  if [[ -L "$tgt" ]]; then
    rm "$tgt"
    warn "removed the ${tgt/#$HOME/~} symlink (it is rendered now, never written through a link)"
  fi
  tmp="$(mktemp "$CODEX_DEST/.config.toml.XXXXXX")"
  if ! python3 "$CODEX_SRC/render_config.py" --base "$CODEX_SRC/config.base.toml" \
        --fragment "$CONFIG_DEST/codex-projects.toml" --home "$HOME" > "$tmp"; then
    rm -f "$tmp"
    warn "could not render ${tgt/#$HOME/~} — left as it was"
    return 1
  fi
  if [[ -f "$tgt" ]] && cmp -s "$tmp" "$tgt"; then
    rm -f "$tmp"
    info "already rendered: ${tgt/#$HOME/~}"
    return
  fi
  if [[ -e "$tgt" ]]; then
    cp "$tgt" "${tgt}.backup.${TS}"
    warn "backed up existing ${tgt/#$HOME/~} -> ${tgt/#$HOME/~}.backup.${TS}"
  fi
  chmod 644 "$tmp"
  mv -f "$tmp" "$tgt"
  ok "rendered ${tgt/#$HOME/~}"
}

echo
echo "==> Codex config in ${CODEX_DEST/#$HOME/~}"
mkdir -p "$CODEX_DEST"
render_codex_config
for f in "${CODEX_FILES[@]}"; do
  link_path "$CODEX_SRC/$f" "$CODEX_DEST/$f"
done

echo
echo "==> Linking Codex wrappers into ${LOCAL_BIN/#$HOME/~}"
mkdir -p "$LOCAL_BIN"
for b in "${CODEX_BINS[@]}"; do
  link_path "$CODEX_SRC/bin/$b" "$LOCAL_BIN/$b"
done
link_path "$GATE_LOG_BIN" "$LOCAL_BIN/gate-log"
for b in "${GIT_BINS[@]}"; do
  link_path "$REPO/git/bin/$b" "$LOCAL_BIN/$b"
done
case ":$PATH:" in
  *":$LOCAL_BIN:"*) : ;;
  *) warn "${LOCAL_BIN/#$HOME/~} is not on your PATH — add it so 'codex-audit', 'gate-log', 'zed-ruby-test' and 'suite-queue' resolve" ;;
esac


echo
echo "==> Linking Zed config into ${ZED_DEST/#$HOME/~}"
mkdir -p "$ZED_DEST"
for f in "${ZED_FILES[@]}"; do
  link_path "$ZED_SRC/$f" "$ZED_DEST/$f"
done
for b in "${ZED_BINS[@]}"; do
  link_path "$ZED_SRC/bin/$b" "$LOCAL_BIN/$b"
done

echo
echo "==> Linking the global gitignore into ${GIT_IGNORE_DEST/#$HOME/~}"
# Git reads ~/.config/git/ignore with no configuration as long as
# core.excludesfile is unset. If something HAS set it, this symlink would be
# silently ignored — so say so rather than pretend the file is in effect.
link_path "$REPO/git/ignore" "$GIT_IGNORE_DEST"
EXCLUDES="$(git config --global --get core.excludesfile || true)"
if [[ -n "$EXCLUDES" ]]; then
  warn "core.excludesfile is set to '$EXCLUDES' — it wins over ${GIT_IGNORE_DEST/#$HOME/~}."
  warn "  Run: git config --global --unset core.excludesfile"
fi

echo
echo "==> Linking shell functions into ${SHELL_DEST/#$HOME/~}"
mkdir -p "$SHELL_DEST"
link_path "$SHELL_SRC/zed.zsh" "$SHELL_DEST/zed.zsh"

# The one place this script writes to a file it does not own. ~/.zshrc is not
# managed by this repo (oh-my-zsh, nvm, asdf, PATH all live there by hand), so
# a single marker-guarded source line is appended instead of taking the file
# over. Guarded by the marker, so re-running appends nothing.
ZSHRC_MARKER="# dotfiles: shell functions"
if [[ -f "$ZSHRC" ]] && grep -Fq "$ZSHRC_MARKER" "$ZSHRC"; then
  info "already sourced from ${ZSHRC/#$HOME/~}"
else
  # Not `[[ -f ]] && cp && warn`: under `set -e` that whole list returns
  # non-zero on a fresh Mac with no ~/.zshrc and aborts the installer.
  if [[ -f "$ZSHRC" ]]; then
    cp "$ZSHRC" "${ZSHRC}.backup.${TS}"
    warn "backed up ${ZSHRC/#$HOME/~} -> ${ZSHRC/#$HOME/~}.backup.${TS}"
  fi
  {
    echo ""
    echo "$ZSHRC_MARKER"
    echo "[ -f \"\$HOME/.config/zsh/zed.zsh\" ] && . \"\$HOME/.config/zsh/zed.zsh\""
  } >> "$ZSHRC"
  ok "appended the source line to ${ZSHRC/#$HOME/~} (open a new shell for 'zw')"
fi

# --- MCP merge -------------------------------------------------------------
echo
echo "==> Merging MCP servers into ${CLAUDE_JSON/#$HOME/~}"
if [[ "$HAVE_JQ" -eq 1 ]]; then
  [[ -f "$CLAUDE_JSON" ]] || echo '{}' > "$CLAUDE_JSON"
  tmp="$(mktemp)"
  # Repo servers merged over any existing ones; all other keys preserved.
  jq --slurpfile mcp "$REPO/mcp/mcpServers.json" \
    '.mcpServers = ((.mcpServers // {}) + $mcp[0].mcpServers)' \
    "$CLAUDE_JSON" > "$tmp"
  # Only touch the file if the merge actually changes something (idempotent).
  if jq -e --slurpfile a "$tmp" --slurpfile b "$CLAUDE_JSON" -n '$a[0] == $b[0]' >/dev/null; then
    rm -f "$tmp"
    info "mcpServers already up to date — no change"
  else
    cp "$CLAUDE_JSON" "${CLAUDE_JSON}.backup.${TS}"
    mv "$tmp" "$CLAUDE_JSON"
    ok "merged mcpServers (backup at ${CLAUDE_JSON/#$HOME/~}.backup.${TS})"
  fi
  info "servers now present: $(jq -r '.mcpServers | keys | join(", ")' "$CLAUDE_JSON")"
else
  warn "skipped — install jq, then re-run to merge mcp/mcpServers.json"
fi

# --- manual steps ----------------------------------------------------------
echo
echo "==> Done. Manual steps this script can't automate:"
echo
echo "  1. Log in: run 'claude' and authenticate. macOS stores credentials in"
echo "     the Keychain, which does NOT transfer between machines. Codex auth"
echo "     (~/.codex/auth.json) is machine-local too — run 'codex login' separately."
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "  2. Install missing prerequisites: ${MISSING[*]}"
else
  echo "  2. Prerequisites: all present."
fi
echo "  3. Secrets to fill in: NONE. No tracked file contains a secret."
echo "     The hooks in settings.json are ACTIVE from the first session: they guard"
echo "     edits on main, place worktrees, and gate the security, data and"
echo "     performance audits. None of them reads an API key — they are git, path"
echo "     and diff logic, run by python3 with the standard library only."
echo "  4. Zed: extensions install themselves on first launch (settings.json"
echo "     declares them under auto_install_extensions) — just open Zed once."
echo "     The Ruby language servers are gems, not extensions:"
echo "       for g in ruby-lsp rubocop; do"
echo "         grep -qxF \"\$g\" ~/.default-gems 2>/dev/null || echo \"\$g\" >> ~/.default-gems; done"
echo "       for v in \$(asdf list ruby | tr -d ' *'); do \\"
echo "         ASDF_RUBY_VERSION=\$v asdf exec gem install ruby-lsp rubocop; done"
echo "       asdf reshim ruby"
echo "     ~/.default-gems makes every future 'asdf install ruby' carry both."
echo "  5. Not managed by this repo (reinstall separately if you want them):"
echo "     skills installed from other sources, and ~/.claude/plugins."
echo
