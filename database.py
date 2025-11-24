from sqlalchemy import BigInteger, String, Boolean, ForeignKey, Integer, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import DB_URL

engine = create_async_engine(DB_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String, nullable=False)
    is_blitz: Mapped[bool] = mapped_column(Boolean, default=False)
    room_code: Mapped[str] = mapped_column(String(4), nullable=True)


class Room(Base):
    __tablename__ = "rooms"
    code: Mapped[str] = mapped_column(String(4), primary_key=True)
    host_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String, default="waiting")  # waiting, playing, finished
    round_number: Mapped[int] = mapped_column(Integer, default=0)
    current_card_text: Mapped[str] = mapped_column(String, nullable=True)

    players: Mapped[list["Player"]] = relationship(back_populates="room", cascade="all, delete-orphan")


class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String, nullable=True)
    room_code: Mapped[str] = mapped_column(ForeignKey("rooms.code"))
    score: Mapped[int] = mapped_column(Integer, default=0)
    current_answers: Mapped[str] = mapped_column(String, nullable=True)  # Ответы через разделитель
    is_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    room: Mapped["Room"] = relationship(back_populates="players")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        result = await session.execute(select(Card))
        if not result.scalars().first():
            defaults = [
                Card(text="Кошки"), Card(text="Ванная комната"),
                Card(text="Почта"), Card(text="Грибы"),
                Card(text="Школа"), Card(text="Япония"),
                Card(text="Обитатели зоопарка"), Card(text="Кухни"),
                Card(text="Металлы"), Card(text="Транспортные средства"),
                Card(text="Грызуны"), Card(text="Футбольные клубы"),
                Card(text="Созвездия"), Card(text="Российские музыкальные исполнители"),
                Card(text="Настольные игры"), Card(text="Канцелярские принадлежности"),
                Card(text="Фрукты"), Card(text="Марки машин"),
                Card(text="Сказки"), Card(text="Цвета"),
                Card(text="Выпечка"), Card(text="Танцы"),
                Card(text="Существительные заканчивающиеся на «-аль»"), Card(text="Детективные фильмы и сериалы"),
                Card(text="Фильмы и сериалы про войну"), Card(text="Центр города"),
                Card(text="Цирк"), Card(text="Книги, в названии которых есть числительное"),
                Card(text="Электрические приборы"), Card(text="Архитектурные сооружения"),
                Card(text="Зарубежные актёры"), Card(text="Персонажи мультфильмов"),
                Card(text="Кофе|Монета|Капитан ...|Жалящее насекомое|Головной убор|Чувство", is_blitz=True),
                Card(text="Пирожное|Слово, заканчивающееся на «-но»|Музыкальная группа 90-х|Торговая сеть|Фокусник|Ирландия", is_blitz=True),
                Card(text="Флот|Ландшафт|Известная Наталья|Островное государство|Дорожный Знак|Комик", is_blitz=True),
                Card(text="Маргарита|Воинское звание|Известное высотное сооружение|Римский император|Компьютерная игра|Обезьяна", is_blitz=True),
                Card(text="Дворец|Сектор|Фильм про шпионов|Начинка для конфет|Нелетающая птица|Солнце", is_blitz=True),
                Card(text="Царь из сказки|Известная пара|Ядовитое растение|Пушной зверь|Гоночный автомобиль|Деталь музыкального инструмента", is_blitz=True),
                Card(text="Сахар|Германия|Популярная профессия|Водный вид спорта|Герой анекдота|Ящерица", is_blitz=True),
                Card(text="Испания|Метательное оружие|Киностудия|Культурное растение|Начинка для пиццы|Муза", is_blitz=True),
                Card(text="Кубок|Порода маленьких собак|Промежуток времени|Чистящее средство|Земля|Банк", is_blitz=True),
                Card(text="Физик|Рок-н-ролл|Аттракцион|Известный Михаил|Ювелирное украшение|Баскетбол", is_blitz=True),
                Card(text="Змея|Река|Спорт|Птица|Авто|Инструмент", is_blitz=True)
            ]
            session.add_all(defaults)
            await session.commit()