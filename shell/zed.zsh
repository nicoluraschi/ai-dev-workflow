# zed.zsh — open a worktree in Zed.
#
# Sourced from ~/.zshrc via install.sh. Worktrees live at
# ~/worktrees/<repo>/<branch>, and because the branch carries the nesting
# ("feat/add-widget"), a worktree sits two levels under the repo, not one.
#
#   zw                            list the repos that have worktrees
#   zw webapp                     one worktree? open it. Several? list them.
#   zw webapp feat/add-widget     open that one
#
# Tests: zsh shell/test_zed.zsh

# A linked worktree is marked by a .git FILE (not a directory), so testing for
# a .git entry finds the leaves whatever the nesting depth.
_zw_repos() {
  local root="${ZW_ROOT:-$HOME/worktrees}" d
  [[ -d "$root" ]] || return 0
  for d in "$root"/*(N/); do print -r -- "${d:t}"; done
}

_zw_branches() {
  local root="${ZW_ROOT:-$HOME/worktrees}" repo="$1" d
  [[ -d "$root/$repo" ]] || return 0
  for d in "$root/$repo"/**/.git(N); do
    print -r -- "${${d:h}#$root/$repo/}"
  done
}

zw() {
  local root="${ZW_ROOT:-$HOME/worktrees}" repo="${1:-}" branch="${2:-}"

  if [[ -z "$repo" ]]; then
    _zw_repos
    return 0
  fi

  if [[ ! -d "$root/$repo" ]]; then
    print -u2 "zw: no worktrees for '$repo' in ${root/#$HOME/~}"
    return 1
  fi

  if [[ -z "$branch" ]]; then
    # (@f) on empty output yields a ONE-element array holding the empty string,
    # so an empty list would otherwise be misread as "exactly one worktree" and
    # open "<repo>/". Drop empties before counting.
    local -a found=(${(@f)"$(_zw_branches "$repo")"})
    found=(${found:#})
    if (( ${#found} == 0 )); then
      print -u2 "zw: no worktrees under $repo"
      return 1
    elif (( ${#found} == 1 )); then
      branch="${found[1]}"
    else
      print -rl -- "${found[@]}"
      return 0
    fi
  fi

  local dest="$root/$repo/$branch"
  if [[ ! -e "$dest/.git" ]]; then
    print -u2 "zw: ${dest/#$HOME/~} is not a worktree"
    return 1
  fi

  # The seam the tests use.
  if [[ -n "${ZW_DRY_RUN:-}" ]]; then
    print -r -- "open $dest"
    return 0
  fi
  zed "$dest"
}

# Completion: repo names, then that repo's worktrees.
_zw() {
  case $CURRENT in
    2) compadd -- ${(f)"$(_zw_repos)"} ;;
    3) compadd -- ${(f)"$(_zw_branches "${words[2]}")"} ;;
  esac
}
if (( $+functions[compdef] )); then compdef _zw zw; fi
