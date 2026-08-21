import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

import zd.cli as cli_module
from zd.client import REQUEST_TIMEOUT, ZendeskClient


class KnowledgeBaseClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = ZendeskClient()

    def test_create_article_uses_draft_and_notification_defaults(self) -> None:
        response = {"article": {"id": 101, "draft": True}}
        with patch.object(self.client, "_post", return_value=response) as post:
            result = self.client.create_article(
                section_id=42,
                title="安装指南",
                body="<p>正文</p>",
            )

        self.assertEqual(result, response)
        post.assert_called_once_with(
            "help_center/zh-cn/sections/42/articles",
            {
                "article": {
                    "title": "安装指南",
                    "body": "<p>正文</p>",
                    "locale": "zh-cn",
                    "draft": True,
                },
                "notify_subscribers": False,
            },
        )

    def test_create_article_includes_optional_access_and_labels(self) -> None:
        with patch.object(self.client, "_post", return_value={}) as post:
            self.client.create_article(
                section_id=42,
                title="Private",
                locale="en-us",
                draft=False,
                notify_subscribers=True,
                permission_group_id=7,
                user_segment_id=8,
                label_names=["release", "enterprise"],
            )

        post.assert_called_once_with(
            "help_center/en-us/sections/42/articles",
            {
                "article": {
                    "title": "Private",
                    "body": "",
                    "locale": "en-us",
                    "draft": False,
                    "permission_group_id": 7,
                    "user_segment_id": 8,
                    "label_names": ["release", "enterprise"],
                },
                "notify_subscribers": True,
            },
        )

    def test_edit_article_updates_translation_content(self) -> None:
        with patch.object(self.client, "_put", return_value={}) as put:
            self.client.edit_article(
                article_id=101,
                locale="ja-jp",
                title="新しいタイトル",
                body="<p>本文</p>",
            )

        put.assert_called_once_with(
            "help_center/articles/101/translations/ja-jp",
            {
                "translation": {
                    "title": "新しいタイトル",
                    "body": "<p>本文</p>",
                }
            },
        )

    def test_edit_article_requires_a_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要提供"):
            self.client.edit_article(article_id=101)

    def test_publish_article_sets_translation_draft_false(self) -> None:
        with patch.object(self.client, "_put", return_value={}) as put:
            self.client.publish_article(article_id=101, locale="en-us")

        put.assert_called_once_with(
            "help_center/articles/101/translations/en-us",
            {"translation": {"draft": False}},
        )

    def test_archive_article_accepts_empty_204_response(self) -> None:
        response = Mock(status_code=204, ok=True, content=b"", headers={})
        self.client.session = Mock()
        self.client.session.delete.return_value = response

        result = self.client.archive_article(article_id=101)

        self.assertEqual(result, {})
        self.client.session.delete.assert_called_once_with(
            f"{self.client.base_url}/help_center/articles/101",
            timeout=REQUEST_TIMEOUT,
        )


class KnowledgeBaseCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_create_command_reads_file_and_defaults_to_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            body_path = Path(tmp_dir) / "article.html"
            body_path.write_text("<p>正文</p>", encoding="utf-8")
            with (
                patch("zd.cli._ensure_config"),
                patch.object(
                    cli_module.client,
                    "create_article",
                    return_value={"article": {"id": 101}},
                ) as create,
            ):
                result = self.runner.invoke(
                    cli_module.cli,
                    ["kb", "create", "42", "安装指南", "-f", str(body_path), "-y"],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        create.assert_called_once_with(
            section_id=42,
            title="安装指南",
            body="<p>正文</p>",
            locale="zh-cn",
            draft=True,
            notify_subscribers=False,
            permission_group_id=None,
            user_segment_id=None,
            label_names=None,
        )

    def test_edit_command_rejects_missing_changes(self) -> None:
        result = self.runner.invoke(cli_module.cli, ["kb", "edit", "101"])

        self.assertEqual(result.exit_code, 2)
        self.assertIn("至少需要提供", result.output)

    def test_edit_command_updates_title_and_file_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            body_path = Path(tmp_dir) / "article.html"
            body_path.write_text("<p>新正文</p>", encoding="utf-8")
            with (
                patch("zd.cli._ensure_config"),
                patch.object(cli_module.client, "edit_article", return_value={}) as edit,
            ):
                result = self.runner.invoke(
                    cli_module.cli,
                    [
                        "kb",
                        "edit",
                        "101",
                        "--title",
                        "新标题",
                        "-f",
                        str(body_path),
                        "--locale",
                        "ja-jp",
                        "-y",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        edit.assert_called_once_with(
            article_id=101,
            locale="ja-jp",
            title="新标题",
            body="<p>新正文</p>",
        )

    def test_edit_command_rejects_body_and_file_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            body_path = Path(tmp_dir) / "article.html"
            body_path.write_text("<p>文件正文</p>", encoding="utf-8")
            result = self.runner.invoke(
                cli_module.cli,
                [
                    "kb",
                    "edit",
                    "101",
                    "--body",
                    "<p>命令行正文</p>",
                    "-f",
                    str(body_path),
                ],
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("不能同时使用", result.output)

    def test_publish_command_targets_selected_locale(self) -> None:
        with (
            patch("zd.cli._ensure_config"),
            patch.object(cli_module.client, "publish_article", return_value={}) as publish,
        ):
            result = self.runner.invoke(
                cli_module.cli,
                ["kb", "publish", "101", "--locale", "en-us", "-y"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        publish.assert_called_once_with(article_id=101, locale="en-us")

    def test_archive_command_can_be_cancelled(self) -> None:
        with (
            patch("zd.cli._ensure_config"),
            patch.object(cli_module.client, "archive_article", return_value={}) as archive,
        ):
            result = self.runner.invoke(
                cli_module.cli,
                ["kb", "archive", "101"],
                input="n\n",
            )

        self.assertEqual(result.exit_code, 0, result.output)
        archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
