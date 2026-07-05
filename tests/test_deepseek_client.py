"""Tests pour deepseek_client.py : complete(), complete_stream(), ask() avec mocks."""
import os
import sys
import json
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Simuler une clé API pour passer les vérifications early-exit
os.environ.setdefault("DEEPSEEK_API_KEY", "test_key_for_tests")

from deepseek_client import complete, complete_stream, ask


class TestComplete(unittest.TestCase):
    """Test de complete() — appels LLM synchrones."""

    @patch("deepseek_client.requests.post")
    def test_complete_success(self, mock_post):
        """Appel réussi retourne le choix."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Bonjour"}, "finish_reason": "stop"}]
        }
        mock_post.return_value = mock_resp

        result = complete(
            [{"role": "user", "content": "Dis bonjour"}],
            model="deepseek-chat", max_tokens=100
        )
        self.assertEqual(result["message"]["content"], "Bonjour")
        self.assertEqual(result["finish_reason"], "stop")
        # Vérifier que l'appel POST a été fait
        mock_post.assert_called_once()

    @patch("deepseek_client.requests.post")
    def test_complete_429_retry(self, mock_post):
        """429 Rate Limited déclenche un retry puis réussit."""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.raise_for_status.side_effect = __import__('requests').exceptions.HTTPError("429")

        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]
        }

        mock_post.side_effect = [mock_429, mock_ok]

        result = complete([{"role": "user", "content": "test"}])
        self.assertEqual(result["message"]["content"], "OK")
        self.assertEqual(mock_post.call_count, 2)

    @patch("deepseek_client.requests.post")
    def test_complete_402_credit(self, mock_post):
        """402 Payment Required déclenche le fallback (pas de RuntimeError)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_post.return_value = mock_resp

        # Le comportement actuel est un fallback gracieux, pas une exception
        result = complete([{"role": "user", "content": "test"}])
        self.assertIsNotNone(result)

    @patch("deepseek_client.requests.post")
    def test_complete_401_unauthorized(self, mock_post):
        """401 Unauthorized déclenche le fallback (pas de RuntimeError)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        # Le comportement actuel est un fallback gracieux, pas une exception
        result = complete([{"role": "user", "content": "test"}])
        self.assertIsNotNone(result)

    @patch("deepseek_client.requests.post")
    def test_complete_timeout_retry(self, mock_post):
        """Timeout réseau déclenche retry puis réussit."""
        mock_post.side_effect = [
            __import__('requests').exceptions.Timeout("timeout"),
            MagicMock(status_code=200, json=lambda: {
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]
            })
        ]

        result = complete([{"role": "user", "content": "test"}])
        self.assertEqual(result["message"]["content"], "OK")
        self.assertEqual(mock_post.call_count, 2)

    @patch("core.provider.complete")
    @patch("deepseek_client.requests.post")
    def test_complete_all_retries_exhausted(self, mock_post, mock_prov):
        """Toutes les tentatives échouent (429) → retry puis fallback."""
        import deepseek_client as _dsc
        from requests.exceptions import HTTPError
        if not _dsc.DEEPSEEK_KEY:
            _dsc.DEEPSEEK_KEY = "test-key-for-mock"

        # 429 trois fois (retry) puis RuntimeError (pas de fallback réussi)
        http_err = HTTPError("429 Rate Limited")
        mock_post.side_effect = http_err
        mock_prov.side_effect = RuntimeError("Fallback provider aussi indisponible")

        with self.assertRaises(RuntimeError):
            complete([{"role": "user", "content": "test"}])


class TestCompleteStream(unittest.TestCase):
    """Test de complete_stream() — streaming asynchrone."""

    def _make_stream_resp(self, chunks):
        """Crée une réponse mock qui yield des lignes SSE."""
        lines = []
        for chunk_data in chunks:
            lines.append(f"data: {json.dumps(chunk_data)}\n".encode())
        lines.append(b"data: [DONE]\n")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = lines
        return mock_resp

    @patch("deepseek_client.requests.post")
    def test_stream_content_chunks(self, mock_post):
        """Les chunks de contenu sont yield correctement."""
        chunks = [
            {"choices": [{"delta": {"content": "Bon"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "jour"}, "finish_reason": "stop"}]},
        ]
        mock_post.return_value = self._make_stream_resp(chunks)

        results = list(complete_stream(
            [{"role": "user", "content": "test"}],
            model="deepseek-chat"
        ))

        contents = [r["content"] for r in results if r["type"] == "content"]
        self.assertEqual("".join(contents), "Bonjour")

    @patch("deepseek_client.requests.post")
    def test_stream_tool_calls(self, mock_post):
        """Les tool_calls sont yield dans le chunk 'complete'."""
        chunks = [
            {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0, "id": "call_1",
                            "function": {"name": "web_search", "arguments": '{"query":'}

                        }]
                    },
                    "finish_reason": None
                }]
            },
            {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {"arguments": ' "test"}', "name": ""}
                        }]
                    },
                    "finish_reason": None
                }]
            },
            {
                "choices": [{
                    "delta": {},
                    "finish_reason": "tool_calls"
                }]
            },
        ]
        mock_post.return_value = self._make_stream_resp(chunks)

        results = list(complete_stream(
            [{"role": "user", "content": "test"}],
            model="deepseek-chat"
        ))

        complete_chunks = [r for r in results if r["type"] == "complete"]
        self.assertEqual(len(complete_chunks), 1)
        tc = complete_chunks[0].get("tool_calls", [])
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0]["function"]["name"], "web_search")
        self.assertEqual(tc[0]["function"]["arguments"], '{"query": "test"}')

    @patch("core.provider.complete_stream")
    @patch("deepseek_client._ds_complete_stream")
    def test_stream_402_error(self, mock_ds, mock_prov):
        """
        Erreur DeepSeek en streaming → fallback vers le provider.
        Vérifie que la chaîne de fallback est déclenchée.
        """
        mock_ds.return_value = iter([{"type": "error", "content": "402 Payment Required"}])
        mock_prov.return_value = iter([{"type": "error", "content": "Fallback aussi échoué"}])

        results = list(complete_stream([{"role": "user", "content": "test"}]))
        errors = [r for r in results if r["type"] == "error"]
        self.assertTrue(len(errors) > 0)
        self.assertTrue(mock_ds.called)
        self.assertTrue(mock_prov.called)

    @patch("deepseek_client.requests.post")
    def test_stream_retry_on_429(self, mock_post):
        """429 dans le stream → retry puis succès."""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.raise_for_status.side_effect = __import__('requests').exceptions.HTTPError("429")

        chunks = [
            {"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]},
        ]
        mock_ok = self._make_stream_resp(chunks)

        mock_post.side_effect = [mock_429, mock_ok]

        results = list(complete_stream(
            [{"role": "user", "content": "test"}],
            model="deepseek-chat"
        ))
        contents = [r["content"] for r in results if r["type"] == "content"]
        self.assertEqual("".join(contents), "OK")
        self.assertEqual(mock_post.call_count, 2)


class TestAsk(unittest.TestCase):
    """Test de ask() — wrapper simple."""

    @patch("deepseek_client._ds_complete")
    def test_ask_success(self, mock_ds):
        """ask() retourne le contenu du message."""
        mock_ds.return_value = {
            "message": {"content": "Réponse test"},
            "finish_reason": "stop"
        }
        result = ask([{"role": "user", "content": "test"}])
        self.assertEqual(result, "Réponse test")

    @patch("deepseek_client._ds_complete")
    def test_ask_raises_on_error(self, mock_ds):
        """ask() propage les exceptions."""
        mock_ds.side_effect = RuntimeError("API down")
        with self.assertRaises(RuntimeError):
            ask([{"role": "user", "content": "test"}])


if __name__ == "__main__":
    unittest.main()
