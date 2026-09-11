import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from zd.cli import cli, client
from zd.client import ZendeskClient, ZendeskError


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        self.config = patch("zd.cli._ensure_config")
        self.config.start()
        self.locales = patch.object(
            client,
            "list_locales",
            return_value={"locales": ["zh-cn", "en-us", "ja-jp"]},
        )
        self.locales.start()
        self.addCleanup(self.config.stop)
        self.addCleanup(self.locales.stop)

    def test_create_each_kind_as_draft(self):
        for kind in ["articles", "categories", "sections"]:
            with (
                self.subTest(kind=kind),
                patch.object(client, "create_translation") as create,
            ):
                result = self.runner.invoke(
                    cli,
                    [
                        "kb",
                        "translations",
                        "create",
                        kind,
                        "42",
                        "--locale",
                        "ja-jp",
                        "--title",
                        "通知",
                        "--body",
                        "本文",
                        "-y",
                    ],
                )
                self.assertEqual(result.exit_code, 0, result.output)
                create.assert_called_once_with(
                    kind, 42, "ja-jp", "通知", body="本文", draft=True
                )

    def test_create_file_published(self):
        with self.runner.isolated_filesystem():
            with open("body.html", "w") as f:
                f.write("<p>English</p>")
            with patch.object(client, "create_translation") as create:
                result = self.runner.invoke(
                    cli,
                    [
                        "kb",
                        "translations",
                        "create",
                        "articles",
                        "42",
                        "--locale",
                        "en-us",
                        "--title",
                        "Notice",
                        "-f",
                        "body.html",
                        "--publish",
                        "-y",
                    ],
                )
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(
                    create.call_args.kwargs, {"body": "<p>English</p>", "draft": False}
                )

    def test_edit_preserves_unspecified_fields(self):
        with patch.object(client, "edit_translation") as edit:
            result = self.runner.invoke(
                cli,
                [
                    "kb",
                    "translations",
                    "edit",
                    "categories",
                    "42",
                    "--locale",
                    "en-us",
                    "--title",
                    "Notice",
                    "-y",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            edit.assert_called_once_with("categories", 42, "en-us", title="Notice")

    def test_publish_only(self):
        with patch.object(client, "edit_translation") as edit:
            result = self.runner.invoke(
                cli,
                [
                    "kb",
                    "translations",
                    "edit",
                    "articles",
                    "42",
                    "--locale",
                    "en-us",
                    "--publish",
                    "-y",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            edit.assert_called_once_with("articles", 42, "en-us", draft=False)

    def test_cancel_does_not_write(self):
        with patch.object(client, "create_translation") as create:
            result = self.runner.invoke(
                cli,
                [
                    "kb",
                    "translations",
                    "create",
                    "articles",
                    "42",
                    "--locale",
                    "en-us",
                    "--title",
                    "Notice",
                ],
                input="n\n",
            )
            self.assertEqual(result.exit_code, 0)
            create.assert_not_called()

    def test_invalid_input_does_not_write(self):
        for args in [
            ["create", "--locale", "en-us"],
            ["create", "--locale", "en-us", "--title", "  "],
            ["create", "--locale", "fr", "--title", "Notice"],
            ["edit", "--locale", "en-us"],
        ]:
            with (
                self.subTest(args=args),
                patch.object(client, "create_translation") as create,
                patch.object(client, "edit_translation") as edit,
            ):
                result = self.runner.invoke(
                    cli,
                    ["kb", "translations", args[0], "articles", "42", *args[1:], "-y"],
                )
                self.assertEqual(result.exit_code, 2, result.output)
                create.assert_not_called()
                edit.assert_not_called()

    def test_body_file_conflict(self):
        with self.runner.isolated_filesystem():
            open("body.html", "w").close()
            with patch.object(client, "create_translation") as create:
                result = self.runner.invoke(
                    cli,
                    [
                        "kb",
                        "translations",
                        "create",
                        "articles",
                        "42",
                        "--locale",
                        "en-us",
                        "--title",
                        "Notice",
                        "--body",
                        "a",
                        "-f",
                        "body.html",
                        "-y",
                    ],
                )
                self.assertEqual(result.exit_code, 2)
                create.assert_not_called()

    def test_server_error_is_failure(self):
        with patch.object(
            client,
            "create_translation",
            side_effect=ZendeskError(422, "Already exists"),
        ):
            result = self.runner.invoke(
                cli,
                [
                    "kb",
                    "translations",
                    "create",
                    "articles",
                    "42",
                    "--locale",
                    "en-us",
                    "--title",
                    "Notice",
                    "-y",
                ],
            )
            self.assertEqual(result.exit_code, 1)
            self.assertNotIn("翻译已保存", result.output)

    def test_list_reports_locales_and_states(self):
        data = {"translations": [{"locale": "ja-jp", "draft": False}]}
        with patch.object(client, "list_translations", return_value=data):
            result = self.runner.invoke(
                cli, ["kb", "translations", "list", "articles", "42"]
            )
            self.assertEqual(json.loads(result.output), data)

    def test_client_routes_and_payloads(self):
        api = ZendeskClient()
        for kind in ["articles", "categories", "sections"]:
            with (
                self.subTest(kind=kind),
                patch.object(api, "_post") as post,
                patch.object(api, "_put") as put,
            ):
                api.create_translation(kind, 42, "ja-jp", "通知", "本文")
                post.assert_called_once_with(
                    f"help_center/{kind}/42/translations",
                    {
                        "translation": {
                            "locale": "ja-jp",
                            "title": "通知",
                            "body": "本文",
                            "draft": True,
                        }
                    },
                )
                api.edit_translation(kind, 42, "ja-jp", draft=False)
                put.assert_called_once_with(
                    f"help_center/{kind}/42/translations/ja-jp",
                    {"translation": {"draft": False}},
                )
        with self.assertRaises(ValueError):
            api.list_translations("tickets", 42)
