"""Regression tests for the Clan documentation snapshot updater CLI."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUCCESS_RETURN_CODE = 0
UPDATER_ERROR_CODE = 2
SHA_HEX_LENGTH = 40
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_cli_module = importlib.import_module("lib.nix_clan_updater.cli")
_core_module = importlib.import_module("lib.nix_clan_updater.core")
main = _cli_module.main
updater_error = _core_module.UpdaterError
_pin_clan_urls = _core_module._pin_clan_urls
_rewrite_markdown_line = _core_module._rewrite_markdown_line
_rewrite_markdown_links = _core_module._rewrite_markdown_links
_toc_for = _core_module._toc_for
update_index = _core_module.update_index
update_notice = _core_module.update_notice
update_skill = _core_module.update_skill


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    if result.returncode != SUCCESS_RETURN_CODE:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class UpdaterCliTests(unittest.TestCase):
    """Exercise the updater through its public command-line entrypoint."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="nix-clan-updater-test-")
        self.root = Path(self.temp.name)
        self.source = self.root / "nix-clan-2605"
        self.repo = self.root / "clan-core"
        self.target = self.root / "nix-clan-2611"
        self._make_source()
        self._make_repo()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _make_source(self) -> None:
        skill_text = (
            "---\n"
            "name: nix-clan-2605\n"
            "description: Use for Clan 26.05 inventory, services, vars, deployment, "
            "migrations, and NixOS workflow documentation.\n"
            "license: MIT\n"
            "metadata:\n"
            "  upstream: https://git.clan.lol/clan/clan-core\n"
            "  branch: 26.05\n"
            "  commit: 1111111111111111111111111111111111111111\n"
            "  retrieved: 2026-08-10\n"
            "---\n"
            "\n"
            "# Clan 26.05 Documentation\n"
            "\n"
            "The bundled snapshot is Clan `clan-core` branch `26.05`, commit\n"
            "`1111111111111111111111111111111111111111`, retrieved 2026-08-10.\n"
        )
        _write(self.source, "SKILL.md", skill_text)
        _write(
            self.source,
            "references/INDEX.md",
            """# Clan 26.05 Reference Index

## Snapshot

- Source: `https://git.clan.lol/clan/clan-core/src/branch/26.05/docs/src`
- Repository: `https://git.clan.lol/clan/clan-core`
- Branch: `26.05`
- Commit: `1111111111111111111111111111111111111111`
- Retrieved: `2026-08-10`
- Vendored: 1 Markdown files from upstream `docs/src`; excludes
  `test.md`, non-Markdown sources such as `index.svelte`, and generated-prefix
  Markdown pages when present.

## Topic router

- `docs/guides/local.md`
""",
        )
        _write(self.source, "references/NOTICE.md", "# old notice\n")
        _write(self.source, "references/docs/old.md", "# old\n")
        _write(self.source, "references/embeds/old.nix", "old = true;\n")
        _write(self.source, "scripts/keep.txt", "keep\n")
        _write(self.source, "tests/keep.txt", "keep\n")
        _write(self.source, "tests/__pycache__/stale.pyc", "runtime junk\n")
        _write(self.source, ".pytest_cache/lastfailed", "runtime junk\n")
        _write(self.source, ".ruff_cache/last", "runtime junk\n")

    def _make_repo(self, unknown: bool = False) -> None:
        self.repo.mkdir()
        _git(self.repo, "init", "-b", "26.11")
        _git(self.repo, "config", "user.email", "test@example.invalid")
        _git(self.repo, "config", "user.name", "Updater Test")
        _write(self.repo, "LICENSE.md", "Copyright target\n\nPermission granted.\n")
        _write(self.repo, "docs/src/guides/local.md", "# Local\n")
        token_page = """# Tokens

See [local](/docs/guides/local) and [generated](/docs/reference/options/foo#bar).
See [titled](</docs/guides/local?query=yes#part> "Keep this title").
Inline code: `[local](/docs/guides/local?inline=yes)`.

~~~text
[fenced](/docs/guides/local?fenced=yes)
~~~

```text
nix run https://clan.lol/install/{{ version }}
nix run https://clan.lol/install/{{! version }}
https://git.clan.lol/clan/clan-core/archive/main.tar.gz
github:clan/clan-core
```
"""
        if unknown:
            token_page += "\n[missing](/docs/guides/missing)\n"
        _write(self.repo, "docs/src/guides/tokens.md", token_page)
        _write(
            self.repo,
            "docs/src/guides/embed.md",
            "# Embed\n\n```nix [sample.nix] {1} embed=sample.nix\n```\n",
        )
        _write(
            self.repo,
            "docs/src/guides/disk-encryption.md",
            "# Disk Encryption\n\n"
            "This guide provides an example setup for a ext4-single-disk ZFS system "
            "with native encryption, accessible for decryption remotely.\n",
        )
        _write(
            self.repo,
            "docs/src/reference/index.md",
            "# Overview\n\n"
            "This documentation is always built for the main branch.\n"
            "If you need documentation for a specific commit "
            "you can build it on your own\n\n"
            "```bash\n"
            "nix build 'git+https://git.clan.lol/clan/clan-core?ref="
            "0324f4d4b87d932163f351e53b23b0b17f2b5e15#docs'\n"
            "```\n",
        )
        long = "# Long\n\n## Section\n\n" + "filler\n" * 301
        _write(self.repo, "docs/src/long.md", long)
        _write(self.repo, "docs/src/test.md", "# fixture\n")
        _write(self.repo, "docs/src/index.svelte", "<h1>site</h1>\n")
        _write(self.repo, "docs/src/reference/options/generated.md", "# generated\n")
        _write(self.repo, "docs/embeds/sample.nix", "{ sample = true; }\n")
        _write(self.repo, "docs/embeds/test.nix", "test = true;\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-m", "fixture")
        _git(self.repo, "branch", "26.05")

    def _run(self, *extra: str, branch: str = "26.11") -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                [
                    "update",
                    "--to-branch",
                    branch,
                    "--repo",
                    str(self.repo),
                    "--source-dir",
                    str(self.source),
                    *extra,
                ],
                skill_root=ROOT,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"], skill_root=ROOT)
        self.assertEqual(raised.exception.code, SUCCESS_RETURN_CODE)
        self.assertIn("update", stdout.getvalue())

    def test_dry_run_is_immutable_and_json(self) -> None:
        before = _tree(self.source)
        code, stdout, stderr = self._run("--json")
        self.assertEqual(code, SUCCESS_RETURN_CODE, stderr)
        self.assertEqual(before, _tree(self.source))
        self.assertFalse(self.target.exists())
        summary = json.loads(stdout)
        self.assertEqual(summary["release"], "26.11")
        self.assertEqual(summary["skill_name"], "nix-clan-2611")
        self.assertEqual(
            summary["excluded"],
            [
                "docs/src/index.svelte (non-Markdown)",
                "docs/src/reference/options/generated.md (generated)",
                "docs/src/test.md",
                "docs/embeds/test.nix",
            ],
        )
        self.assertIn("changed", summary["counts"])
        transient_names = ("__pycache__", ".pytest_cache", ".ruff_cache", ".pyc")
        for delta in summary["files"]:
            self.assertFalse(any(name in delta["path"] for name in transient_names))

    def test_same_release_dry_run_is_allowed_but_apply_is_refused(self) -> None:
        before = _tree(self.source)
        code, _, stderr = self._run(branch="26.05")
        self.assertEqual(code, SUCCESS_RETURN_CODE, stderr)
        self.assertEqual(before, _tree(self.source))
        self.assertTrue(self.source.exists())
        code, _, stderr = self._run("--apply", branch="26.05")
        self.assertEqual(code, UPDATER_ERROR_CODE)
        self.assertIn("cannot replace", stderr)
        self.assertEqual(before, _tree(self.source))

    def test_apply_creates_normalized_sibling_and_keeps_source(self) -> None:
        code, _, stderr = self._run("--apply")
        self.assertEqual(code, SUCCESS_RETURN_CODE, stderr)
        self.assertTrue(self.target.is_dir())
        self.assertTrue(self.source.is_dir())
        self.assertTrue((self.target / "references/docs/guides/local.md").is_file())
        self.assertFalse(
            any(
                any(
                    name in path
                    for name in ("__pycache__", ".pytest_cache", ".ruff_cache", ".pyc")
                )
                for path in _tree(self.target)
            )
        )
        skill = (self.target / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: nix-clan-2611", skill)
        self.assertIn("branch: 26.11", skill)
        index = (self.target / "references/INDEX.md").read_text(encoding="utf-8")
        self.assertIn("- Branch: `26.11`", index)
        commit = _git(self.repo, "rev-parse", "26.11")
        self.assertIn(f"- Commit: `{commit}`", index)
        self.assertIn("- Retrieved: `2026-08-10`", index)
        self.assertIn(
            "- Vendored: 6 Markdown files from upstream `docs/src`; excludes", index
        )
        self.assertIn("- `docs/guides/local.md`", index)
        self.assertFalse(
            (self.target / "references/docs/reference/options/generated.md").exists()
        )
        self.assertFalse((self.target / "references/docs/test.md").exists())
        self.assertFalse((self.target / "references/embeds/test.nix").exists())
        self.assertEqual(
            (self.target / "references/embeds/sample.nix").read_text(),
            "{ sample = true; }\n",
        )
        self.assertIn(
            "Copyright target", (self.target / "references/NOTICE.md").read_text()
        )

    def test_transforms_links_tokens_and_embed(self) -> None:
        code, _, stderr = self._run("--apply")
        self.assertEqual(code, SUCCESS_RETURN_CODE, stderr)
        tokens = (self.target / "references/docs/guides/tokens.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("(local.md)", tokens)
        self.assertIn('(<local.md?query=yes#part> "Keep this title")', tokens)
        self.assertIn("[fenced](/docs/guides/local?fenced=yes)", tokens)
        self.assertIn("`[local](/docs/guides/local?inline=yes)`", tokens)
        self.assertIn("https://clan.lol/docs/26.11/reference/options/foo#bar", tokens)
        self.assertIn("install/26.11", tokens)
        self.assertIn("install/{{! version }}", tokens)
        self.assertIn("archive/26.11.tar.gz", tokens)
        self.assertIn("github:clan/clan-core?ref=26.11", tokens)
        embed = (self.target / "references/docs/guides/embed.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("{ sample = true; }", embed)
        self.assertNotIn("embed=", embed)

    def test_markdown_scanner_handles_unterminated_and_nested_fences(self) -> None:
        self.assertEqual(
            _rewrite_markdown_line(
                "a `b\n", "guides/tokens.md", {"guides/local.md"}, "26.11"
            ),
            "a `b\n",
        )
        self.assertEqual(
            _rewrite_markdown_links(
                "    ```nix\n",
                "guides/tokens.md",
                {"guides/local.md"},
                "26.11",
            ),
            "    ```nix\n",
        )
        for opening, closing in (("```", "```"), ("~~~", "~~~")):
            fenced = (
                f"    {opening}nix\n    [example](/docs/guides/local)\n    {closing}\n"
            )
            self.assertEqual(
                _rewrite_markdown_links(
                    fenced,
                    "guides/tokens.md",
                    {"guides/local.md"},
                    "26.11",
                ),
                fenced,
            )
        listed = "  - ```nix\n      [example](/docs/guides/local)\n    ~~~\n    ```\n"
        self.assertEqual(
            _rewrite_markdown_links(
                listed,
                "guides/tokens.md",
                {"guides/local.md"},
                "26.11",
            ),
            listed,
        )

    def test_toc_and_compatibility_patches(self) -> None:
        code, _, stderr = self._run("--apply")
        self.assertEqual(code, SUCCESS_RETURN_CODE, stderr)
        long = (self.target / "references/docs/long.md").read_text(encoding="utf-8")
        self.assertIn("<!-- nix-clan-updater:toc:start -->", long)
        self.assertIn("[Section](#section)", long)
        disk = (self.target / "references/docs/guides/disk-encryption.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("ZFS system with native encryption and remote decryption", disk)
        reference = (self.target / "references/docs/reference/index.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("This bundled overview is from Clan `26.11`", reference)

    def test_pin_clan_url_preserves_query_suffixes(self) -> None:
        text = (
            "github:clan/clan-core?ref=main&dir=docs#readme "
            "github:clan/clan-core?dir=docs#readme "
            "github:clan/clan-core#readme"
        )
        pinned = _pin_clan_urls(text, "26.11")
        self.assertEqual(
            pinned,
            "github:clan/clan-core?ref=26.11&dir=docs#readme "
            "github:clan/clan-core?ref=26.11&dir=docs#readme "
            "github:clan/clan-core?ref=26.11#readme",
        )

    def test_metadata_boundaries_and_license_bytes(self) -> None:
        malformed_index = self.source.joinpath("references/INDEX.md").read_text()
        with self.assertRaises(updater_error):
            update_index(
                malformed_index.replace("- Branch: `26.05`", "- Branch: 26.05"),
                "26.11",
                "2" * SHA_HEX_LENGTH,
                "2026-08-10",
                1,
            )
        with self.assertRaises(updater_error):
            update_skill(
                self.source.joinpath("SKILL.md")
                .read_text()
                .replace(
                    "description:",
                    "description: >",
                    1,
                ),
                "26.11",
                "2" * SHA_HEX_LENGTH,
                "2026-08-10",
            )
        license_bytes = b"Copyright\n\n"
        notice = update_notice(
            "repo", "26.11", "2" * SHA_HEX_LENGTH, "2026-08-10", license_bytes
        )
        self.assertTrue(notice.endswith(license_bytes))

    def test_managed_toc_regenerates_and_fences_are_skipped(self) -> None:
        filler = "filler\n" * 301
        marker = (
            "<!-- nix-clan-updater:toc:start -->\n"
            "## Table of Contents\n"
            "- [Old](#old)\n"
            "<!-- nix-clan-updater:toc:end -->\n"
        )
        original = "~~~markdown\n## Inside\n~~~\n\n## Kept\n\nbody\n" + filler + marker
        updated = _toc_for(original.replace("## Kept", "## Renamed"), None)
        self.assertIn("[Renamed](#renamed)", updated)
        self.assertNotIn("[Old](#old)", updated)
        self.assertNotIn("[Inside](#inside)", updated)

    def test_source_symlink_is_refused_without_mutation(self) -> None:
        link = self.source / "linked.txt"
        try:
            link.symlink_to(self.source / "SKILL.md")
        except OSError:
            self.skipTest("symlinks unavailable")
        before = _tree(self.source)
        code, _, stderr = self._run()
        self.assertEqual(code, UPDATER_ERROR_CODE)
        self.assertIn("symlink", stderr)
        self.assertEqual(before, _tree(self.source))
        self.assertFalse(self.target.exists())

    def test_unknown_manual_link_fails_without_mutation(self) -> None:
        shutil.rmtree(self.repo)
        self._make_repo(unknown=True)
        before = _tree(self.source)
        code, _, stderr = self._run()
        self.assertEqual(code, UPDATER_ERROR_CODE)
        self.assertIn("unknown manual docs link", stderr)
        self.assertEqual(before, _tree(self.source))
        self.assertFalse(self.target.exists())

    def test_target_collision_and_malformed_release(self) -> None:
        self.target.mkdir()
        code, _, stderr = self._run()
        self.assertEqual(code, UPDATER_ERROR_CODE)
        self.assertIn("already exists", stderr)
        self.target.rmdir()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                [
                    "update",
                    "--to-branch",
                    "2611",
                    "--repo",
                    str(self.repo),
                    "--source-dir",
                    str(self.source),
                ],
                skill_root=ROOT,
            )
        self.assertEqual(code, UPDATER_ERROR_CODE)
        self.assertIn("YY.MM", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
