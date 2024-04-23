from telegram import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio.session import AsyncSession

from utils.db_model import (
    User, KeyboardKey,
    Field, FieldBranch,
    ReplyableConditionMessage
)
from utils.custom_types import KeyboardKeyStatusEnum, ReplyTypeEnum

from bot.application import BBApplication
from bot.helpers.replyable_condition_messages import (
    select_awaliable_replyable_condition_messages_by_condition_bool_field_id,
    check_if_reply_condition_message_is_awaliable_by_reply_condition_bool_field_id
)
from bot.callback_constants import (
    UserStartBranchReplyCallback,
    UserFullTextAnswerReplyCallback,
    UserFastAnswerReplyCallback
)

def construct_keyboard_reply(field: Field, app: BBApplication, deferable_key: bool = True) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    """
    Получить клавиатуру по строке вариантов ответов
    """
    branch: FieldBranch = field.branch
    if field.answer_options in [None, ''] and not branch.is_deferrable:
        return ReplyKeyboardRemove()
    if field.answer_options in [None, ''] and branch.is_deferrable:
        return ReplyKeyboardMarkup([
            [app.provider.config.i18n.defer] if branch.is_deferrable and deferable_key else []
        ])
    return ReplyKeyboardMarkup([
        [key] for key in field.answer_options.split('\n')
    ] + [
        [app.provider.config.i18n.defer] if branch.is_deferrable and deferable_key else []
    ])

async def get_keyboard_of_user(
        session: AsyncSession, user: User,
        always_add_defered_keys: bool = False
    ) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    """
    Получить клавиатуру, доступную пользователю
    """
    awaliable_rcm = select_awaliable_replyable_condition_messages_by_condition_bool_field_id(user)
    selected = await session.execute(
        select(KeyboardKey)
        .where(
            (
                (KeyboardKey.status == KeyboardKeyStatusEnum.NORMAL) &
                (KeyboardKey.reply_condition_message_id.in_(awaliable_rcm))
            ) |
            (
                (KeyboardKey.status == KeyboardKeyStatusEnum.ME) &
                (KeyboardKey.branch_id != None)
            ) |
            (
                (KeyboardKey.status == KeyboardKeyStatusEnum.DEFERRED) &
                (KeyboardKey.branch_id == None) &
                (KeyboardKey.reply_condition_message_id == None) &
                (user.deferred_field_id is not None or always_add_defered_keys)
            )
        )
        .order_by(KeyboardKey.id.asc())
    )
    keyboard_keys     = list(selected.scalars())
    keyboard_keys_len = len(keyboard_keys)
    if keyboard_keys_len == 0:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(
        [
            [ key.key for key in keyboard_keys[idx:idx+2] ]
            for idx in range(0,keyboard_keys_len,2)
        ] if keyboard_keys_len > 2 \
            else [
                [ key.key ] for key in keyboard_keys
            ]
    )

async def get_keyboard_key_by_key_text(session: AsyncSession, key: str) -> KeyboardKey | None:
    """
    Получить полный объект кнопки клавиатуры по названию клавиши
    """
    selected = await session.execute(
        select(KeyboardKey)
        .where(KeyboardKey.key == key)
    )
    return selected.scalar_one_or_none()

async def get_awaliable_inline_keyboard_for_user(
    reply_condition_message: ReplyableConditionMessage,
    user: User,
    session: AsyncSession
    ) -> InlineKeyboardMarkup|None:
    """Получить Inline клавиатуру с вариантами ответов для сообщения"""
    
    if not await check_if_reply_condition_message_is_awaliable_by_reply_condition_bool_field_id(
        reply_condition_message, user, session
    ):
        return None
    
    if reply_condition_message.reply_type == ReplyTypeEnum.BRANCH_START:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                text=reply_condition_message.reply_keyboard_keys,
                callback_data=UserStartBranchReplyCallback.TEMPLATE.format(
                    reply_message_id=reply_condition_message.id,
                    branch_id=reply_condition_message.reply_answer_field_branch_id
                )
            )
        ]])
    
    if reply_condition_message.reply_type == ReplyTypeEnum.FULL_TEXT_ANSWER:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                text=reply_condition_message.reply_keyboard_keys,
                callback_data=UserFullTextAnswerReplyCallback.TEMPLATE.format(
                    reply_message_id=reply_condition_message.id,
                    field_id=reply_condition_message.reply_answer_field_id
                )
            )
        ]])
    
    if reply_condition_message.reply_type == ReplyTypeEnum.FAST_ANSWER:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    text=answer,
                    callback_data=UserFastAnswerReplyCallback.TEMPLATE.format(
                        reply_message_id=reply_condition_message.id,
                        field_id=reply_condition_message.reply_answer_field_id,
                        answer_idx=answer_idx
                    )
                )
            ]
            for answer_idx,answer in enumerate(reply_condition_message.reply_keyboard_keys.split('\n'))
        ])

    return None