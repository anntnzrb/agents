#!/bin/sh
# Reaper for one Pi session's background jobs. Pi keeps this script's stdin open; when Pi exits
# for any reason, including SIGKILL, the kernel closes the pipe and `read` returns EOF.
# Pi writes "+<pgid>" when a job starts and "-<pgid>" once it is reaped. Every job also carries
# PI_BG_OWNER=<tag> in its environment, which survives setsid and reparenting, so processes that
# left their group are found by tag.
dir=$1 tag=$2
groups=""
trap '' INT HUP TERM
while IFS= read -r line; do
  case $line in
    +*) groups="$groups ${line#+}" ;;
    -*) groups=$(printf '%s\n' $groups | grep -vx "${line#-}" | tr '\n' ' ') ;;
  esac
done
tagged() {
  if [ -r /proc/self/environ ]; then
    for e in /proc/[0-9]*/environ; do
      tr '\0' '\n' < "$e" 2>/dev/null | grep -qx "PI_BG_OWNER=$tag" && { p=${e#/proc/}; echo "${p%/environ}"; }
    done
  else
    ps -E -ww -o pid= -o command= -U "$(id -u)" 2>/dev/null | grep -F " PI_BG_OWNER=$tag" | awk '{print $1}'
  fi
}
reap() { sig=$1; for g in $groups; do kill -"$sig" -"$g" 2>/dev/null; done; for p in $(tagged); do kill -"$sig" "$p" 2>/dev/null; done; }
reap TERM
sleep 1
reap KILL
rm -rf "$dir"
