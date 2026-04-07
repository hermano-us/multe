import streamlit as st
import requests
from bs4 import BeautifulSoup
import subprocess
import json
import os
from datetime import datetime

st.set_page_config(page_title="Telegram OSINT Profiler", page_icon="🕵️", layout="wide")

st.title("🕵️ Telegram OSINT Profiler")
st.markdown("**Самый быстрый поиск по Telegram + 2000+ сайтов** | Только открытые данные")

# Freemium (работает локально и на Streamlit Cloud)
if "searches" not in st.session_state:
    st.session_state.searches = 0

MAX_FREE_SEARCHES = 3

def parse_public_telegram(query: str):
    query = query.strip()
    if query.startswith("https://t.me/"):
        username = query.split("/")[-1]
    elif query.startswith("@"):
        username = query[1:]
    else:
        username = query

    url = f"https://t.me/{username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    }

    try:
        r = requests.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        og_image = soup.find("meta", property="og:image")

        full_name = og_title["content"].split("–")[0].strip() if og_title else "Не указано"
        bio = og_desc["content"] if og_desc else "Био отсутствует"
        photo = og_image["content"] if og_image else None

        # Количество подписчиков (для каналов)
        subs_text = None
        for tag in soup.find_all(string=True):
            if "подписчик" in tag.lower() or "subscribers" in tag.lower():
                subs_text = tag.strip()
                break

        return {
            "success": True,
            "username": username,
            "full_name": full_name,
            "bio": bio,
            "photo": photo,
            "subscribers": subs_text or "—",
            "url": url,
            "type": "Канал" if "канал" in full_name.lower() else "Профиль"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_maigret(username: str):
    report_dir = "maigret_reports"
    os.makedirs(report_dir, exist_ok=True)

    cmd = [
        "maigret", username,
        "--json",
        "-o", report_dir,
        "--timeout", "18",
        "--site-list", "all"  # можно убрать, если слишком долго
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        report_path = os.path.join(report_dir, f"{username}.json")

        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Удаляем файл после чтения (чтобы не засорять)
            os.remove(report_path)
            return data
        else:
            return {"error": "Maigret не создал отчёт"}
    except Exception as e:
        return {"error": str(e)}


# ====================== ИНТЕРФЕЙС ======================
query = st.text_input(
    "Введите @username, t.me/ссылку или просто username",
    placeholder="@durov или https://t.me/durov"
)

if st.button("🚀 Запустить OSINT-поиск", type="primary", use_container_width=True):
    if not query:
        st.error("Введите запрос!")
        st.stop()

    if st.session_state.searches >= MAX_FREE_SEARCHES:
        st.warning("🎟️ Вы использовали все бесплатные поиски")
        st.info("Подписка 790 ₽/мес или один поиск — 49 ₽")
        st.markdown("[Купить подписку →](https://t.me/yourbot)")  # заменишь на свою ЮKassa позже
        st.stop()

    with st.spinner("Собираем данные из Telegram + Maigret..."):
        tg_data = parse_public_telegram(query)

        if not tg_data.get("success"):
            st.error(f"Не удалось найти в Telegram: {tg_data.get('error')}")
            st.stop()

        maigret_data = run_maigret(tg_data["username"])

    # Увеличиваем счётчик
    st.session_state.searches += 1

    # ====================== ОТЧЁТ ======================
    st.success(f"✅ Найдено по запросу: **@{tg_data['username']}**")

    col1, col2 = st.columns([1, 2])

    with col1:
        if tg_data.get("photo"):
            st.image(tg_data["photo"], use_container_width=True)
        st.metric("Тип", tg_data["type"])
        st.metric("Подписчики", tg_data["subscribers"])

    with col2:
        st.subheader("Telegram данные")
        st.write(f"**Имя:** {tg_data['full_name']}")
        st.write(f"**Био:** {tg_data['bio']}")
        st.write(f"**Ссылка:** [t.me/{tg_data['username']}]({tg_data['url']})")

    # Maigret результаты
    st.subheader("🔍 Найдено на других сайтах (Maigret)")
    if isinstance(maigret_data, dict) and "error" not in maigret_data:
        found_count = len([s for s in maigret_data.get("sites", []) if s.get("status") == "Found"])
        st.info(f"**Найдено аккаунтов:** {found_count}")

        # Таблица
        sites = []
        for site in maigret_data.get("sites", []):
            if site.get("status") == "Found":
                sites.append({
                    "Сайт": site.get("site"),
                    "Ссылка": site.get("url") or site.get("link"),
                    "ID/Username": site.get("username") or "—"
                })

        if sites:
            st.dataframe(sites, use_container_width=True)
        else:
            st.write("Ничего не найдено на других платформах")
    else:
        st.warning("Maigret не вернул данные (возможно, слишком много запросов)")

    # Экспорт
    report = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "telegram": tg_data,
        "maigret": maigret_data
    }

    st.download_button(
        label="📥 Скачать полный отчёт (JSON)",
        data=json.dumps(report, ensure_ascii=False, indent=2),
        file_name=f"osint_{tg_data['username']}.json",
        mime="application/json"
    )

    st.caption("Осталось бесплатных поисков: " + str(MAX_FREE_SEARCHES - st.session_state.searches))

st.divider()
st.markdown("""
**Disclaimer**: Инструмент использует **только публичные данные**.  
Не используйте для незаконных целей. Мы не храним ваши запросы.
""")