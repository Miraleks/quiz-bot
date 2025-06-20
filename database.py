import sqlite3
from datetime import datetime, timedelta
import verbs as verb_data

DB_NAME = 'quiz_bot.db'


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            phone_number TEXT NOT NULL,
            first_name TEXT,
            registration_date TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            archive_id TEXT UNIQUE
        )
    ''')

    # Таблица глаголов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS verbs (
            verb_id INTEGER PRIMARY KEY AUTOINCREMENT,
            infinitive TEXT NOT NULL,
            praeteritum TEXT NOT NULL,
            partizip_ii TEXT NOT NULL,
            is_irregular INTEGER NOT NULL
        )
    ''')

    # Таблица статистики
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_stats (
            stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            verb_id INTEGER NOT NULL,
            is_correct INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (verb_id) REFERENCES verbs (verb_id)
        )
    ''')

    # Проверка, нужно ли наполнять базу глаголами
    cursor.execute("SELECT COUNT(*) FROM verbs")
    if cursor.fetchone()[0] == 0:
        print("Populating verbs database...")
        all_verbs = []
        # Добавляем неправильные глаголы
        for v in verb_data.IRREGULAR_VERBS:
            all_verbs.append(v + (1,))
        # Добавляем правильные глаголы
        for v in verb_data.REGULAR_VERBS:
            all_verbs.append(v + (0,))

        cursor.executemany(
            "INSERT INTO verbs (infinitive, praeteritum, partizip_ii, is_irregular) VALUES (?, ?, ?, ?)",
            all_verbs
        )
        print(f"Added {len(all_verbs)} verbs to the database.")

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ? AND is_active = 1", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user


def add_user(user_id, phone_number, first_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (user_id, phone_number, first_name, registration_date) VALUES (?, ?, ?, ?)",
            (user_id, phone_number, first_name, datetime.now().isoformat())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Если пользователь уже есть, но неактивен, активируем его
        cursor.execute(
            "UPDATE users SET is_active = 1, phone_number = ?, first_name = ? WHERE user_id = ?",
            (phone_number, first_name, user_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_random_verbs(count=4):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM verbs ORDER BY RANDOM() LIMIT ?", (count,))
    verbs = cursor.fetchall()
    conn.close()
    return verbs


def log_answer(user_id, verb_id, is_correct):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO quiz_stats (user_id, verb_id, is_correct, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, verb_id, 1 if is_correct else 0, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_user_stats(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    now = datetime.now()
    periods = {
        'day': now - timedelta(days=1),
        'week': now - timedelta(days=7),
        'month': now - timedelta(days=30)
    }

    stats = {}
    for period_name, start_date in periods.items():
        cursor.execute(
            "SELECT COUNT(*), SUM(is_correct) FROM quiz_stats WHERE user_id = ? AND timestamp >= ?",
            (user_id, start_date.isoformat())
        )
        result = cursor.fetchone()
        total = result[0] if result[0] is not None else 0
        correct = result[1] if result[1] is not None else 0
        stats[period_name] = {
            'total': total,
            'correct': correct,
            'percentage': (correct / total * 100) if total > 0 else 0
        }

    cursor.execute("SELECT COUNT(DISTINCT verb_id) FROM quiz_stats WHERE user_id = ?", (user_id,))
    stats['games_played'] = cursor.fetchone()[0]

    conn.close()
    return stats


def reset_statistics(user_id, phone_number):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    archive_id = f"{phone_number}_old_{datetime.now().strftime('%Y-%m-%d_%H-%M')}"

    # 1. Создаем архивную запись пользователя
    cursor.execute(
        "UPDATE users SET is_active = 0, archive_id = ? WHERE user_id = ? AND is_active = 1",
        (archive_id, user_id)
    )

    # 2. Переносим статистику на старого "неактивного" пользователя
    # Статистика остается привязанной к user_id, который теперь неактивен.
    # Для нового старта просто не будет старых записей.

    conn.commit()
    conn.close()

    # Так как пользователь с этим user_id стал неактивным,
    # при следующем старте он будет считаться новым, но мы можем его
    # сразу "перерегистрировать" с тем же user_id, чтобы не терять контакт.
    # В данном коде это произойдет автоматически при /start
    return True