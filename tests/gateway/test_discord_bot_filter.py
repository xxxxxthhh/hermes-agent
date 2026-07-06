"""Tests for Discord bot message filtering (DISCORD_ALLOW_BOTS)."""

import os
import re
import unittest
from unittest.mock import MagicMock, patch


def _make_author(*, bot: bool = False, is_self: bool = False):
    """Create a mock Discord author."""
    author = MagicMock()
    author.bot = bot
    author.id = 99999 if is_self else 12345
    author.name = "TestBot" if bot else "TestUser"
    author.display_name = author.name
    return author


def _make_message(*, author=None, content="hello", mentions=None, raw_mentions=None, is_dm=False, message_type=None):
    """Create a mock Discord message."""
    msg = MagicMock()
    msg.author = author or _make_author()
    msg.content = content
    msg.attachments = []
    msg.mentions = mentions or []
    if raw_mentions is None:
        raw_mentions = [
            getattr(m, "id", m)
            for m in msg.mentions
            if str(getattr(m, "id", m)) in content
        ]
    msg.raw_mentions = raw_mentions
    if message_type is None:
        import discord
        message_type = discord.MessageType.default
    msg.type = message_type
    if is_dm:
        import discord
        msg.channel = MagicMock(spec=discord.DMChannel)
        msg.channel.id = 111
    else:
        msg.channel = MagicMock()
        msg.channel.id = 222
        msg.channel.name = "test-channel"
        msg.channel.guild = MagicMock()
        msg.channel.guild.name = "TestServer"
        # Make isinstance checks fail for DMChannel and Thread
        type(msg.channel).__name__ = "TextChannel"
    return msg


