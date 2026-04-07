import streamlit as st
import asyncio
import os
import json
from datetime import datetime
import subprocess
import requests
from bs4 import BeautifulSoup
from telethon import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import SessionPasswordNeededError, FloodWaitError

st.set_page_config(page_title="Telegram OSINT Profiler v1.1", page_icon="🕵️‍♂️", layout="wide")

st.title("🕵️ Telegram OSINT Profiler v1.1")
st.markdown("**Telethon + Maigret** | Поиск по username · ID · телефону · forward")

# ====================== СЕССИЯ И API ======================
# ====================== TELETHON CLIENT (исправленная версия) ======================
if "telethon_client" not in st.session_state:
    st.session_state.telethon_client = None
if "auth_step" not in st.session_state:
    st.session_state.auth_step = "phone"   # phone → code → done
if "phone" not in st.session_state:
    st.session_state.phone = ""
if "code" not in st.session_state:
    st.session_state.code = ""

async def get_telethon_client():
    if st.session_state.telethon_client is not None and await st.session_state.telethon_client.is_user_authorized():
        return st.session_state.telethon_client

    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        if st.session_state.auth_step == "phone":
            phone = st.text_input("Введите номер телефона (+7XXXXXXXXXX)", 
                                  value=st.session_state.phone, 
                                  key="phone_input")
            if st.button("Отправить код", key="send_code"):
                st.session_state.phone = phone
                try:
                    await client.send_code_request(phone)
                    st.session_state.auth_step = "code"
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка отправки кода: {e}")
        elif st.session_state.auth_step == "code":
            st.info(f"Код отправлен на номер {st.session_state.phone}")
            code = st.text_input("Введите код из Telegram", key="code_input")
            if st.button("Войти", key="login_button"):
                try:
                    await client.sign_in(st.session_state.phone, code)
                    st.success("✅ Авторизация прошла успешно!")
                    st.session_state.auth_step = "done"
                    st.rerun()
                except SessionPasswordNeededError:
                    st.error("Включён двухфакторный пароль. Пока не поддерживается в этом MVP.")
                except Exception as e:
                    st.error(f"Ошибка входа: {e}")
    else:
        st.session_state.auth_step = "done"

    st.session_state.telethon_client = client
    return client

API_ID = st.secrets.get("API_ID") or os.getenv("API_ID")
API_HASH = st.secrets.get("API_HASH") or os.getenv("API_HASH")
SESSION_NAME = "tg_osint_session"

if not API_ID or not API_HASH:
    st.error("❌ Добавь API_ID и API_HASH в Streamlit Secrets или .env файл")
    st.info("Получи их на https://my.telegram.org → API development tools")
    st.stop()

# ====================== FREEMIUM ======================
if "searches" not in st.session_state:
    st.session_state.searches = 0
MAX_FREE = 3


# ====================== ОСНОВНЫЕ ФУНКЦИИ ======================
async def get_telethon_client():
    if st.session_state.telethon_client is None or not st.session_state.telethon_client.is_connected():
        client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            st.warning("Нужно авторизоваться. Введи номер телефона ниже.")
            phone = st.text_input("Телефон для авторизации (+7...)")
            if phone:
                await client.start(phone=phone)
                st.success("Авторизация прошла!")
        st.session_state.telethon_client = client
    return st.session_state.telethon_client


async def fetch_user_info(query: str):
    client = await get_telethon_client()

    try:
        # Автоопределение типа запроса
        if query.startswith(('+', '7', '8')) and len(query.replace('+', '').replace(' ', '')) >= 10:
            entity = await client.get_entity(query)  # по телефону
        elif query.isdigit() or (query.startswith('-') and query[1:].isdigit()):
            entity = await client.get_entity(int(query))  # по ID
        elif query.startswith("https://t.me/") or query.startswith("@"):
            entity = await client.get_entity(query)
        else:
            # Пытаемся как username или forward
            entity = await client.get_entity(query)

        full = await client(GetFullUserRequest(entity))

        return {
            "success": True,
            "entity": entity,
            "full_user": full,
            "username": entity.username,
            "id": entity.id,
            "first_name": entity.first_name,
            "last_name": entity.last_name,
            "bio": full.full_user.about if full.full_user.about else "—",
            "photo": f"https://t.me/{entity.username}" if entity.username else None,
            "status": str(entity.status) if hasattr(entity, 'status') else "—",
            "is_bot": entity.bot,
            "is_channel": hasattr(entity, 'broadcast') and entity.broadcast
        }
    except FloodWaitError as e:
        return {"success": False, "error": f"Telegram просит подождать {e.seconds} секунд (Flood)"}
    except Exception as e:
        # fallback на простой парсинг t.me
        return await fallback_parse(query)


