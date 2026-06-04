# g-Remover Backend

FastAPI бэкенд для удаления фона с изображений.

## Быстрый старт

```bash
# 1. Клонируй репо и перейди в папку
cd g-remover-backend

# 2. Создай виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# 3. Установи зависимости
pip install -r requirements.txt

# 4. Создай .env файл
cp .env.example .env
# Отредактируй .env — поменяй SECRET_KEY на случайную строку

# 5. Запусти сервер
uvicorn main:app --reload
```

Сервер запустится на http://localhost:8000

Документация API: http://localhost:8000/docs

---

## API эндпоинты

### Удаление фона
`POST /api/remove-bg`
- Принимает: `multipart/form-data` с полем `file` (JPG/PNG, до 10 МБ)
- Для гостей: передавай заголовок `X-Session-Id` (UUID, генерируй на клиенте и сохраняй в localStorage)
- Для авторизованных: заголовок `Authorization: Bearer <token>`
- Возвращает: PNG с прозрачным фоном
- Заголовок ответа `X-Remaining-Uses` — сколько попыток осталось (для гостей)

### Статус гостя
`GET /api/guest-status`
- Заголовок: `X-Session-Id`
- Возвращает: `{ remaining, used, limit }`

### Регистрация
`POST /api/users/register`
```json
{ "email": "user@example.com", "password": "123456" }
```

### Вход
`POST /api/users/login`
- form-data: `username=email`, `password=...`
- Возвращает JWT токен

### Профиль
`GET /api/users/me`
- Заголовок: `Authorization: Bearer <token>`
- Возвращает план, email, использование

---

## Тарифы

| Тариф   | Лимит/мес | Цена    |
|---------|-----------|---------|
| Гость   | 5         | Бесплатно |
| Starter | 50        | 0 ₽     |
| Pro     | ∞         | 200 ₽   |
| Studio  | ∞         | 690 ₽   |

---

## Деплой на Railway

1. Залей код на GitHub
2. Зайди на railway.app → New Project → Deploy from GitHub
3. Добавь переменные окружения из `.env.example`
4. Railway автоматически найдёт `requirements.txt` и запустит проект
