import asyncio
import random
import string
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from sqlalchemy import select, update, func, delete
from sqlalchemy.orm import joinedload
from config import BOT_TOKEN
from database import init_db, async_session, Room, Player, Card
from states import GameStates

#{"ROOM_CODE": asyncio.Event}
room_events = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))


async def send_warning_task(room_code, delay=55):
    try:
        await asyncio.sleep(delay)

        async with async_session() as session:
            room = await session.get(Room, room_code)
            if not room or room.status != "playing":
                return

            players = (await session.execute(select(Player).where(Player.room_code == room_code))).scalars().all()
            for p in players:
                if not p.is_ready:
                    try:
                        await bot.send_message(p.user_id, "⏳ **Осталось 5 секунд!** Поторопитесь!",
                                               parse_mode="Markdown")
                    except:
                        pass

    except asyncio.CancelledError:
        pass


async def perform_stop_game(session, room, trigger_user_id):
    if not room or room in session.deleted:
        return False

    room_code = room.code

    if room_code in room_events:
        room_events[room_code].set()

    players_to_notify = (await session.execute(select(Player).where(Player.room_code == room_code))).scalars().all()

    for p in players_to_notify:
        try:
            state_key = StorageKey(bot_id=bot.id, chat_id=p.user_id, user_id=p.user_id)
            await FSMContext(dp.storage, state_key).clear()

            if p.user_id == trigger_user_id:
                continue

            await bot.send_message(p.user_id, "🛑 **Игра остановлена хостом.**\nКомната распущена, все данные очищены.", parse_mode="Markdown")
        except:
            pass

    await session.execute(delete(Card).where(Card.room_code == room_code))

    await session.delete(room)

    await session.commit()

    return True

async def get_round_type(round_num):
    if round_num in [1, 4]:
        return "sync", "🔄 СИНХРОН (Нужны совпадения)"

    elif round_num in [2, 5]:
        return "diff", "💥 РАЗНОБОЙ (Нужна уникальность)"

    else:
        return "express", "🚄 ЭКСПРЕСС (6 категорий)"


@dp.message(Command("help"))
async def help_command(message: types.Message):
    text = (
        "🤖 **Помощь по боту «СмыСЛов»**\n\n"
        "**Основные команды:**\n"
        "/start — Главное меню (создать комнату, правила)\n"
        "/help — Показать это сообщение\n\n"
        "**Вход в игру:**\n"
        "`/join КОД` — Присоединиться к комнате по коду (например: `/join A1B2`)\n\n"
        "**Управление (когда вы в комнате):**\n"
        "`/setname Имя` — Сменить свой ник в игре\n"
        "/leave — Покинуть текущую комнату\n"
        "/stop — Остановить игру принудительно (только для Хоста)\n\n"
        "ℹ️ *Если бот не отвечает на ваши сообщения во время раунда, значит, время вышло и идет подсчет очков.*"
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = types.ReplyKeyboardMarkup(keyboard=[
        [types.KeyboardButton(text="Создать комнату")],
        [types.KeyboardButton(text="Правила")]
    ], resize_keyboard=True)
    await message.answer("Добро пожаловать в игру **«СмыСЛов»**! 🧠\nВыберите действие:", reply_markup=kb, parse_mode="Markdown")

@dp.message(F.text == "Правила")
async def rules_handler(message: types.Message):
    text = (
        "📚 **ПРАВИЛА ИГРЫ «СмыСЛов»**\n\n"
        "Это игра на ассоциации, которая длится 6 раундов.\n\n"
        "🔄 **Раунды 1 и 4: «Синхрон»**\n"
        "Ваша цель — настроиться на волну других. Вы получаете очки за каждый ответ, который **совпал** с ответом хотя бы одного другого игрока.\n\n"
        "💥 **Раунды 2 и 5: «Разнобой»**\n"
        "Здесь нужно мыслить нестандартно. Вы получаете очки только за те ответы, которые **уникальны** и не встретились ни у кого больше.\n\n"
        "🚄 **Раунды 3 и 6: «Экспресс»**\n"
        "Вам дается 6 разных мини-тем. Нужно придумать по 1 ассоциации на каждую.\n"
        "⚠️ **Важен порядок!** Ваш первый ответ сравнивается только с первым ответом других игроков, второй — со вторым и так далее\n\n"
        "**Бонусы:**\n"
        "Если в раунде вы «выбили» 6 из 6 (все совпали в Синхроне или все уникальны в Разнобое), вы получаете +1 бонусный балл."
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(F.text == "Создать комнату")
async def create_room(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    async with async_session() as session:
        stmt = select(Player).options(joinedload(Player.room)).where(Player.user_id == user_id)
        existing_player = await session.scalar(stmt)

        if existing_player and existing_player.room and existing_player.room.status in ["waiting", "playing"]:
            return await message.answer(
                "⛔ Вы уже находитесь в активной комнате!\n"
                "Сначала выйдите из текущей игры, написав команду /leave."
            )

        code = generate_room_code()
        room = Room(code=code, host_id=user_id)

        user_name = message.from_user.full_name or message.from_user.first_name

        player = Player(user_id=user_id, username=user_name, room_code=code)

        session.add(room)
        session.add(player)
        await session.commit()

    await state.set_state(GameStates.in_lobby)
    await state.update_data(room_code=code)

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Начать игру 🚀", callback_data="start_game")],
        [types.InlineKeyboardButton(text="➕ Добавить карты", callback_data="add_cards_menu")]
    ])

    await message.answer(
        f"✅ **Комната успешно создана!**\n\n"
        f"Код комнаты: `{code}`\n\n"
        f"Отправьте этот код друзьям. Они должны написать боту:\n`/join {code}`\n\n"
        f"Когда все соберутся, нажмите кнопку «Начать игру».",
        parse_mode="Markdown",
        reply_markup=kb
    )


@dp.callback_query(F.data == "add_cards_menu")
async def add_cards_menu(callback: types.CallbackQuery, state: FSMContext):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Обычные (Синхрон/Разнобой)", callback_data="set_add_mode_standard")],
        [types.InlineKeyboardButton(text="Экспресс (6 тем)", callback_data="set_add_mode_express")],
        [types.InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_lobby")]
    ])
    await callback.message.edit_text("Какие карты вы хотите добавить?", reply_markup=kb)


