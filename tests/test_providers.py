from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zotero_connector_cli.ebsco import (
    build_ebsco_search_url,
    build_search_url,
    matches_pdf_access_control,
)
from zotero_connector_cli.providers import (
    BUILTIN_PROVIDERS,
    CONFIG_ENV,
    DEFAULT_ENV,
    FALLBACK_PROVIDER,
    UTWENTE_EBSCO,
    Provider,
    ProviderError,
    load_providers,
    provider_from_dict,
    resolve_provider,
)

OTHER = {
    "searchBase": "https://research-ebsco-com.ezproxy.example.edu/c/abcdef/search/advanced-results",
    "databases": "bth,eric",
    "accessControlPrefix": "download pdf",
    "description": "Example University",
}


def config_file(directory, providers, default=None):
    payload = {"providers": providers}
    if default is not None:
        payload["default"] = default
    path = Path(directory) / "providers.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class BuiltinTests(unittest.TestCase):
    def test_the_ut_route_survives_as_one_named_provider(self):
        # It is a tested configuration, not the only thing the package knows.
        self.assertIn("utwente-ebsco", BUILTIN_PROVIDERS)
        self.assertIn("ezproxy2.utwente.nl", UTWENTE_EBSCO.search_base)

    def test_the_ut_search_url_is_unchanged_by_the_refactor(self):
        url = build_ebsco_search_url("Dynamic Routing under Uncertainty")

        self.assertIn("research-ebsco-com.ezproxy2.utwente.nl", url)
        self.assertIn("q=Dynamic+Routing+under+Uncertainty", url)
        self.assertIn("searchMode=boolean", url)
        self.assertIn("db=bth%2Cnlebk", url)

    def test_a_provider_without_databases_omits_the_parameter(self):
        provider = Provider(name="bare", search_base="https://example.org/search")

        url = build_search_url(provider, "A Title")

        self.assertNotIn("db=", url)
        self.assertIn("q=A+Title", url)


