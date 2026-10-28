#!/usr/bin/env bash
# Sets up the opportunity routine on this Linux machine.
#   install.sh skill   /letter-opportunities in Claude Code here (symlink in .claude/skills, gitignored)
#   install.sh timer   systemd user timer: run-routine.sh every 15 minutes; installed, not started
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"

install_skill() {
  mkdir -p "$repo/.claude/skills"
  ln -sfn "$repo/docs/routines/letter-opportunities" "$repo/.claude/skills/letter-opportunities"
  echo "Skill installed: type /letter-opportunities in Claude Code started in $repo"
}

install_timer() {
  local units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$units"
  cat >"$units/letter-opportunities.service" <<UNIT
[Unit]
Description=Letter Writer: draft letters for captured jobs

[Service]
Type=oneshot
WorkingDirectory=$repo
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$repo/scripts/opportunities/run-routine.sh
# Bounded like everything else on this machine; drafting needs far less.
MemoryMax=3G
TimeoutStartSec=2h
UNIT
  cat >"$units/letter-opportunities.timer" <<UNIT
[Unit]
Description=Draft letters for captured jobs every 15 minutes

[Timer]
OnCalendar=*:0/15
RandomizedDelaySec=1min
# A run missed while the machine was off or asleep happens once on wake.
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl --user daemon-reload
  echo "Timer installed. Start it with:  systemctl --user enable --now letter-opportunities.timer"
  echo "Run once now:                    systemctl --user start letter-opportunities.service"
  echo "Log:                             $repo/temp/opportunities/routine.log"
}

case "${1:-}" in
  skill) install_skill ;;
  timer) install_timer ;;
  *) echo "usage: $0 skill|timer" >&2; exit 2 ;;
esac