class TestDiscordBotFilter(unittest.TestCase):
    """Test the DISCORD_ALLOW_BOTS filtering logic."""

    @staticmethod
    def _self_is_explicitly_mentioned(message, client_user):
        """Mirror adapter._self_is_explicitly_mentioned: resolved or raw mention."""
        if not client_user:
            return False
        if client_user in message.mentions:
            return True
        raw_ids = {
            m.group(1)
            for m in re.finditer(r"<@!?(\d+)>", getattr(message, "content", "") or "")
        }
        return str(client_user.id) in raw_ids

    @staticmethod
    def _self_is_raw_mentioned(message, client_user):
        """Mirror adapter._self_is_raw_mentioned: raw inline token only."""
        if not client_user:
            return False
        raw_ids = {
            m.group(1)
            for m in re.finditer(r"<@!?(\d+)>", getattr(message, "content", "") or "")
        }
        return str(client_user.id) in raw_ids

    def _run_filter(
        self,
        message,
        allow_bots="none",
        client_user=None,
        bots_require_inline_mention=False,
    ):
        """Simulate the on_message filter logic and return whether message was accepted."""
        # Replicate the exact filter logic from discord.py on_message
        if message.author == client_user:
            return False  # own messages always ignored

        # Ignore Discord system messages (only default and reply allowed)
        import discord
        if message.type not in {discord.MessageType.default, discord.MessageType.reply, None}:
            return False

        if getattr(message.author, "bot", False):
            allow = allow_bots.lower().strip()
            if allow == "none":
                return False
            import discord
            is_dm_channel = isinstance(message.channel, discord.DMChannel)
            raw_self_mentioned = self._self_is_raw_mentioned(message, client_user)
            if not is_dm_channel and not raw_self_mentioned:
                return False
            if allow == "mentions" and not self._self_is_explicitly_mentioned(message, client_user):
                return False
            if bots_require_inline_mention and not raw_self_mentioned:
                return False
            if message.type == discord.MessageType.reply and not raw_self_mentioned:
                return False

        return True  # message accepted

    def test_own_messages_always_ignored(self):
        """Bot's own messages are always ignored regardless of allow_bots."""
        bot_user = _make_author(is_self=True)
        msg = _make_message(author=bot_user)
        self.assertFalse(self._run_filter(msg, "all", bot_user))

    def test_human_messages_always_accepted(self):
        """Human messages are always accepted regardless of allow_bots."""
        human = _make_author(bot=False)
        msg = _make_message(author=human)
        self.assertTrue(self._run_filter(msg, "none"))
        self.assertTrue(self._run_filter(msg, "mentions"))
        self.assertTrue(self._run_filter(msg, "all"))

    def test_allow_bots_none_rejects_bots(self):
        """With allow_bots=none, all other bot messages are rejected."""
        bot = _make_author(bot=True)
        msg = _make_message(author=bot)
        self.assertFalse(self._run_filter(msg, "none"))

    def test_allow_bots_all_accepts_dm_bots_without_self_mention(self):
        """With allow_bots=all, bot DMs are accepted without @mention."""
        bot = _make_author(bot=True)
        msg = _make_message(author=bot, mentions=[], is_dm=True)
        self.assertTrue(self._run_filter(msg, "all"))

    def test_allow_bots_all_rejects_channel_bot_message_without_self_mention(self):
        """Even allow_bots=all must not accept ambient bot messages in shared channels."""
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(author=bot, mentions=[], is_dm=False)
        self.assertFalse(self._run_filter(msg, "all", our_user))

    def test_allow_bots_all_rejects_reply_ping_without_explicit_content_mention(self):
        """Discord reply-pings must not count as explicit bot-to-bot mentions."""
        import discord
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(
            author=bot,
            content="负例测试：这条消息没有 explicit bot mention",
            mentions=[our_user],
            raw_mentions=[],
            is_dm=False,
            message_type=discord.MessageType.reply,
        )
        self.assertFalse(self._run_filter(msg, "all", our_user))

    def test_allow_bots_mentions_rejects_without_mention(self):
        """With allow_bots=mentions, bot messages without @mention are rejected."""
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(author=bot, mentions=[])
        self.assertFalse(self._run_filter(msg, "mentions", our_user))

    def test_allow_bots_mentions_accepts_with_mention(self):
        """With allow_bots=mentions, bot messages with @mention are accepted."""
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(author=bot, content=f"<@{our_user.id}> hello", mentions=[our_user])
        self.assertTrue(self._run_filter(msg, "mentions", our_user))

    def test_allow_bots_all_accepts_channel_bot_message_with_explicit_raw_mention(self):
        """With allow_bots=all, shared-channel bot messages with explicit self mention are accepted."""
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(
            author=bot,
            content=f"<@{our_user.id}> default message with explicit mention",
            mentions=[our_user],
            is_dm=False,
        )
        self.assertTrue(self._run_filter(msg, "all", our_user))

    def test_allow_bots_mentions_accepts_with_raw_content_mention(self):
        """Raw <@!ID> mention counts even when message.mentions is empty."""
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(author=bot, content=f"<@!{our_user.id}> relay", mentions=[])
        self.assertTrue(self._run_filter(msg, "mentions", our_user))

    def test_inline_mention_requirement_off_still_rejects_reply_ping_only(self):
        """Our shared-channel bot gate rejects reply-ping-only bot messages by default."""
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(author=bot, content="reply-ping only", mentions=[our_user])

        self.assertFalse(
            self._run_filter(
                msg,
                "all",
                our_user,
                bots_require_inline_mention=False,
            )
        )

    def test_inline_mention_requirement_rejects_reply_ping_only(self):
        """Opt-in guard also rejects bot messages where only Discord's reply-ping mentions us."""
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(author=bot, content="reply-ping only", mentions=[our_user])

        self.assertFalse(
            self._run_filter(
                msg,
                "all",
                our_user,
                bots_require_inline_mention=True,
            )
        )

    def test_inline_mention_requirement_accepts_body_mention(self):
        """Opt-in guard still admits intentional inline cross-bot mentions."""
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(
            author=bot,
            content=f"<@{our_user.id}> intentional handoff",
            mentions=[our_user],
        )

        self.assertTrue(
            self._run_filter(
                msg,
                "all",
                our_user,
                bots_require_inline_mention=True,
            )
        )

    def test_inline_mention_requirement_does_not_affect_humans(self):
        """The opt-in guard only applies to bot-authored messages."""
        human = _make_author(bot=False)
        our_user = _make_author(is_self=True)
        msg = _make_message(author=human, content="human reply-ping", mentions=[our_user])

        self.assertTrue(
            self._run_filter(
                msg,
                "none",
                our_user,
                bots_require_inline_mention=True,
            )
        )

    def test_default_is_none(self):
        """Document the adapter's code default when no env override is set."""
        with patch.dict(os.environ, {}, clear=True):
            default = os.getenv("DISCORD_ALLOW_BOTS", "none")
        self.assertEqual(default, "none")

    def test_case_insensitive(self):
        """Allow_bots value should be case-insensitive."""
        bot = _make_author(bot=True)
        our_user = _make_author(is_self=True)
        msg = _make_message(author=bot, content=f"<@{our_user.id}> hello", mentions=[our_user])
        self.assertTrue(self._run_filter(msg, "ALL", our_user))
        self.assertTrue(self._run_filter(msg, "All", our_user))
        self.assertFalse(self._run_filter(msg, "NONE"))
        self.assertFalse(self._run_filter(msg, "None"))


    def test_allow_bots_all_rejects_bot_reply_without_self_mention(self):
        """With allow_bots=all, ambient bot reply messages are dropped."""
        import discord
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(author=bot, mentions=[], message_type=discord.MessageType.reply)
        self.assertFalse(self._run_filter(msg, "all", our_user))

    def test_allow_bots_mentions_accepts_bot_reply_with_self_mention(self):
        """Bot reply messages are accepted when they explicitly @mention us."""
        import discord
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(
            author=bot,
            content=f"<@{our_user.id}> reply with explicit mention",
            mentions=[our_user],
            message_type=discord.MessageType.reply,
        )
        self.assertTrue(self._run_filter(msg, "mentions", our_user))

    def test_allow_bots_all_accepts_bot_reply_with_explicit_raw_mention(self):
        """With allow_bots=all, bot replies with explicit body self mention are accepted."""
        import discord
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(
            author=bot,
            content=f"<@{our_user.id}> reply with explicit mention",
            mentions=[our_user],
            is_dm=False,
            message_type=discord.MessageType.reply,
        )
        self.assertTrue(self._run_filter(msg, "all", our_user))

    def test_allow_bots_mentions_rejects_bot_reply_without_self_mention(self):
        """Bot reply messages without explicit self mention are still dropped."""
        import discord
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(
            author=bot,
            mentions=[],
            message_type=discord.MessageType.reply,
        )
        self.assertFalse(self._run_filter(msg, "mentions", our_user))

    def test_human_reply_not_rejected(self):
        """Human reply messages are not dropped by the anti-loop guard."""
        import discord
        human = _make_author(bot=False)
        msg = _make_message(author=human, message_type=discord.MessageType.reply)
        self.assertTrue(self._run_filter(msg, "all"))

    def test_substantive_bot_default_message_with_mention_is_accepted(self):
        """Substantive default bot messages with self mention still support bot-to-bot review."""
        our_user = _make_author(is_self=True)
        bot = _make_author(bot=True)
        msg = _make_message(
            author=bot,
            content=f"<@{our_user.id}> PR #123 is ready. Please review the diff and test plan.",
            mentions=[our_user],
        )
        self.assertTrue(self._run_filter(msg, "mentions", our_user))


if __name__ == "__main__":
    unittest.main()
