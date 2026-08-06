from __future__ import annotations

import unittest

from zotero_connector_cli.remote_fetch import (
    RemoteFetchError,
    public_remote_url,
    validate_remote_host,
    validate_remote_url,
)


class RemoteFetchTests(unittest.TestCase):
    def test_accepts_plain_ssh_target_and_https_source(self) -> None:
        self.assertEqual(
            validate_remote_host("user@remote-host"), "user@remote-host"
        )
        self.assertEqual(
            validate_remote_url("https://repository.example.edu/paper.pdf"),
            "https://repository.example.edu/paper.pdf",
        )

    def test_rejects_shell_host_and_non_https_source(self) -> None:
        with self.assertRaises(RemoteFetchError):
            validate_remote_host("remote-host; shutdown")
        with self.assertRaises(RemoteFetchError):
            validate_remote_url("http://example.edu/paper.pdf")

    def test_rejects_unauthorized_copy_sources(self) -> None:
        for url in (
            "https://libgen.li/book.pdf",
            "https://sci-hub.example/paper.pdf",
            "https://annas-archive.example/book.pdf",
        ):
            with self.subTest(url=url), self.assertRaises(RemoteFetchError):
                validate_remote_url(url)

    def test_reported_url_drops_query_and_fragment(self) -> None:
        self.assertEqual(
            public_remote_url(
                "https://repository.example.edu/paper.pdf?token=secret#page=2"
            ),
            "https://repository.example.edu/paper.pdf",
        )


if __name__ == "__main__":
    unittest.main()
