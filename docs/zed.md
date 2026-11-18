# Zed — setup details

The [README](../README.md#-zed--where-i-read-code) covers what Zed is for and its shortcuts. This
page has the language-server, test-runner and new-Mac detail.

## Viewer-safe saving

Zed defaults `remove_trailing_whitespace_on_save` and `ensure_final_newline_on_save` to `true`, so
saving a file the agent just wrote would rewrite it and show up as a diff. Those two,
`format_on_save` and `autosave` are all off.

## Ruby language servers, test runner and trust

`ruby-lsp` + `rubocop`, with `solargraph` explicitly disabled — and also `sorbet`, `steep`,
`kanayago` and `fuzzy-ruby-server`, which the `"..."` tail would otherwise pull in. The tail is
kept only because `tailwindcss-language-server` lives in it. ERB gets `herb`, which declares
`HTML+ERB` only; `YAML+ERB` and `JS+ERB` get `ruby-lsp` alone.

`use_bundler: true` resolves the servers through the project's Gemfile, which is what makes
go-to-definition reach into a gem. The cost is a generated `.ruby-lsp/` directory per Rails root —
globally gitignored.

The language servers are **gems, not extensions**, so they're per Ruby version:

```bash
for g in ruby-lsp rubocop; do                                       # every FUTURE asdf ruby
  grep -qxF "$g" ~/.default-gems 2>/dev/null || echo "$g" >> ~/.default-gems
done
for v in $(asdf list ruby | tr -d ' *'); do                         # the ones already there
  ASDF_RUBY_VERSION=$v asdf exec gem install ruby-lsp rubocop
done
asdf reshim ruby
```

`zed-ruby-test` exists because **the Rails app isn't at the worktree root** in my monorepos —
it's in `backend/`, so `$ZED_WORKTREE_ROOT` points at a directory with no Gemfile. It walks up
from the open file to the nearest Gemfile, detects RSpec vs Minitest, and `cd`s in so asdf
resolves the project's Ruby from `.tool-versions`. That's also what keeps the tasks global.
`cmd-alt-t` is the only mnemonic root free in both Zed's default-macos and VS Code keymaps.

**Extensions aren't installed by hand**: `auto_install_extensions` installs Ruby, SQL,
Dockerfile, TOML, Terraform, env and HTML on first launch. Zed's state, caches, extension
binaries and history are machine-local and never tracked.

`session.trust_all_worktrees` stays at Zed's default of `false`. Trusting a project lets it start
language servers and sync its own `.zed/settings.json`, so it stays a deliberate click per project.

## New Mac

1. `brew install --cask zed` — the cask provides `/opt/homebrew/bin/zed`; there's no separate CLI step.
2. Open Zed once so the declared extensions install.
3. Run the gem block above.
4. Click **Trust** the first time you open each project.