@dp.callback_query(F.data.startswith("set_add_mode_"))
async def set_add_card_mode(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split("_")[-1]
    await state.update_data(adding_mode=mode)
    await state.set_state(GameStates.adding_cards)

    if mode == "standard":
        text = (
            "📝 **Добавление обычных карт**\n"
            "Пришлите список тем одним сообщением.\n"
            "Разделяйте темы **запятой** или **новой строкой**.\n\n"
            "Пример:\n`Любимые фильмы, Еда в столовой, Что подарить бабушке`"
        )
    else:
        text = (
            "📝 **Добавление карт для Экспресса**\n"
            "Пришлите темы. Каждая строка — это одна карточка, содержащая ровно **6 подтем**, разделенных знаком `|`.\n\n"
            "Пример:\n`Зима|Лето|Осень|Весна|Дождь|Снег`\n`Москва|Питер|Казань|Сочи|Уфа|Омск`"
        )

    await callback.message.edit_text(text, parse_mode="Markdown")


@dp.message(GameStates.adding_cards)
async def save_custom_cards(message: types.Message, state: FSMContext):
    data = await state.get_data()
    room_code = data.get("room_code")
    mode = data.get("adding_mode")

    text = message.text
    added_count = 0

    async with async_session() as session:
        if mode == "standard":
            raw_lines = text.replace(',', '\n').split('\n')
            for line in raw_lines:
                clean_text = line.strip()
                if clean_text:
                    card = Card(text=clean_text, is_blitz=False, room_code=room_code)
                    session.add(card)
                    added_count += 1

        elif mode == "express":
            lines = text.split('\n')
            for line in lines:
                parts = line.split('|')
                if len(parts) >= 2:
                    clean_text = line.strip()
                    card = Card(text=clean_text, is_blitz=True, room_code=room_code)
                    session.add(card)
                    added_count += 1

        await session.commit()

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Начать игру 🚀", callback_data="start_game")],
        [types.InlineKeyboardButton(text="➕ Добавить ещё", callback_data="add_cards_menu")]
    ])

    await state.set_state(GameStates.in_lobby)
    await message.answer(f"✅ Добавлено карточек: **{added_count}**.\nОни будут использованы в приоритете!",
                         reply_markup=kb, parse_mode="Markdown")


