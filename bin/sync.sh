#!/bin/sh
set -eu

# AGENTS_HOME
# Root of the agents repo
AGENTS_HOME="${HOME}/.config/agents"

# ASSETS_HOME
# Tool agnostic assets
ASSETS_HOME="${AGENTS_HOME}/assets"

# TOOLS_HOME
# Tool specific configs
TOOLS_HOME="${AGENTS_HOME}/tools"

# CODEX_HOME
CODEX_HOME="${HOME}/.config/codex"

# OPENCODE_HOME
# OpenCode config root
OPENCODE_HOME="${HOME}/.config/opencode"

# CLAUDE_HOME
# Claude config root
CLAUDE_HOME="${HOME}/.claude"

# PI_HOME
# Pi config root
PI_HOME="${HOME}/.config/pi/agent"

# MCPORTER_HOME
MCPORTER_HOME="${HOME}/.mcporter"

# VERBOSE
# Set to 1 to emit logs
VERBOSE="${VERBOSE:-off}"

# note
# Emit a line only when VERBOSE is 1
note() {
  [ "${VERBOSE}" = "on" ] && printf '%s\n' "${1}"
  return 0
}

# report
# Emit a report line
report() {
  printf '%s\n' "sync: ${1}"
}

# err
# Emit errors to stderr
err() {
  printf '%s\n' "sync: ${1}" >&2
}

# exists
# True when a path exists
exists() {
  [ -e "${1}" ]
}

# is_dir
# True when a path is a directory
is_dir() {
  [ -d "${1}" ]
}

# ensure_dir
# Create directory path if missing
ensure_dir() {
  mkdir -p "${1}"
}

# rm_entry
# Remove file or directory
rm_entry() {
  exists "${1}" || return 0
  [ -L "${1}" ] && rm -f "${1}" && return 0
  is_dir "${1}" && rm -rf "${1}" && return 0
  rm -f "${1}"
}

# copy_item
# Replace destination with source file
copy_item() {
  src="${1}"
  dst="${2}"

  exists "${src}" || {
    err "missing source: ${src}"
    return 0
  }
  ensure_dir "$(dirname "${dst}")"
  rm_entry "${dst}"
  cp -a "${src}" "${dst}"
  note "copied: ${dst} <- ${src}"
}

# copy_dir_into
# Copy directory contents into destination
copy_dir_into() {
  src_dir="${1}"
  dst_dir="${2}"

  is_dir "${src_dir}" || {
    err "missing directory: ${src_dir}"
    return 0
  }
  ensure_dir "${dst_dir}"
  cp -a "${src_dir}/." "${dst_dir}/"
  note "copied: ${dst_dir} <- ${src_dir}"
}

# tool_dirs
# Map tool config directories to destinations
tool_dirs() {
  printf '%s\n' "${TOOLS_HOME}/claude ${CLAUDE_HOME}"
  printf '%s\n' "${TOOLS_HOME}/codex ${CODEX_HOME}"
  printf '%s\n' "${TOOLS_HOME}/opencode ${OPENCODE_HOME}"
  printf '%s\n' "${TOOLS_HOME}/pi ${PI_HOME}"
}

# run_pairs
# Read src dst pairs from stdin and call handler
run_pairs() {
  handler="${1}"
  while read -r src dst; do
    "${handler}" "${src}" "${dst}"
  done
  return 0
}

# asset_copies
# Map every asset directory to every tool home
asset_copies() {
  for asset_path in "${ASSETS_HOME}"/*; do
    [ -d "${asset_path}" ] || continue
    asset_name="$(basename "${asset_path}")"
    for tool_home in "${CLAUDE_HOME}" "${CODEX_HOME}" "${OPENCODE_HOME}"; do
      printf '%s\n' "${asset_path} ${tool_home}/${asset_name}"
    done
    pi_dest="${PI_HOME}/${asset_name}"
    [ "${asset_name}" = "commands" ] && pi_dest="${PI_HOME}/prompts"
    printf '%s\n' "${asset_path} ${pi_dest}"
  done
}

# agent_files
# Map AGENTS.md to tool locations
agent_files() {
  printf '%s\n' "${AGENTS_HOME}/AGENTS.md ${CODEX_HOME}/AGENTS.md"
  printf '%s\n' "${AGENTS_HOME}/AGENTS.md ${OPENCODE_HOME}/AGENTS.md"
  printf '%s\n' "${AGENTS_HOME}/AGENTS.md ${CLAUDE_HOME}/CLAUDE.md"
  printf '%s\n' "${AGENTS_HOME}/AGENTS.md ${PI_HOME}/AGENTS.md"
}

# config_files
# Map standalone config files
config_files() {
  printf '%s\n' "${ASSETS_HOME}/mcporter.jsonc ${MCPORTER_HOME}/mcporter.json"
}

tool_dirs | run_pairs copy_dir_into
asset_copies | run_pairs copy_dir_into
agent_files | run_pairs copy_item
config_files | run_pairs copy_item
