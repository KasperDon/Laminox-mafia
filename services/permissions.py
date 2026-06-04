"""
Guruh ruxsatlarini boshqarish: yozishni yoqish/o'chirish.
"""
import logging
from aiogram import Bot
from aiogram.types import ChatPermissions
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

logger = logging.getLogger(__name__)

# Guruh ochiq bo'lganda ruxsatlar
OPEN_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)

# Guruh yopiq bo'lganda ruxsatlar
CLOSED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)


async def lock_chat(bot: Bot, chat_id: int) -> bool:
    """Guruhda yozishni o'chiradi. Muvaffaqiyatli bo'lsa True qaytaradi."""
    try:
        await bot.set_chat_permissions(chat_id, CLOSED_PERMISSIONS)
        logger.info("Chat %d locked", chat_id)
        return True
    except TelegramForbiddenError:
        logger.warning("No admin rights in chat %d to lock", chat_id)
        return False
    except TelegramBadRequest as e:
        logger.warning("Failed to lock chat %d: %s", chat_id, e)
        return False


async def unlock_chat(bot: Bot, chat_id: int) -> bool:
    """Guruhda yozishni yoqadi. Muvaffaqiyatli bo'lsa True qaytaradi."""
    try:
        await bot.set_chat_permissions(chat_id, OPEN_PERMISSIONS)
        logger.info("Chat %d unlocked", chat_id)
        return True
    except TelegramForbiddenError:
        logger.warning("No admin rights in chat %d to unlock", chat_id)
        return False
    except TelegramBadRequest as e:
        logger.warning("Failed to unlock chat %d: %s", chat_id, e)
        return False


async def check_bot_is_admin(bot: Bot, chat_id: int) -> bool:
    """Bot guruhda admin ekanligini tekshiradi."""
    try:
        bot_info = await bot.get_me()
        member = await bot.get_chat_member(chat_id, bot_info.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False