@dp.callback_query(F.data == "back_to_lobby")
async def back_lobby(callback: types.CallbackQuery, state: FSMContext):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Начать игру 🚀", callback_data="start_game")],
        [types.InlineKeyboardButton(text="➕ Добавить карты", callback_data="add_cards_menu")]
    ])
    await callback.message.edit_text("Готовы начать?", reply_markup=kb)

@dp.message(Command("setname"))
async def set_name_command(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.answer("Используйте: `/setname НовоеИмя`", parse_mode="Markdown")

    new_name = args[1].strip()[:20]

    async with async_session() as session:
        player = await session.scalar(select(Player).where(Player.user_id == message.from_user.id))
        if player:
            player.username = new_name
            await session.commit()
            await message.answer(f"✅ Ваше имя изменено на: **{new_name}**", parse_mode="Markdown")
        else:
            await message.answer("Сначала войдите в комнату с помощью /join")


@dp.message(Command("join"))
async def join_room(message: types.Message, state: FSMContext):
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Используйте: /join КОД")
    code = args[1].upper()

    user_name = message.from_user.full_name or message.from_user.first_name

    async with async_session() as session:
        room = await session.get(Room, code)
        if not room or room.status != "waiting":
            return await message.answer("Комната недоступна.")

        existing = await session.scalar(
            select(Player).where(Player.user_id == message.from_user.id, Player.room_code == code))

        if not existing:
            player = Player(user_id=message.from_user.id, username=user_name, room_code=code)
            session.add(player)
            await session.commit()

            count = await session.scalar(select(func.count(Player.id)).where(Player.room_code == code))
            try:
                await bot.send_message(
                    room.host_id,
                    f"👤 **Новый игрок!**\nК нам присоединился: {user_name}\nВсего игроков: {count}"
                )
            except:
                pass
        else:
            await message.answer("Вы уже в этой комнате.")

    await state.set_state(GameStates.in_lobby)
    await state.update_data(room_code=code)
    await message.answer(f"Вы вошли в комнату {code} как **{user_name}**.\nЖдем старта игры.")


@dp.callback_query(F.data == "add_card")
async def ask_custom_card(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название категории (или 6 категорий через '|' для блица):")
    # TODO разобраться что я тут наделал...


@dp.callback_query(F.data == "start_game")
async def start_game_handler(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    code = data.get("room_code")

    async with async_session() as session:
        await session.execute(update(Room).where(Room.code == code).values(status="playing", round_number=0))
        await session.commit()

    await start_next_round(code)


@dp.message(Command("stop"))
async def stop_game_command(message: types.Message):
    async with async_session() as session:
        stmt = select(Player).options(joinedload(Player.room)).where(Player.user_id == message.from_user.id)
        player = await session.scalar(stmt)

        if not player or not player.room:
            return await message.answer("Вы не в игре.")

        room = player.room
        if room.host_id != message.from_user.id:
            return await message.answer("Только хост может остановить игру.")

        if await perform_stop_game(session, room, message.from_user.id):
            await message.answer("✅ Игра остановлена.")
        else:
            await message.answer("Игра уже завершена.")


@dp.message(Command("leave"))
async def leave_room_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    async with async_session() as session:
        stmt = select(Player).options(joinedload(Player.room)).where(Player.user_id == user_id)
        player = await session.scalar(stmt)

        if not player or not player.room:
            await state.clear()
            return await message.answer("Вы не находитесь в активной комнате.")

        room = player.room
        room_code = room.code
        is_host = (room.host_id == user_id)

        if is_host and room.status != "finished":
            await perform_stop_game(session, room, user_id)
            await message.answer("Вы покинули комнату. Так как вы были хостом, игра остановлена для всех.")
            await session.delete(player)
            await session.commit()

        else:
            username = player.username
            await session.delete(player)
            await session.commit()

            await message.answer(f"Вы покинули комнату {room_code}.")

            if room.status != "finished":
                count = await session.scalar(select(func.count(Player.id)).where(Player.room_code == room_code))
                try:
                    await bot.send_message(room.host_id, f"🏃‍♂️ Игрок **{username}** покинул игру. Осталось: {count}",
                                           parse_mode="Markdown")
                except:
                    pass

    await state.clear()


async def start_next_round(room_code):
    round_event = asyncio.Event()
    room_events[room_code] = round_event

    async with async_session() as session:
        room = await session.get(Room, room_code)
        if not room or room.status == "finished": return

        room.round_number += 1
        if room.round_number > 6: return await finish_game(room_code, session)

        r_type, r_name = await get_round_type(room.round_number)
        need_blitz = (r_type == "express")
        stmt_custom = select(Card).where(Card.is_blitz == need_blitz, Card.room_code == room_code)
        custom_cards = (await session.execute(stmt_custom)).scalars().all()
        if custom_cards:
            card = random.choice(custom_cards)
        else:
            stmt_default = select(Card).where(Card.is_blitz == need_blitz, Card.room_code == None)
            default_cards = (await session.execute(stmt_default)).scalars().all()
            card = random.choice(default_cards) if default_cards else Card(text="Резерв", is_blitz=False)

        room.current_card_text = card.text
        await session.execute(
            update(Player).where(Player.room_code == room_code).values(current_answers=None, is_ready=False))
        await session.commit()
        players = (await session.execute(select(Player).where(Player.room_code == room_code))).scalars().all()

    for p in players:
        if r_type == "express":
            cats = card.text.split('|')
            formatted_cats = "\n".join([f"{i + 1}. {c}" for i, c in enumerate(cats)])
            msg = (
                f"🚄 **ЭКСПРЕСС (Важен порядок!)**\nНапишите 6 ответов строго по порядку:\n\n{formatted_cats}\n\n👇 Отправьте 6 строк.")
        else:
            msg = (
                f"🔔 **Раунд {room.round_number}: {r_name}**\nТема: **{card.text}**\n\n👇 Напишите 6 ассоциаций (порядок не важен):")

        try:
            await bot.send_message(p.user_id, msg, parse_mode="Markdown")
            state_key = StorageKey(bot_id=bot.id, chat_id=p.user_id, user_id=p.user_id)
            await FSMContext(dp.storage, state_key).set_state(GameStates.writing_answers)
        except:
            pass

    warning_task = asyncio.create_task(send_warning_task(room_code, delay=55))

    try:
          await asyncio.wait_for(round_event.wait(), timeout=60.0)
    except asyncio.TimeoutError:
        pass
    finally:
        if not warning_task.done():
            warning_task.cancel()

    if room_code in room_events:
        del room_events[room_code]

    async with async_session() as session:
        room = await session.get(Room, room_code)
        if not room or room.status == "finished": return

    await calculate_results(room_code)


@dp.message(GameStates.in_lobby)
async def lobby_chat(message: types.Message):
    pass


# В реальном коде здесь нужен Middleware или проверка state пользователя,
# так как все игроки должны быть в state `writing_answers`
@dp.message(GameStates.writing_answers)
async def receive_answer(message: types.Message, state: FSMContext):
    text = message.text.replace(',', '\n').replace(';', '\n')
    answers = [line.strip() for line in text.split('\n') if line.strip()][:6]
    if not answers: return

    async with async_session() as session:
        stmt = select(Player, Room).join(Room, Player.room_code == Room.code).where(
            Player.user_id == message.from_user.id)
        result = (await session.execute(stmt)).first()

        if not result:
            await state.clear()
            return

        player, room = result

        if room.status != "playing":
            await state.clear()
            await message.answer("Игра уже завершена, ответы не принимаются.")
            return

        player.current_answers = "||".join(answers)
        await session.execute(update(Player).where(Player.id == player.id).values(current_answers="||".join(answers)))
        await session.commit()

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Я всё (Готов)", callback_data="player_ready")]
    ])
    await message.answer(
        f"Принято: {len(answers)}/6.\n" + "\n".join(answers) + "\n\nЕсли не будете менять — жмите кнопку!",
        reply_markup=kb
    )


@dp.callback_query(F.data == "player_ready")
async def player_ready_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    async with async_session() as session:
        await session.execute(update(Player).where(Player.user_id == user_id).values(is_ready=True))
        await session.commit()

        player = (await session.execute(select(Player).where(Player.user_id == user_id))).scalars().first()
        room_code = player.room_code

        total_players = await session.execute(select(func.count(Player.id)).where(Player.room_code == room_code))
        ready_players = await session.execute(
            select(func.count(Player.id)).where(Player.room_code == room_code, Player.is_ready == True))

        total = total_players.scalar()
        ready = ready_players.scalar()

    await callback.answer(f"Готово! Ждем остальных ({ready}/{total})")
    await callback.message.edit_text(f"✅ Вы отметились как готовый. Ждем остальных ({ready}/{total})...")

    if ready == total:
        if room_code in room_events:
            room_events[room_code].set()



async def calculate_results(room_code):
    async with async_session() as session:
        room = await session.get(Room, room_code)
        players = (await session.execute(select(Player).where(Player.room_code == room_code))).scalars().all()

        r_type, _ = await get_round_type(room.round_number)

        player_answers_map = {}
        for p in players:
            if p.current_answers:
                player_answers_map[p.id] = [a.lower().strip() for a in p.current_answers.split('||')]
            else:
                player_answers_map[p.id] = []

        round_scores = {}

        for p in players:
            added_score = 0
            p_answers = player_answers_map.get(p.id, [])
            matches_count = 0

            for i, my_ans in enumerate(p_answers):
                is_match_found = False

                for other in players:
                    if other.id == p.id: continue

                    other_answers = player_answers_map.get(other.id, [])

                    if r_type == "express":
                        if i < len(other_answers) and other_answers[i] == my_ans:
                            is_match_found = True
                            break

                    else:
                        if my_ans in other_answers:
                            is_match_found = True
                            break

                if r_type in ["sync", "express"]:
                    if is_match_found:
                        added_score += 1
                        matches_count += 1

                elif r_type == "diff":
                    if not is_match_found:
                        added_score += 1
                        matches_count += 1

            if len(p_answers) == 6 and matches_count == 6:
                added_score += 1

            round_scores[p.id] = added_score
            p.score += added_score

        await session.commit()

        summary_text = f"📊 **Итоги раунда {room.round_number}**\n\n"

        for p in players:
            ans_list = player_answers_map.get(p.id, [])

            if r_type == "express":
                ans_display = "\n".join([f"{k + 1}. {word}" for k, word in enumerate(ans_list)])
                display_block = f"\n{ans_display}"
            else:
                display_block = ", ".join(ans_list)

            summary_text += f"👤 **{p.username}**: +{round_scores[p.id]} ⭐️\nОтветы: {display_block}\n\n"

        summary_text += "Администратор проверяет результаты..."

    host_id = room.host_id
    for p in players:
        state_key = StorageKey(bot_id=bot.id, chat_id=p.user_id, user_id=p.user_id)
        await FSMContext(dp.storage, state_key).set_state(GameStates.scoring)

        if p.user_id == host_id:
            await send_host_panel(p.user_id, room_code, summary_text)
        else:
            await bot.send_message(p.user_id, summary_text, parse_mode="Markdown")


async def send_host_panel(chat_id, room_code, summary_text):
    async with async_session() as session:
        players = (await session.execute(
            select(Player).where(Player.room_code == room_code).order_by(Player.id))).scalars().all()

    keyboard = []
    for p in players:
        btn_text = f"✏️ {p.username} ({p.score})"
        keyboard.append([types.InlineKeyboardButton(text=btn_text, callback_data=f"edit_score_{p.id}_{room_code}")])

    keyboard.append([types.InlineKeyboardButton(text="➡️ Следующий раунд", callback_data=f"host_next_{room_code}")])

    kb = types.InlineKeyboardMarkup(inline_keyboard=keyboard)

    await bot.send_message(
        chat_id,
        summary_text + "\n\n👮‍♂️ **Панель Хоста**:\nНажмите на игрока, чтобы исправить очки, если робот ошибся.",
        reply_markup=kb,
        parse_mode="Markdown"
    )



@dp.callback_query(F.data.startswith("edit_score_"))
async def edit_score_menu(callback: types.CallbackQuery):
    # data format: edit_score_PLAYERID_ROOMCODE
    _, _, player_id_str, room_code = callback.data.split("_")
    player_id = int(player_id_str)

    async with async_session() as session:
        host_player = await session.scalar(select(Player).where(Player.user_id == callback.from_user.id))
        room = await session.get(Room, room_code)

        if not host_player or not room or room.host_id != callback.from_user.id:
            return await callback.answer("Вы не хост!", show_alert=True)

        target_player = await session.get(Player, player_id)
        if not target_player:
            return await callback.answer("Игрок не найден")

        current_score = target_player.score
        name = target_player.username

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="➖ 1", callback_data=f"mod_score_-1_{player_id}_{room_code}"),
            types.InlineKeyboardButton(text=f"🏆 {current_score}", callback_data="noop"),
            types.InlineKeyboardButton(text="➕ 1", callback_data=f"mod_score_+1_{player_id}_{room_code}")
        ],
        [types.InlineKeyboardButton(text="🔙 Назад к списку", callback_data=f"back_panel_{room_code}")]
    ])

    await callback.message.edit_text(f"Редактирование очков игрока **{name}**:", reply_markup=kb, parse_mode="Markdown")


