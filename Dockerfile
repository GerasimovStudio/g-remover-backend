FROM python:3.11-slim

WORKDIR /code

# Устанавливаем обновленные системные библиотеки (заменили libgl1-mesa-glx на libgl1)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements.txt внутрь контейнера
COPY ./requirements.txt /code/requirements.txt

# Устанавливаем все питон-зависимости
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Копируем оставшийся код проекта
COPY . .

# Запускаем FastAPI на порту 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]