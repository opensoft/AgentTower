# Source this file from zsh to enable AgentTower Speckit worktree helpers.
#
# Example:
#   source /home/brett/projects/AgentTower/.specify/shell/ct.zsh

SCRIPT_DIR="${${(%):-%x}:A:h}"
source "$SCRIPT_DIR/worktrees.sh"