@dp.callback_query(F.data.startswith("mod_score_"))
async def modify_score_handler(callback: types.CallbackQuery):
    # data format: mod_score_DELTA_PLAYERID_ROOMCODE
    parts = callback.data.split("_")
    delta = int(parts[2])
    player_id = int(parts[3])
    room_code = parts[4]

    async with async_session() as session:
        player = await session.get(Player, player_id)
        if player:
            player.score += delta
            new_score = player.score
            name = player.username
            await session.commit()

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="➖ 1", callback_data=f"mod_score_-1_{player_id}_{room_code}"),
            types.InlineKeyboardButton(text=f"🏆 {new_score}", callback_data="noop"),
            types.InlineKeyboardButton(text="➕ 1", callback_data=f"mod_score_+1_{player_id}_{room_code}")
        ],
        [types.InlineKeyboardButton(text="🔙 Назад к списку", callback_data=f"back_panel_{room_code}")]
    ])

    try:
        await callback.message.edit_text(f"Редактирование очков игрока **{name}**:", reply_markup=kb,
                                         parse_mode="Markdown")
    except:
        pass


@dp.callback_query(F.data.startswith("back_panel_"))
async def back_to_panel(callback: types.CallbackQuery):
    room_code = callback.data.split("_")[-1]
    await send_host_panel(callback.from_user.id, room_code, "📊 **Панель управления** (обновлено)")



