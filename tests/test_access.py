"""Access-gate tests: only ADMIN_IDS may interact with the bot.

Hits dispatch with mock updates and patches the outgoing _tg call so we
can assert what (if anything) the bot would have sent back.
"""
from unittest.mock import patch

import api.telegram as tg


ADMIN = next(iter(tg.ADMIN_IDS))
RANDOM = 999999999  # not in ADMIN_IDS


def _update_message(user_id: int, chat_id: int = 100, text: str = "/menu") -> dict:
    return {
        "message": {
            "from": {"id": user_id},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        }
    }


def _update_callback(user_id: int, chat_id: int = 100, data: str = "menu") -> dict:
    return {
        "callback_query": {
            "id": "cb-1",
            "from": {"id": user_id},
            "message": {
                "message_id": 1,
                "chat": {"id": chat_id, "type": "private"},
            },
            "data": data,
        }
    }


# --- _from_user_id ---------------------------------------------------------

def test_from_user_id_message():
    assert tg._from_user_id(_update_message(42)) == 42


def test_from_user_id_callback():
    assert tg._from_user_id(_update_callback(42)) == 42


def test_from_user_id_missing():
    assert tg._from_user_id({}) is None


# --- is_admin --------------------------------------------------------------

def test_is_admin_true_for_listed():
    assert tg.is_admin(ADMIN) is True


def test_is_admin_false_for_random():
    assert tg.is_admin(RANDOM) is False


def test_is_admin_false_for_none():
    assert tg.is_admin(None) is False


# --- dispatch gate ---------------------------------------------------------

def test_non_admin_message_gets_denial_and_no_handling():
    with patch.object(tg, "_tg") as mock_tg, \
         patch.object(tg, "handle_callback") as mock_cb, \
         patch.object(tg, "_handle_start") as mock_start:
        tg.dispatch(_update_message(RANDOM, text="/start"))
        # No business-logic handler ran:
        mock_cb.assert_not_called()
        mock_start.assert_not_called()
        # One denial sendMessage went out:
        sent = [c for c in mock_tg.mock_calls if c.args and c.args[0] == "sendMessage"]
        assert len(sent) == 1
        assert "приватный" in sent[0].kwargs["text"].lower()


def test_non_admin_callback_gets_toast_and_no_handling():
    with patch.object(tg, "_tg") as mock_tg, \
         patch.object(tg, "handle_callback") as mock_cb:
        tg.dispatch(_update_callback(RANDOM, data="src:skills:menu"))
        mock_cb.assert_not_called()
        # answerCallbackQuery fired with 'private' toast:
        answers = [
            c for c in mock_tg.mock_calls
            if c.args and c.args[0] == "answerCallbackQuery"
        ]
        assert len(answers) == 1
        assert "приватный" in answers[0].kwargs.get("text", "").lower()


def test_non_admin_deep_link_denied():
    """t.me/<bot>?start=item_<uid> from a random user must NOT open the detail."""
    with patch.object(tg, "_tg") as mock_tg, \
         patch.object(tg, "find_item_anywhere") as mock_find:
        tg.dispatch(_update_message(RANDOM, text="/start item_abc12345"))
        mock_find.assert_not_called()
        # Only denial went out
        sent = [c for c in mock_tg.mock_calls if c.args and c.args[0] == "sendMessage"]
        assert len(sent) == 1
        assert "приватный" in sent[0].kwargs["text"].lower()


def test_admin_message_passes_gate():
    with patch.object(tg, "deliver") as mock_deliver, \
         patch.object(tg, "_handle_start") as mock_start:
        tg.dispatch(_update_message(ADMIN, text="/menu"))
        # _handle_start was called once → gate passed
        assert mock_start.called


def test_admin_callback_passes_gate():
    with patch.object(tg, "handle_callback") as mock_cb:
        tg.dispatch(_update_callback(ADMIN, data="src:skills:menu"))
        mock_cb.assert_called_once()


# --- env override ----------------------------------------------------------

def test_parse_admin_ids_handles_whitespace_and_garbage():
    assert tg._parse_admin_ids("111, 222 ,not-a-number, 333") == {111, 222, 333}


def test_parse_admin_ids_empty():
    assert tg._parse_admin_ids("") == set()
    assert tg._parse_admin_ids("   ") == set()
