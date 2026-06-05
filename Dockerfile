FROM python:3.11-slim

WORKDIR /code

# Устанавливаем системные библиотеки для работы с изображениями и OpenCV
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements.txt внутрь контейнера
COPY ./requirements.txt /code/requirements.txt

# Устанавливаем все питон-зависимости (включая psycopg2-binary и rembg)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Копируем оставшийся код проекта
COPY . .

# Запускаем FastAPI на порту 7860 (жесткое требование Hugging Face Spaces)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]