# Set up and run orbs

Read this when changing a project's orb lifecycle or running threads in orbs.

- Setup runs once per project snapshot; a new thread restores the snapshot. Editing the project pre-setup script invalidates snapshots, editing a tracked `.agents/setup` does not: after changing it, run `amp projects snapshots delete <project>`.
- An orb starts without the user's `~/.config/amp/settings.json`. Settings that must hold there, such as `amp.tools.disable`, belong in the workspace's `.amp/settings.json`; generate it in setup when the repository must not track it.
- `amp projects status` maps the current directory to a project by git remote; orb runs need a mapped project. `amp projects create` rejects GitHub repositories whose name starts with `_`: attach such a repository to a wrapper project as an additional repository, and have the wrapper's pre-setup run the repository's own setup.
- `amp --executor orb -x "<prompt>"` returns the thread URL immediately while the orb works; read results with `amp threads markdown <thread>`. Measure cold setup from `~/.cache/amp/logs/setup.log` inside the orb.
- An orb pauses only after idle time; archive a finished thread with `amp threads archive <thread>` to pause it at once.