class ConfigTests(unittest.TestCase):
    def test_a_file_adds_providers_alongside_the_builtins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = config_file(directory, {"example-ebsco": OTHER})
            providers, declared = load_providers(path)

        self.assertIn("example-ebsco", providers)
        self.assertIn("utwente-ebsco", providers)
        self.assertIsNone(declared)
        self.assertEqual(providers["example-ebsco"].access_control_prefix, "download pdf")

    def test_a_file_entry_may_correct_a_builtin_without_forking_the_package(self):
        with tempfile.TemporaryDirectory() as directory:
            path = config_file(directory, {"utwente-ebsco": OTHER})
            providers, _ = load_providers(path)

        self.assertIn("example.edu", providers["utwente-ebsco"].search_base)

    def test_a_missing_file_named_explicitly_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ProviderError, "not found"):
                load_providers(Path(directory) / "absent.json")

    def test_a_missing_default_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {CONFIG_ENV: str(Path(directory) / "absent.json")}):
                providers, declared = load_providers()

        self.assertEqual(set(providers), set(BUILTIN_PROVIDERS))
        self.assertIsNone(declared)

    def test_malformed_json_says_so(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "providers.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ProviderError, "not valid JSON"):
                load_providers(path)

    def test_a_file_with_no_providers_object_says_so(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "providers.json"
            path.write_text(json.dumps({"default": "x"}), encoding="utf-8")
            with self.assertRaisesRegex(ProviderError, "no 'providers' object"):
                load_providers(path)

    def test_a_default_the_file_does_not_define_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = config_file(directory, {"example-ebsco": OTHER}, default="typo")
            with self.assertRaisesRegex(ProviderError, "does not define"):
                load_providers(path)


class ValidationTests(unittest.TestCase):
    def test_a_missing_search_base_is_refused(self):
        with self.assertRaisesRegex(ProviderError, "missing required key"):
            provider_from_dict("broken", {"databases": "bth"})

    def test_a_plain_http_route_is_refused_rather_than_warned_about(self):
        # An EZproxy route carries a session cookie; http would leak it.
        with self.assertRaisesRegex(ProviderError, "must be https"):
            provider_from_dict("insecure", {"searchBase": "http://example.edu/search"})

    def test_an_unknown_key_is_refused_so_a_typo_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ProviderError, "unknown key"):
            provider_from_dict(
                "typo", {"searchBase": "https://example.edu/s", "database": "bth"}
            )

    def test_a_non_object_provider_is_refused(self):
        with self.assertRaisesRegex(ProviderError, "must be an object"):
            provider_from_dict("wrong", ["https://example.edu"])

    def test_extra_query_must_be_an_object(self):
        with self.assertRaisesRegex(ProviderError, "extraQuery must be an object"):
            provider_from_dict(
                "wrong", {"searchBase": "https://example.edu/s", "extraQuery": ["a"]}
            )


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        # Resolution reads the environment, so the test's answer must not
        # depend on what the developer happens to have exported.
        cleaned = {
            key: value
            for key, value in os.environ.items()
            if key not in (CONFIG_ENV, DEFAULT_ENV)
        }
        patcher = patch.dict(os.environ, cleaned, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_explicit_name_wins_over_everything(self):
        with tempfile.TemporaryDirectory() as directory:
            path = config_file(directory, {"example-ebsco": OTHER}, default="example-ebsco")
            with patch.dict(os.environ, {DEFAULT_ENV: "utwente-ebsco"}):
                provider = resolve_provider("utwente-ebsco", path)

        self.assertEqual(provider.name, "utwente-ebsco")

    def test_the_files_declared_default_wins_over_the_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = config_file(directory, {"example-ebsco": OTHER}, default="example-ebsco")
            with patch.dict(os.environ, {DEFAULT_ENV: "utwente-ebsco"}):
                provider = resolve_provider(None, path)

        self.assertEqual(provider.name, "example-ebsco")

    def test_the_environment_is_used_when_the_file_declares_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = config_file(directory, {"example-ebsco": OTHER})
            with patch.dict(os.environ, {DEFAULT_ENV: "example-ebsco"}):
                provider = resolve_provider(None, path)

        self.assertEqual(provider.name, "example-ebsco")

    def test_an_install_that_configures_nothing_keeps_working(self):
        # The fallback is a named route, not a built-in assumption about which
        # university you are at -- but it does have to keep existing runs alive.
        with tempfile.TemporaryDirectory() as directory:
            path = config_file(directory, {"example-ebsco": OTHER})
            provider = resolve_provider(None, path)

        self.assertEqual(provider.name, FALLBACK_PROVIDER)

    def test_an_unknown_provider_lists_what_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            path = config_file(directory, {"example-ebsco": OTHER})
            with self.assertRaises(ProviderError) as caught:
                resolve_provider("nope", path)

        message = str(caught.exception)
        self.assertIn("Unknown provider", message)
        self.assertIn("example-ebsco", message)
        self.assertIn("utwente-ebsco", message)


class AccessControlTests(unittest.TestCase):
    def test_the_control_prefix_comes_from_the_provider(self):
        self.assertTrue(
            matches_pdf_access_control(
                "Button", "Download PDF Dynamic Routing", "Dynamic Routing", "download pdf"
            )
        )
        self.assertFalse(
            matches_pdf_access_control(
                "Button", "Download PDF Dynamic Routing", "Dynamic Routing", "access now pdf"
            )
        )

    def test_a_control_for_a_different_record_is_not_matched(self):
        self.assertFalse(
            matches_pdf_access_control(
                "Button", "Access now (PDF) Some Other Paper", "Dynamic Routing"
            )
        )

    def test_an_empty_prefix_never_matches_everything(self):
        self.assertFalse(
            matches_pdf_access_control("Button", "Access now (PDF) X", "X", "")
        )


if __name__ == "__main__":
    unittest.main()