async def fallback_parse(query: str):
    # Тот же простой парсинг, что был раньше
    try:
        if query.startswith("https://t.me/"):
            username = query.split("/")[-1].split("?")[0]
        elif query.startswith("@"):
            username = query[1:]
        else:
            username = query

        r = requests.get(f"https://t.me/{username}", timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")

        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        og_image = soup.find("meta", property="og:image")

        return {
            "success": True,
            "fallback": True,
            "username": username,
            "full_name": og_title["content"].split("–")[0].strip() if og_title else username,
            "bio": og_desc["content"] if og_desc else "—",
            "photo": og_image["content"] if og_image else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_maigret(username: str):
    """Временная заглушка — Maigret отключён из-за проблем с установкой на Streamlit Cloud"""
    if not username:
        return {"error": "Нет username"}
    
    return {
        "warning": "🔧 Поиск по другим сайтам (Maigret) временно отключён",
        "message": "Мы работаем над стабильной версией. Пока пользуйтесь Telegram-данными.",
        "sites": []  # пустой список, чтобы не ломало отображение
    }


# ====================== ИНТЕРФЕЙС ======================
query = st.text_input(
    "🔍 Введите запрос:",
    placeholder="@durov | 123456789 | +79161234567 | https://t.me/durov | вставь forwarded сообщение"
)

if st.button("🚀 Запустить расширенный OSINT", type="primary", use_container_width=True):
    if not query:
        st.error("Введите запрос!")
        st.stop()

    if st.session_state.searches >= MAX_FREE:
        st.warning("🎟️ Бесплатные поиски закончились")
        st.info("Один поиск — 49 ₽ | Подписка 790 ₽/мес")
        st.stop()

    with st.spinner("Подключаемся к Telegram через Telethon + Maigret..."):
        result = asyncio.run(fetch_user_info(query))

    st.session_state.searches += 1

    if not result.get("success"):
        st.error(f"Ошибка: {result.get('error')}")
        st.stop()

    # ====================== КРАСИВЫЙ ОТЧЁТ ======================
    st.success(f"✅ Профиль найден: **{result.get('full_name', result.get('username'))}**")

    col1, col2 = st.columns([1, 2])

    with col1:
        if result.get("photo"):
            st.image(result["photo"], use_container_width=True)
        st.metric("ID", result.get("id", "—"))
        st.metric("Username", f"@{result.get('username')}" if result.get("username") else "—")
        st.metric("Тип", "Канал" if result.get("is_channel") else "Бот" if result.get("is_bot") else "Пользователь")

    with col2:
        st.subheader("📋 Основная информация")
        st.write(f"**Имя:** {result.get('first_name')} {result.get('last_name') or ''}")
        st.write(f"**Био:** {result.get('bio')}")
        st.write(f"**Статус:** {result.get('status')}")

        if result.get("fallback"):
            st.info("Использован упрощённый парсинг (без Telethon)")

    # Maigret
    username_for_maigret = result.get("username") or result.get("full_name")
    if username_for_maigret:
        st.subheader("🌐 Найдено на других платформах")
        maigret_data = run_maigret(username_for_maigret)

        if "error" not in maigret_data:
            found = len([s for s in maigret_data.get("sites", []) if s.get("status") == "Found"])
            st.info(f"Аккаунты найдены на **{found}** сайтах")

            sites_table = []
            for site in maigret_data.get("sites", []):
                if site.get("status") == "Found":
                    sites_table.append({
                        "Сайт": site.get("site_name", site.get("site")),
                        "Ссылка": site.get("url") or site.get("link"),
                        "ID/Логин": site.get("username") or "—"
                    })
            if sites_table:
                st.dataframe(sites_table, use_container_width=True)
        else:
            st.warning(maigret_data["error"])

    # Экспорт
    full_report = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "result": result,
        "maigret": maigret_data if 'maigret_data' in locals() else None
    }

    st.download_button(
        "📥 Скачать полный JSON-отчёт",
        data=json.dumps(full_report, ensure_ascii=False, indent=2),
        file_name=f"osint_report_{result.get('username', 'unknown')}.json",
        mime="application/json"
    )

    st.caption(f"Осталось бесплатных поисков: {MAX_FREE - st.session_state.searches}")

st.divider()
st.caption("Только публичные данные • Не используйте для незаконных целей")