@dp.callback_query(F.data.startswith("host_next_"))
async def host_next_round(callback: types.CallbackQuery):
    room_code = callback.data.split("_")[-1]

    async with async_session() as session:
        room = await session.get(Room, room_code)
        if not room or room.host_id != callback.from_user.id:
            return await callback.answer("Только хост может продолжить игру!", show_alert=True)

        players = (await session.execute(select(Player).where(Player.room_code == room_code))).scalars().all()

        msg = f"✅ **Результаты раунда {room.round_number} утверждены!**\nОбщий счет:\n"
        sorted_players = sorted(players, key=lambda x: x.score, reverse=True)
        for p in sorted_players:
            msg += f"{p.username}: {p.score}\n"

    for p in players:
        try:
            await bot.send_message(p.user_id, msg, parse_mode="Markdown")
        except:
            pass

    await callback.message.edit_text("✅ Результаты сохранены. Запускаем следующий раунд...")

    asyncio.create_task(start_next_round(room_code))


@dp.callback_query(F.data.startswith("next_round_"))
async def next_round_trigger(callback: types.CallbackQuery):
    # TODO это актуально?
    room_code = callback.data.split("_")[-1]
    await callback.message.answer("Запускаем следующий раунд...")
    await start_next_round(room_code)


async def finish_game(room_code, session):
    players = (await session.execute(
        select(Player).where(Player.room_code == room_code).order_by(Player.score.desc())
    )).scalars().all()

    if not players: return

    text = "🏆 **ИГРА ОКОНЧЕНА!** 🏆\n\nИтоговая таблица:\n"
    for i, p in enumerate(players):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🔹"
        text += f"{medal} {p.username} — {p.score}\n"

    winner = players[0]
    text += f"\nПобедитель: **{winner.username}**! Поздравляем!"

    for p in players:
        try:
            await bot.send_message(p.user_id, text, parse_mode="Markdown")
            state_key = StorageKey(bot_id=bot.id, chat_id=p.user_id, user_id=p.user_id)
            await FSMContext(dp.storage, state_key).clear()
        except:
            pass


    await session.execute(delete(Card).where(Card.room_code == room_code))

    room = await session.get(Room, room_code)
    if room:
        await session.delete(room)

    await session.commit()
    print(f"Комната {room_code} и данные игроков удалены.")

@dp.message(F.text, StateFilter(None))
async def default_handler(message: types.Message):
    await message.answer(
        "Я вас не понимаю. 🤔\n"
        "Похоже, вы отправили сообщение не вовремя.\n\n"
        "Используйте команду /help, чтобы посмотреть список доступных действий, "
        "или нажмите /start для выхода в главное меню."
    )

async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())