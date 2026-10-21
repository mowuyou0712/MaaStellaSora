import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.updater import mss_update


class MappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_mapping(self, payload: dict) -> Path:
        path = self.root / "update_mapping.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def payload(mirrors: list[dict]) -> dict:
        return {
            "repo": {"owner": "MaaStellaSora", "name": "MaaStellaSora"},
            "api": "https://api.github.com/repos/{owner}/{repo}",
            "asset_pattern": "{name}-{platform}-{tag}.{ext}",
            "platforms": {"win-x86_64": "zip"},
            "mirrors": mirrors,
            "protected_paths": ["config"],
            "managed_dirs": ["resource"],
        }

    def test_skips_disabled_mirrors(self) -> None:
        path = self.write_mapping(
            self.payload(
                [
                    {"name": "停用", "prefix": "https://off.invalid/", "enabled": False},
                    {"name": "gh-proxy", "prefix": "https://gh-proxy.com/"},
                ]
            )
        )

        mapping = mss_update.Mapping.load(path)

        self.assertEqual([mirror.name for mirror in mapping.mirrors], ["gh-proxy"])

    def test_candidates_respect_scope_order_and_direct_fallback(self) -> None:
        path = self.write_mapping(
            self.payload(
                [
                    {"name": "only-download", "prefix": "https://a.invalid/", "scopes": ["download"]},
                    {"name": "both", "prefix": "https://b.invalid/", "scopes": ["api", "download"]},
                ]
            )
        )
        mapping = mss_update.Mapping.load(path)

        api_urls = mapping.candidates("api", "https://api.github.com/x")
        download_urls = mapping.candidates("download", "https://github.com/x")

        self.assertEqual(
            api_urls,
            [("both", "https://b.invalid/https://api.github.com/x"), ("直连", "https://api.github.com/x")],
        )
        self.assertEqual(
            download_urls,
            [
                ("only-download", "https://a.invalid/https://github.com/x"),
                ("both", "https://b.invalid/https://github.com/x"),
                ("直连", "https://github.com/x"),
            ],
        )

    def test_direct_prefix_is_not_duplicated(self) -> None:
        path = self.write_mapping(self.payload([{"name": "直连 GitHub", "prefix": ""}]))
        mapping = mss_update.Mapping.load(path)

        self.assertEqual(
            mapping.candidates("download", "https://github.com/x"),
            [("直连 GitHub", "https://github.com/x")],
        )

    def test_rejects_missing_or_mirrorless_mapping(self) -> None:
        with self.assertRaisesRegex(mss_update.UpdateError, "找不到映射表"):
            mss_update.Mapping.load(self.root / "absent.json")

        path = self.write_mapping(self.payload([]))
        with self.assertRaisesRegex(mss_update.UpdateError, "没有可用镜像"):
            mss_update.Mapping.load(path)

    def test_project_mapping_is_usable(self) -> None:
        mapping = mss_update.Mapping.load(mss_update.DEFAULT_MAPPING)

        self.assertEqual(mapping.repo_name, "MaaStellaSora")
        self.assertIn("win-x86_64", mapping.platforms)
        self.assertIn("config", mapping.protected)
        self.assertTrue(any(mirror.serves("api") for mirror in mapping.mirrors))
        self.assertTrue(any(mirror.serves("download") for mirror in mapping.mirrors))


class VersionTests(unittest.TestCase):
    def test_leading_v_is_ignored(self) -> None:
        self.assertEqual(
            mss_update.version_key("v1.7.0"),
            mss_update.version_key("1.7.0"),
        )

    def test_prerelease_sorts_before_release(self) -> None:
        self.assertLess(
            mss_update.version_key("1.7.0-beta.1"),
            mss_update.version_key("1.7.0"),
        )

    def test_newer_handles_empty_current_and_bad_input(self) -> None:
        self.assertTrue(mss_update.is_newer("1.7.0", ""))
        self.assertFalse(mss_update.is_newer("1.7.0", "v1.7.0"))
        self.assertTrue(mss_update.is_newer("1.7.1", "1.7.0"))
        self.assertFalse(mss_update.is_newer("1.7.0", "1.7.1"))
        self.assertTrue(mss_update.is_newer("1.7.0", "??"))


