"""Tests pour deepseek_client.py — wrapper vers core.provider.

deepseek_client est devenu un wrapper mince qui délègue à core.provider.
Ces tests vérifient que le wrapper appelle correctement le provider,
sans tester la logique de fallback/retry (qui est dans test_provider.py).
"""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Simuler une clé API pour passer les vérifications early-exit
os.environ.setdefault("DEEPSEEK_API_KEY", "test_key_for_tests")

from deepseek_client import complete, complete_stream, ask


class TestComplete(unittest.TestCase):
    """Test de complete() — délègue à core.provider.complete."""

    @patch("deepseek_client._provider_complete")
    def test_complete_success(self, mock_complete):
        """Appel réussi retourne le message."""
        mock_complete.return_value = {
            "message": {"content": "Bonjour"},
            "finish_reason": "stop"
        }
        result = complete(
            [{"role": "user", "content": "Dis bonjour"}],
            model="deepseek-chat", max_tokens=100
        )
        self.assertEqual(result["message"]["content"], "Bonjour")
        self.assertEqual(result["finish_reason"], "stop")
        mock_complete.assert_called_once()

    @patch("deepseek_client._provider_complete")
    def test_complete_passes_args(self, mock_complete):
        """Vérifie la transmission des arguments au provider."""
        mock_complete.return_value = {
            "message": {"content": "OK"},
            "finish_reason": "stop"
        }
        complete(
            [{"role": "user", "content": "test"}],
            model="deepseek-v4-flash", max_tokens=100, timeout=60
        )
        mock_complete.assert_called_once()
        _name, args, kwargs = mock_complete.mock_calls[0]
        self.assertEqual(kwargs.get("max_tokens"), 100)
        self.assertEqual(kwargs.get("timeout"), 60)
        self.assertEqual(kwargs.get("model"), "deepseek-v4-flash")

    @patch("deepseek_client._provider_complete")
    def test_complete_propagates_error(self, mock_complete):
        """Les exceptions du provider sont propagées par le wrapper."""
        mock_complete.side_effect = RuntimeError("Provider error")
        with self.assertRaises(RuntimeError):
            complete([{"role": "user", "content": "test"}])


class TestCompleteStream(unittest.TestCase):
    """Test de complete_stream() — wrapper vers core.provider.complete_stream."""

    @patch("deepseek_client._provider_stream")
    def test_stream_content_chunks(self, mock_stream):
        """Les chunks du provider sont yield correctement."""
        chunks = [
            {"type": "content", "content": "Bon"},
            {"type": "content", "content": "jour"},
            {"type": "complete", "content": "", "finish_reason": "stop"},
        ]
        mock_stream.return_value = iter(chunks)

        results = list(complete_stream(
            [{"role": "user", "content": "test"}],
            model="deepseek-chat"
        ))

        self.assertEqual(len(results), 3)
        contents = [r["content"] for r in results if r["type"] == "content"]
        self.assertEqual("".join(contents), "Bonjour")

    @patch("deepseek_client._provider_stream")
    def test_stream_propagates_error(self, mock_stream):
        """Les erreurs du provider sont propagées."""
        mock_stream.side_effect = RuntimeError("Stream error")

        with self.assertRaises(RuntimeError):
            for _ in complete_stream([{"role": "user", "content": "test"}]):
                pass

    @patch("deepseek_client._provider_stream")
    def test_stream_passes_tools(self, mock_stream):
        """Les outils sont transmis au provider."""
        mock_stream.return_value = iter([])
        tools = [{"type": "function", "function": {"name": "web_search"}}]
        list(complete_stream(
            [{"role": "user", "content": "test"}],
            tools=tools, tool_choice="auto"
        ))
        mock_stream.assert_called_once()
        _name, args, kwargs = mock_stream.mock_calls[0]
        self.assertEqual(kwargs.get("tools"), tools)
        self.assertEqual(kwargs.get("tool_choice"), "auto")


class TestAsk(unittest.TestCase):
    """Test de ask() — helper one-shot qui appelle complete()."""

    @patch("deepseek_client._provider_complete")
    def test_ask_string_prompt(self, mock_complete):
        """ask() avec prompt string appelle complete avec messages."""
        mock_complete.return_value = {
            "message": {"content": "Réponse test"},
            "finish_reason": "stop"
        }
        result = ask("Dis bonjour")
        self.assertEqual(result, "Réponse test")
        mock_complete.assert_called_once()
        _name, args, kwargs = mock_complete.mock_calls[0]
        self.assertEqual(len(args[0]), 1)
        self.assertEqual(args[0][0]["role"], "user")

    @patch("deepseek_client._provider_complete")
    def test_ask_with_system(self, mock_complete):
        """ask() avec système ajoute un message system."""
        mock_complete.return_value = {
            "message": {"content": "OK"},
            "finish_reason": "stop"
        }
        result = ask("test", system="Sois concis")
        self.assertEqual(result, "OK")
        mock_complete.assert_called_once()
        _name, args, kwargs = mock_complete.mock_calls[0]
        self.assertEqual(len(args[0]), 2)
        self.assertEqual(args[0][0]["role"], "system")

    @patch("deepseek_client._provider_complete")
    def test_ask_list_messages(self, mock_complete):
        """ask() accepte directement une liste de messages."""
        mock_complete.return_value = {
            "message": {"content": "OK"},
            "finish_reason": "stop"
        }
        messages = [{"role": "user", "content": "test"}]
        result = ask(messages)
        self.assertEqual(result, "OK")
        mock_complete.assert_called_once()
        _name, args, kwargs = mock_complete.mock_calls[0]
        self.assertIs(args[0], messages)

    @patch("deepseek_client._provider_complete")
    def test_ask_raises_on_error(self, mock_complete):
        """ask() propage les exceptions du provider."""
        mock_complete.side_effect = RuntimeError("API down")
        with self.assertRaises(RuntimeError):
            ask("test")


if __name__ == "__main__":
    unittest.main()