class AssetTests(unittest.TestCase):
    @staticmethod
    def release(*names: str, tag: str = "v1.7.0") -> dict:
        return {
            "tag_name": tag,
            "assets": [{"name": name, "size": 1, "browser_download_url": f"https://example.invalid/{name}"} for name in names],
        }

    @staticmethod
    def mapping() -> mss_update.Mapping:
        return mss_update.Mapping.load(mss_update.DEFAULT_MAPPING)

    def test_prefers_name_built_from_pattern(self) -> None:
        release = self.release(
            "MaaStellaSora-win-aarch64-v1.7.0.zip",
            "MaaStellaSora-win-x86_64-v1.7.0.zip",
        )

        asset = mss_update.resolve_asset(self.mapping(), release, "win-x86_64")

        self.assertEqual(asset["name"], "MaaStellaSora-win-x86_64-v1.7.0.zip")

    def test_falls_back_to_platform_token(self) -> None:
        release = self.release("MaaStellaSora-win-x86_64-v1.7.0-extra.zip")

        asset = mss_update.resolve_asset(self.mapping(), release, "win-x86_64")

        self.assertEqual(asset["name"], "MaaStellaSora-win-x86_64-v1.7.0-extra.zip")

    def test_reports_missing_platform(self) -> None:
        release = self.release("MaaStellaSora-android-arm64-v8a-v1.7.0.apk")

        with self.assertRaisesRegex(mss_update.UpdateError, "没有 win-x86_64"):
            mss_update.resolve_asset(self.mapping(), release, "win-x86_64")


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.install_dir = self.root / "install"
        self.installer = mss_update.Installer(self.install_dir)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def test_content_root_accepts_flat_and_wrapped_layouts(self) -> None:
        flat = self.root / "flat"
        self.write(flat / "interface.json", "{}")
        self.write(flat / "agent" / "main.py", "")
        self.assertEqual(self.installer.content_root(flat), flat)

        wrapped = self.root / "wrapped"
        self.write(wrapped / "MaaStellaSora" / "interface.json", "{}")
        self.assertEqual(self.installer.content_root(wrapped), wrapped / "MaaStellaSora")

    def test_extract_rejects_path_traversal(self) -> None:
        archive = self.root / "evil.zip"
        with zipfile.ZipFile(archive, "w") as bundled:
            bundled.writestr("../escape.txt", "escaped")

        with self.assertRaisesRegex(mss_update.UpdateError, "非法路径"):
            self.installer.extract(archive, self.root / "staging")
        self.assertFalse((self.root / "escape.txt").exists())

    def test_sync_replaces_adds_prunes_and_keeps_protected_paths(self) -> None:
        self.write(self.install_dir / "interface.json", json.dumps({"version": "0.9.5"}))
        self.write(self.install_dir / "resource" / "base" / "a.json", "old")
        self.write(self.install_dir / "resource" / "base" / "stale.json", "stale")
        self.write(self.install_dir / "config" / "config.json", "user")

        source = self.root / "source"
        self.write(source / "interface.json", json.dumps({"version": "1.7.0"}))
        self.write(source / "resource" / "base" / "a.json", "new")
        self.write(source / "resource" / "base" / "b.json", "added")
        self.write(source / "interface" / "tasks" / "x.json", "{}")
        self.write(source / "config" / "config.json", "should be skipped")

        backup_dir = self.installer.state_dir / "backup" / "20261021-000000"
        stats = self.installer.sync(
            source,
            backup_dir=backup_dir,
            protected=("config",),
            managed=("resource",),
            prune=True,
            dry_run=False,
        )

        self.assertEqual(stats["new"], 2)
        self.assertEqual(stats["replaced"], 2)
        self.assertEqual(stats["removed"], 1)
        self.assertEqual(stats["same"], 0)
        self.assertEqual(json.loads(self.read(self.install_dir / "interface.json"))["version"], "1.7.0")
        self.assertEqual(self.read(self.install_dir / "resource" / "base" / "a.json"), "new")
        self.assertEqual(self.read(self.install_dir / "resource" / "base" / "b.json"), "added")
        self.assertFalse((self.install_dir / "resource" / "base" / "stale.json").exists())
        self.assertTrue((backup_dir / "resource" / "base" / "stale.json").is_file())
        self.assertEqual(self.read(backup_dir / "resource" / "base" / "a.json"), "old")
        self.assertEqual(self.read(self.install_dir / "config" / "config.json"), "user")

    def test_sync_is_idempotent(self) -> None:
        source = self.root / "source"
        self.write(source / "interface.json", json.dumps({"version": "1.7.0"}))
        self.write(source / "resource" / "base" / "a.json", "new")
        self.installer.sync(
            source,
            backup_dir=None,
            protected=("config",),
            managed=("resource",),
            prune=True,
            dry_run=False,
        )

        stats = self.installer.sync(
            source,
            backup_dir=None,
            protected=("config",),
            managed=("resource",),
            prune=True,
            dry_run=False,
        )

        self.assertEqual(stats["new"], 0)
        self.assertEqual(stats["replaced"], 0)
        self.assertEqual(stats["removed"], 0)
        self.assertEqual(stats["same"], 2)

    def test_dry_run_changes_nothing(self) -> None:
        self.write(self.install_dir / "resource" / "base" / "stale.json", "stale")
        source = self.root / "source"
        self.write(source / "interface.json", json.dumps({"version": "1.7.0"}))

        stats = self.installer.sync(
            source,
            backup_dir=None,
            protected=("config",),
            managed=("resource",),
            prune=True,
            dry_run=True,
        )

        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["removed"], 1)
        self.assertFalse((self.install_dir / "interface.json").exists())
        self.assertTrue((self.install_dir / "resource" / "base" / "stale.json").exists())

    def test_restore_returns_backed_up_files(self) -> None:
        self.write(self.install_dir / "interface.json", json.dumps({"version": "0.9.5"}))
        self.write(self.install_dir / "resource" / "base" / "stale.json", "stale")
        source = self.root / "source"
        self.write(source / "interface.json", json.dumps({"version": "1.7.0"}))

        backup_dir = self.installer.state_dir / "backup" / "20261021-000000"
        self.installer.sync(
            source,
            backup_dir=backup_dir,
            protected=("config",),
            managed=("resource",),
            prune=True,
            dry_run=False,
        )
        mss_update.restore(self.installer, "latest")

        self.assertEqual(json.loads(self.read(self.install_dir / "interface.json"))["version"], "0.9.5")
        self.assertTrue((self.install_dir / "resource" / "base" / "stale.json").is_file())

    def test_read_version_prefers_interface_then_state(self) -> None:
        self.assertEqual(self.installer.read_version(), "")

        self.write(self.install_dir / "interface.json", json.dumps({"version": "v1.7.0"}))
        self.assertEqual(self.installer.read_version(), "v1.7.0")

        (self.install_dir / "interface.json").unlink()
        self.installer.write_state(version="1.6.0")
        self.assertEqual(self.installer.read_version(), "1.6.0")


if __name__ == "__main__":
    unittest.main()
